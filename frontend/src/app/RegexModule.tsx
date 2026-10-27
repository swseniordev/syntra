import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Icon } from '../shared/Icon';
import { EmptyState } from '../shared/EmptyState';
import { AuditMetadata } from '../shared/AuditMetadata';
import { api, ApiError } from '../shared/api';
import type { Yo } from '../shared/api';
import { StateBadge } from '../shared/StateBadge';
import { ConfirmDialog } from '../shared/ConfirmDialog';
import { useToast } from '../shared/Toast';

type Regex = { id: number; nombre: string; condicion: string; flags: string; texto_prueba: string; descripcion: string | null; version: number; estado_id: number; creado_en: string; creado_por: number | null; actualizado_en: string; actualizado_por: number | null };
type RegexPage = { items: Regex[]; siguiente: string | null; total_aprox: number };
type Match = { inicio: number; fin: number; texto: string };
type Verdict = { valida: boolean; cumple: boolean; coincidencias: Match[]; error: string | null };
type AuditEvent = { id: number; fecha: string; usuario_id: number | null; accion: string; antes: Record<string, unknown> | null; despues: Record<string, unknown> | null };
const STATES = [['vigentes', 'Vigentes'], ['activos', 'Activos'], ['inactivos', 'Inactivos'], ['eliminados', 'Eliminados']] as const;
const DESCRIPTION = 'Condiciones para etiquetar registros, filtrarlos en fiscalización y registros, y preclasificarlos según el orden definido en cada medición. Al guardar se valida contra un texto de prueba.';

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'El servidor no pudo completar la operación. Inténtalo de nuevo.';
    if (error.status === 401) return 'La sesión venció. Ingresa de nuevo.';
    if (error.status === 403) return 'No tienes permiso para realizar esta acción.';
    return error.message;
  }
  return 'No se pudo completar la operación.';
}

function VerdictView({ verdict, text, checking, error, hasCondition }: { verdict: Verdict | null; text: string; checking: boolean; error: string; hasCondition: boolean }) {
  if (!verdict) return <div className={`regex-verdict${error ? ' err' : ''}`} role="status" aria-live="polite"><Icon name={error ? 'alert' : 'info'} size={18} /><span>{error || (checking ? 'Validando expresión con RE2…' : hasCondition ? 'Escribe un texto de prueba para validar la regex.' : 'Escribe la condición para validarla contra el texto de prueba.')}</span></div>;
  if (verdict.valida && !text.trim()) return <div className="regex-verdict" role="status" aria-live="polite"><Icon name="info" size={18} /><span>Escribe un texto de prueba para validar la regex.</span></div>;
  const chars = Array.from(text);
  const segments: { text: string; match: boolean }[] = [];
  let offset = 0;
  for (const hit of verdict.coincidencias) {
    if (hit.inicio > offset) segments.push({ text: chars.slice(offset, hit.inicio).join(''), match: false });
    if (hit.fin > offset) segments.push({ text: chars.slice(Math.max(offset, hit.inicio), hit.fin).join(''), match: true });
    offset = Math.max(offset, hit.fin);
  }
  if (offset < chars.length) segments.push({ text: chars.slice(offset).join(''), match: false });
  return <div className={`regex-verdict${!verdict.valida ? ' err' : verdict.cumple ? ' ok' : ' no'}`} role="status" aria-live="polite">
    <span className={`badge ${verdict.valida && verdict.cumple ? 'info' : 'err'}`}>
      <Icon name={verdict.valida && verdict.cumple ? 'check' : 'x'} size={12} />{!verdict.valida ? 'Expresión inválida' : verdict.cumple ? 'Cumple' : 'No cumple'}
    </span>
    <span>{verdict.error || (!text.trim() ? 'Escribe un texto de prueba para validar la regex.' : verdict.cumple ? `${verdict.coincidencias.length} coincidencia(s) en el texto de prueba.` : 'La expresión no coincide con el texto de prueba.')}</span>
    {verdict.cumple && <div className="regex-highlight">{segments.map((segment, index) => segment.match ? <mark key={index}>{segment.text}</mark> : <span key={index}>{segment.text}</span>)}</div>}
  </div>;
}

export function RegexList({ yo }: { yo: Yo | null }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [state, setState] = useState<(typeof STATES)[number][0]>('vigentes');
  const [page, setPage] = useState<RegexPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<Regex | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [changingId, setChangingId] = useState<number | null>(null);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const canCreate = Boolean(yo?.permisos.regex?.includes('crear'));
  const canEdit = Boolean(yo?.permisos.regex?.includes('editar'));
  const canDelete = Boolean(yo?.permisos.regex?.includes('eliminar'));
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));

  function params(cursor?: string) {
    const result = new URLSearchParams({ estado: state, limite: '25' });
    if (query.trim()) result.set('q', query.trim());
    if (cursor) result.set('cursor', cursor);
    return result;
  }
  useEffect(() => {
    let live = true;
    setLoading(true); setPage(null);
    const timer = window.setTimeout(async () => {
      try {
        const result = await (await api(`/regex?${params()}`)).json() as RegexPage;
        if (live) { setPage(result); setNotice(''); }
      } catch (error) { if (live) setNotice(message(error)); }
      finally { if (live) setLoading(false); }
    }, 180);
    return () => { live = false; window.clearTimeout(timer); };
  }, [query, state, refresh]);
  async function loadMore() {
    if (!page?.siguiente || loadingMore) return;
    setLoadingMore(true);
    try {
      const result = await (await api(`/regex?${params(page.siguiente)}`)).json() as RegexPage;
      setPage(current => current ? { ...result, items: [...current.items, ...result.items] } : result);
    } catch (error) { setNotice(message(error)); }
    finally { setLoadingMore(false); }
  }
  async function changeState(item: Regex) {
    if (changingId !== null) return;
    setChangingId(item.id);
    try {
      await api(`/regex/${item.id}/estado`, { method: 'POST', body: JSON.stringify({ estado_id: item.estado_id === 1 ? 0 : 1 }) });
      toast(item.estado_id === 1 ? 'Inactivada' : 'Activada', item.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo cambiar el estado', message(error), 'err'); }
    finally { setChangingId(null); }
  }
  async function restore(item: Regex) {
    if (restoringId !== null) return;
    setRestoringId(item.id);
    try {
      await api(`/regex/${item.id}/restaurar`, { method: 'POST' });
      toast('Restaurada como Inactiva', item.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo restaurar', message(error), 'err'); }
    finally { setRestoringId(null); }
  }
  async function remove() {
    if (!deleteTarget || deleting) return;
    setDeleting(true); setDeleteError('');
    try {
      await api(`/regex/${deleteTarget.id}`, { method: 'DELETE' });
      toast('Eliminada lógicamente', deleteTarget.nombre);
      setDeleteTarget(null); setRefresh(value => value + 1);
    } catch (error) { setDeleteError(message(error)); toast('No se pudo eliminar', message(error), 'err'); }
    finally { setDeleting(false); }
  }
  return <>
    <div className="page-heading"><div><h1>Regex</h1><p>{DESCRIPTION}</p></div>{canCreate && <Link className="button primary heading-action" to="/regex/nueva"><Icon name="plus" size={16} />Nueva regex</Link>}</div>
    <section className="panel entity-list-panel"><div className="module-toolbar entity-toolbar" aria-label="Filtros de Regex"><label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar regex…" aria-label="Buscar regex" /></label><div className="seg status-segment" role="group" aria-label="Filtrar regex por estado">{STATES.map(([key, label]) => <button key={key} type="button" className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}</button>)}</div></div>
      {notice && <p className="control-notice error" role="alert">{notice}</p>}
      <div className="table-wrap"><table className="data-table client-table regex-table"><thead><tr><th>Regex</th><th>Texto de prueba</th><th>Versión</th><th>Estado</th><th>Actualizado</th><th>Acciones</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={6} className="empty-cell" role="status">Cargando regex…</td></tr> : page?.items.length ? page.items.map(item => <tr key={item.id} className={item.estado_id === -1 ? 'client-row-deleted' : 'client-row'} tabIndex={item.estado_id === -1 ? undefined : 0} aria-label={item.estado_id === -1 ? `Regex eliminada ${item.nombre}` : `Ver detalle de ${item.nombre}`}
          onClick={event => { if (item.estado_id !== -1 && (!(event.target instanceof Element) || !event.target.closest('a,button,[data-row-action]'))) navigate(`/regex/${item.id}`); }}
          onKeyDown={event => { if (item.estado_id !== -1 && event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); navigate(`/regex/${item.id}`); } }}>
          <td><strong>{item.nombre}</strong><div className="regex-condition">/{item.condicion}/{item.flags}</div></td><td><span className="badge info"><Icon name="check" size={11} />Cumple</span><span className="regex-sample">{item.texto_prueba}</span></td><td className="regex-version">v{item.version}</td><td><StateBadge state={item.estado_id} /></td><td>{new Date(item.actualizado_en).toLocaleDateString('es-CO')}</td>
          <td><div className="client-row-actions">{item.estado_id === -1 ? canDelete && <button className="button client-restore-action" type="button" title="Restaurar como inactiva" aria-label={`Restaurar ${item.nombre}`} disabled={restoringId === item.id} onClick={event => { event.stopPropagation(); void restore(item); }}><Icon name="undo" size={14} />Restaurar</button> : <>
            {canEdit && <><Link className="client-row-action" to={`/regex/${item.id}/editar`} title="Editar" aria-label={`Editar ${item.nombre}`} onClick={event => event.stopPropagation()}><Icon name="edit" size={16} /></Link><button className="client-row-action" type="button" title={item.estado_id === 1 ? 'Inactivar' : 'Activar'} aria-label={`${item.estado_id === 1 ? 'Inactivar' : 'Activar'} ${item.nombre}`} disabled={changingId === item.id} onClick={event => { event.stopPropagation(); void changeState(item); }}><Icon name="power" size={16} /></button></>}
            {canHistory && <Link className="client-row-action" to={`/regex/${item.id}?historial=1`} title="Ver historial de cambios" aria-label={`Ver historial de cambios de ${item.nombre}`} onClick={event => event.stopPropagation()}><Icon name="clock" size={16} /></Link>}
            {canDelete && <button className="client-row-action client-row-action-danger" type="button" title="Eliminar" aria-label={`Eliminar ${item.nombre}`} onClick={event => { event.stopPropagation(); setDeleteError(''); setDeleteTarget(item); }}><Icon name="trash" size={16} /></button>}
          </>}</div></td>
        </tr>) : <tr><td colSpan={6} className="empty-cell"><EmptyState title={state === 'eliminados' ? 'No hay registros eliminados' : query.trim() ? 'Sin resultados para los filtros' : 'Aún no hay regex'} detail={query.trim() ? 'Prueba con otro término de búsqueda.' : 'El contenido aparecerá cuando haya información disponible.'} /></td></tr>}
      </tbody></table></div>{page?.siguiente && <div className="form-actions"><button type="button" className="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? 'Cargando…' : 'Cargar más'}</button></div>}
    </section>
    {deleteTarget && <ConfirmDialog title="Eliminar regex" description={<><strong>{deleteTarget.nombre}</strong> pasará a estado Eliminado. ¿Desea Continuar?.</>} error={deleteError} busy={deleting} confirmLabel="Eliminar" busyLabel="Eliminando…" onConfirm={() => void remove()} onClose={() => setDeleteTarget(null)} />}
  </>;
}

export function RegexForm() {
  const { id } = useParams();
  const editId = id ? Number(id) : null;
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState('');
  const [condition, setCondition] = useState('');
  const [ignoreCase, setIgnoreCase] = useState(true);
  const [sample, setSample] = useState('');
  const [description, setDescription] = useState('');
  const [state, setState] = useState(1);
  const [etag, setEtag] = useState('');
  const [version, setVersion] = useState(1);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [checking, setChecking] = useState(false);
  const [testError, setTestError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(!editId);
  useEffect(() => {
    if (!editId) return;
    let live = true;
    api(`/regex/${editId}`).then(async response => {
      const item = await response.json() as Regex;
      if (live) { setName(item.nombre); setCondition(item.condicion); setIgnoreCase(item.flags.includes('i')); setSample(item.texto_prueba); setDescription(item.descripcion || ''); setState(item.estado_id); setVersion(item.version); setEtag(response.headers.get('ETag') || ''); setReady(true); }
    }).catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [editId]);
  useEffect(() => {
    let live = true;
    setVerdict(null);
    setTestError('');
    setChecking(Boolean(condition && ready));
    if (!condition || !ready) return;
    const timer = window.setTimeout(async () => {
      try {
        const response = await api('/regex/probar', { method: 'POST', body: JSON.stringify({ condicion: condition, flags: ignoreCase ? 'i' : '', texto: sample }) });
        const result = await response.json() as Verdict;
        if (live) setVerdict(result);
      } catch (error) { if (live) setTestError(message(error)); }
      finally { if (live) setChecking(false); }
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [condition, ignoreCase, sample, ready]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !ready || checking || !verdict?.valida || !verdict.cumple) {
      setNotice('La condición debe cumplir el texto de prueba según RE2 antes de guardarse.');
      return;
    }
    setBusy(true); setNotice('');
    try {
      const response = await api(editId ? `/regex/${editId}` : '/regex', {
        method: editId ? 'PATCH' : 'POST', headers: editId ? { 'If-Match': etag } : undefined,
        body: JSON.stringify({ nombre: name, condicion: condition, flags: ignoreCase ? 'i' : '', texto_prueba: sample, descripcion: description || null, estado_id: state }),
      });
      const saved = await response.json() as Regex;
      toast(editId ? 'Regex actualizada' : 'Regex creada', `${saved.nombre} · v${saved.version}`);
      navigate(`/regex/${saved.id}`);
    } catch (error) { setNotice(message(error)); toast('No se pudo guardar', message(error), 'err'); }
    finally { setBusy(false); }
  }
  return <>
    <div className="page-heading"><div><h1>{editId ? 'Editar regex' : 'Nueva regex'}</h1><p>{DESCRIPTION}</p></div></div>
    <form className="panel creation-form" onSubmit={submit}><div className="panel-heading"><h2>{editId ? `Editar regex · v${version}` : 'Nueva regex'}</h2></div><div className="creation-form-body"><div className="form-grid">
      <div className="field"><label htmlFor="regex-name">Nombre *</label><input id="regex-name" value={name} onChange={event => setName(event.target.value)} placeholder="Ej. Crisis del agua" required /></div>
      <div className="field"><label htmlFor="regex-state">Estado</label><select id="regex-state" value={state} onChange={event => setState(Number(event.target.value))}><option value={1}>Activo</option><option value={0}>Inactivo</option></select></div>
      <div className="field span2"><label htmlFor="regex-condition">Condición (expresión regular) *</label><div className="regex-condition-input"><span>/</span><input id="regex-condition" className="regex-mono" value={condition} onChange={event => setCondition(event.target.value)} placeholder={String.raw`\b(agua|sequía|pipas?)\b`} required /><span>/</span><label className="check"><input type="checkbox" checked={ignoreCase} onChange={event => setIgnoreCase(event.target.checked)} /> ignorar mayúsculas</label></div></div>
      <div className="field"><label htmlFor="regex-sample">Texto de prueba *</label><textarea id="regex-sample" value={sample} onChange={event => setSample(event.target.value)} rows={3} placeholder="Pega aquí un texto real que la regex debe encontrar." required /></div>
      <div className="field"><label htmlFor="regex-description">Descripción</label><input id="regex-description" value={description} onChange={event => setDescription(event.target.value)} placeholder="Para qué sirve esta regex" /></div>
      <div className="span2"><VerdictView verdict={verdict} text={sample} checking={checking} error={testError} hasCondition={Boolean(condition)} /></div>
    </div>{notice && <p className="control-notice error" role="alert">{notice}</p>}</div><div className="form-actions creation-actions"><Link className="button" to={editId ? `/regex/${editId}` : '/regex'}><Icon name="arrow" size={15} />Cancelar</Link><button className="button primary" type="submit" disabled={!ready || busy || checking || !verdict?.valida || !verdict.cumple}><Icon name="check" size={15} />{busy ? 'Guardando…' : 'Guardar'}</button></div></form>
  </>;
}

export function RegexDetail({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const autoHistory = searchParams.get('historial') === '1';
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));
  const [item, setItem] = useState<Regex | null>(null);
  const [notice, setNotice] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<AuditEvent[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [historyBusy, setHistoryBusy] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setItem(null); setNotice(''); setHistory([]); setHistoryOpen(false);
    api(`/regex/${id}`).then(response => response.json()).then((value: Regex) => { if (live) setItem(value); })
      .catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [id]);
  async function loadHistory(cursor?: string) {
    if (historyBusy) return;
    setHistoryOpen(true); setHistoryBusy(true); setHistoryError('');
    const params = new URLSearchParams({ limite: '25' });
    if (cursor) params.set('cursor', cursor);
    try {
      const response = await api(`/regex/${id}/historial?${params}`);
      const events = await response.json() as AuditEvent[];
      setHistory(previous => cursor ? [...previous, ...events] : events);
      setNextCursor(response.headers.get('X-Next-Cursor'));
    } catch (error) { setHistoryError(message(error)); }
    finally { setHistoryBusy(false); }
  }
  useEffect(() => { if (autoHistory && canHistory) void loadHistory(); }, [id, autoHistory, canHistory]);
  return <>
    <div className="page-heading"><div><h1>Detalle de regex</h1><p>{DESCRIPTION}</p></div>{item && item.estado_id !== -1 && yo?.permisos.regex?.includes('editar') && <Link className="button primary heading-action" to={`/regex/${item.id}/editar`}><Icon name="edit" size={16} />Editar</Link>}</div>
    {notice && <p className="control-notice error" role="alert">{notice}</p>}
    {item && <section className="panel creation-form"><div className="panel-heading"><h2>{item.nombre}</h2></div><div className="creation-form-body"><dl className="client-access-kv"><dt>Condición</dt><dd className="regex-mono">/{item.condicion}/{item.flags}</dd><dt>Texto de prueba</dt><dd>{item.texto_prueba}</dd><dt>Versión</dt><dd>v{item.version}</dd><dt>Descripción</dt><dd>{item.descripcion || '—'}</dd><dt>Estado</dt><dd><StateBadge state={item.estado_id} /></dd></dl><AuditMetadata record={item} canViewUsers={Boolean(yo?.permisos.usuarios?.includes('ver'))} /></div><div className="form-actions client-detail-actions"><Link className="button" to="/regex">Volver a Regex</Link>{canHistory && <button className="button" type="button" onClick={() => historyOpen ? setHistoryOpen(false) : void loadHistory()}><Icon name="clock" size={15} />{historyOpen ? 'Ocultar historial' : 'Ver historial de cambios'}</button>}</div></section>}
    {item && historyOpen && <section className="panel role-history" aria-label="Historial de cambios"><div className="panel-heading"><h2>Historial de cambios</h2></div>{historyError && <p className="control-notice error" role="alert">{historyError}</p>}{historyBusy && !history.length ? <p className="role-history-empty" role="status">Cargando historial…</p> : !history.length && !historyError ? <p className="role-history-empty">No hay cambios registrados para esta regex.</p> : <ol>{history.map(event => <li key={`${event.fecha}-${event.id}`}><strong>{event.accion}</strong><span>{new Date(event.fecha).toLocaleString('es-CO')} · Usuario {event.usuario_id ?? 'sistema'}</span><details><summary>Ver datos registrados</summary><pre>Antes: {JSON.stringify(event.antes, null, 2) || '—'}{'\n'}Después: {JSON.stringify(event.despues, null, 2) || '—'}</pre></details></li>)}</ol>}{nextCursor && <button className="button" type="button" disabled={historyBusy} onClick={() => void loadHistory(nextCursor)}>Ver más</button>}</section>}
  </>;
}
