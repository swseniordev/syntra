import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Icon } from '../../shared/Icon';
import { EmptyState } from '../../shared/EmptyState';
import { AuditMetadata } from '../../shared/AuditMetadata';
import { api, ApiError } from '../../shared/api';
import type { Yo } from '../../shared/api';
import { StateBadge } from '../../shared/StateBadge';
import { ConfirmDialog } from '../../shared/ConfirmDialog';
import { useToast } from '../../shared/Toast';

type Prompt = { id: number; tipo: string; red: string | null; nombre: string; contenido: string; por_defecto: boolean; version_actual: number; estado_id: number; creado_en: string; creado_por: number | null; actualizado_en: string; actualizado_por: number | null };
type PromptPage = { items: Prompt[]; siguiente: string | null; total_aprox: number };
type PromptVersion = { version: number; contenido: string; creado_en: string; creado_por: number | null };
type AuditEvent = { id: number; fecha: string; usuario_id: number | null; accion: string; antes: Record<string, unknown> | null; despues: Record<string, unknown> | null };
const STATES = [['vigentes', 'Vigentes'], ['activos', 'Activos'], ['inactivos', 'Inactivos'], ['eliminados', 'Eliminados']] as const;
const TYPES = [['cluster', 'Clusters'], ['temas', 'Temas finales'], ['relevancia', 'Relevancia'], ['sentimiento', 'Sentimiento'], ['etiqueta_cluster', 'Etiqueta de cluster']] as const;
const NETWORKS = [['x', 'X'], ['tiktok', 'TikTok'], ['youtube', 'YouTube'], ['facebook', 'Facebook'], ['instagram', 'Instagram'], ['medios', 'Medios']] as const;
const VARIABLES = ['{{cuenta}}', '{{num_clusters}}', '{{num_subclusters}}'];
const DESCRIPTION = 'Plantillas base para clusters, temas finales, relevancia y sentimiento. Los de relevancia y sentimiento pueden ser específicos de una red social; en cada medición se ajustan por red.';
const perNetwork = (kind: string) => kind === 'relevancia' || kind === 'sentimiento';
const typeLabel = (value: string) => TYPES.find(([code]) => code === value)?.[1] ?? value;
const networkLabel = (value: string | null) => value ? NETWORKS.find(([code]) => code === value)?.[1] ?? value : 'General';

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'El servidor no pudo completar la operación. Inténtalo de nuevo.';
    if (error.status === 401) return 'La sesión venció. Ingresa de nuevo.';
    if (error.status === 403) return 'No tienes permiso para realizar esta acción.';
    return error.message;
  }
  return 'No se pudo completar la operación.';
}

export function PromptsList({ yo }: { yo: Yo | null }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [state, setState] = useState<(typeof STATES)[number][0]>('vigentes');
  const [kind, setKind] = useState('');
  const [network, setNetwork] = useState('');
  const [page, setPage] = useState<PromptPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<Prompt | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [changingId, setChangingId] = useState<number | null>(null);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const canCreate = Boolean(yo?.permisos.prompts?.includes('crear'));
  const canEdit = Boolean(yo?.permisos.prompts?.includes('editar'));
  const canDelete = Boolean(yo?.permisos.prompts?.includes('eliminar'));
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));

  function params(cursor?: string) {
    const result = new URLSearchParams({ estado: state, limite: '25' });
    if (query.trim()) result.set('q', query.trim());
    if (kind) result.set('tipo', kind);
    if (network) result.set('red', network);
    if (cursor) result.set('cursor', cursor);
    return result;
  }
  useEffect(() => {
    let live = true;
    setLoading(true); setPage(null);
    const timer = window.setTimeout(async () => {
      try {
        const data = await (await api(`/prompts?${params()}`)).json() as PromptPage;
        if (live) { setPage(data); setNotice(''); }
      } catch (error) { if (live) setNotice(message(error)); }
      finally { if (live) setLoading(false); }
    }, 180);
    return () => { live = false; window.clearTimeout(timer); };
  }, [query, state, kind, network, refresh]);

  async function loadMore() {
    if (!page?.siguiente || loadingMore) return;
    setLoadingMore(true);
    try {
      const data = await (await api(`/prompts?${params(page.siguiente)}`)).json() as PromptPage;
      setPage(current => current ? { ...data, items: [...current.items, ...data.items] } : data);
    } catch (error) { setNotice(message(error)); }
    finally { setLoadingMore(false); }
  }
  async function changeState(prompt: Prompt) {
    if (changingId !== null) return;
    setChangingId(prompt.id);
    try {
      await api(`/prompts/${prompt.id}/estado`, { method: 'POST', body: JSON.stringify({ estado_id: prompt.estado_id === 1 ? 0 : 1 }) });
      toast(prompt.estado_id === 1 ? 'Inactivado' : 'Activado', prompt.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo cambiar el estado', message(error), 'err'); }
    finally { setChangingId(null); }
  }
  async function restore(prompt: Prompt) {
    if (restoringId !== null) return;
    setRestoringId(prompt.id);
    try {
      await api(`/prompts/${prompt.id}/restaurar`, { method: 'POST' });
      toast('Restaurado como Inactivo', prompt.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo restaurar', message(error), 'err'); }
    finally { setRestoringId(null); }
  }
  async function remove() {
    if (!deleteTarget || deleting) return;
    setDeleting(true); setDeleteError('');
    try {
      await api(`/prompts/${deleteTarget.id}`, { method: 'DELETE' });
      toast('Eliminado lógicamente', deleteTarget.nombre);
      setDeleteTarget(null);
      setRefresh(value => value + 1);
    } catch (error) { setDeleteError(message(error)); toast('No se pudo eliminar', message(error), 'err'); }
    finally { setDeleting(false); }
  }

  return <>
    <div className="page-heading"><div><h1>Prompts por defecto</h1><p>{DESCRIPTION}</p></div>{canCreate && <Link className="button primary heading-action" to="/prompts/nuevo"><Icon name="plus" size={16} />Nuevo prompt</Link>}</div>
    <section className="panel entity-list-panel">
      <div className="module-toolbar entity-toolbar" aria-label="Filtros de Prompts"><label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar prompts…" aria-label="Buscar prompts" /></label><select aria-label="Tipo" value={kind} onChange={event => setKind(event.target.value)}><option value="">Tipo: todos</option>{TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select aria-label="Red" value={network} onChange={event => setNetwork(event.target.value)}><option value="">Red: todas</option><option value="_">General (todas)</option>{NETWORKS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><div className="seg status-segment" role="group" aria-label="Filtrar prompts por estado">{STATES.map(([key, label]) => <button key={key} type="button" className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}</button>)}</div></div>
      {notice && <p className="control-notice error" role="alert">{notice}</p>}
      <div className="table-wrap"><table className="data-table client-table prompts-table"><thead><tr><th>Prompt</th><th>Tipo</th><th>Red</th><th>Versión</th><th>Por defecto</th><th>Estado</th><th>Actualizado</th><th>Acciones</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={8} className="empty-cell" role="status">Cargando prompts…</td></tr> : page?.items.length ? page.items.map(prompt => <tr key={prompt.id} className={prompt.estado_id === -1 ? 'client-row-deleted' : 'client-row'} tabIndex={prompt.estado_id === -1 ? undefined : 0} aria-label={prompt.estado_id === -1 ? `Prompt eliminado ${prompt.nombre}` : `Ver detalle de ${prompt.nombre}`}
          onClick={event => { if (prompt.estado_id !== -1 && (!(event.target instanceof Element) || !event.target.closest('a,button,[data-row-action]'))) navigate(`/prompts/${prompt.id}`); }}
          onKeyDown={event => { if (prompt.estado_id !== -1 && event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); navigate(`/prompts/${prompt.id}`); } }}>
          <td><div className="cell-main"><span className="avatar small"><Icon name="sparkles" size={14} /></span><span><strong>{prompt.nombre}</strong><small>{prompt.contenido.slice(0, 70)}{prompt.contenido.length > 70 ? '…' : ''}</small></span></div></td><td><span className="badge info">{typeLabel(prompt.tipo)}</span></td><td>{networkLabel(prompt.red)}</td><td className="prompt-version">v{prompt.version_actual}</td><td>{prompt.por_defecto ? <span className="badge grad">★ Por defecto</span> : '—'}</td><td><StateBadge state={prompt.estado_id} /></td><td>{new Date(prompt.actualizado_en).toLocaleDateString('es-CO')}</td>
          <td><div className="client-row-actions">{prompt.estado_id === -1 ? canDelete && <button className="button client-restore-action" type="button" title="Restaurar como inactivo" aria-label={`Restaurar ${prompt.nombre}`} disabled={restoringId === prompt.id} onClick={event => { event.stopPropagation(); void restore(prompt); }}><Icon name="undo" size={14} />Restaurar</button> : <>
            {canEdit && <><Link className="client-row-action" to={`/prompts/${prompt.id}/editar`} title="Editar" aria-label={`Editar ${prompt.nombre}`} onClick={event => event.stopPropagation()}><Icon name="edit" size={16} /></Link><button className="client-row-action" type="button" title={prompt.estado_id === 1 ? 'Inactivar' : 'Activar'} aria-label={`${prompt.estado_id === 1 ? 'Inactivar' : 'Activar'} ${prompt.nombre}`} disabled={changingId === prompt.id} onClick={event => { event.stopPropagation(); void changeState(prompt); }}><Icon name="power" size={16} /></button></>}
            {canHistory && <Link className="client-row-action" to={`/prompts/${prompt.id}?historial=1`} title="Ver historial de cambios" aria-label={`Ver historial de cambios de ${prompt.nombre}`} onClick={event => event.stopPropagation()}><Icon name="clock" size={16} /></Link>}
            {canDelete && <button className="client-row-action client-row-action-danger" type="button" title="Eliminar" aria-label={`Eliminar ${prompt.nombre}`} onClick={event => { event.stopPropagation(); setDeleteError(''); setDeleteTarget(prompt); }}><Icon name="trash" size={16} /></button>}
          </>}</div></td>
        </tr>) : <tr><td colSpan={8} className="empty-cell"><EmptyState title={state === 'eliminados' ? 'No hay registros eliminados' : query.trim() ? 'Sin resultados para los filtros' : 'Aún no hay prompts'} detail={query.trim() ? 'Prueba con otro término de búsqueda.' : 'El contenido aparecerá cuando haya información disponible.'} /></td></tr>}
      </tbody></table></div>{page?.siguiente && <div className="form-actions"><button type="button" className="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? 'Cargando…' : 'Cargar más'}</button></div>}
    </section>
    {deleteTarget && <ConfirmDialog title="Eliminar prompt" description={<><strong>{deleteTarget.nombre}</strong> pasará a estado Eliminado. ¿Desea Continuar?.</>} error={deleteError} busy={deleting} confirmLabel="Eliminar" busyLabel="Eliminando…" onConfirm={() => void remove()} onClose={() => setDeleteTarget(null)} />}
  </>;
}

export function PromptForm() {
  const { id } = useParams();
  const editId = id ? Number(id) : null;
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState('');
  const [kind, setKind] = useState('cluster');
  const [network, setNetwork] = useState('');
  const [content, setContent] = useState('');
  const [isDefault, setIsDefault] = useState(false);
  const [state, setState] = useState(1);
  const [version, setVersion] = useState(0);
  const [etag, setEtag] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(!editId);
  useEffect(() => {
    if (!editId) return;
    let live = true;
    api(`/prompts/${editId}`).then(async response => {
      const prompt = await response.json() as Prompt;
      if (live) { setName(prompt.nombre); setKind(prompt.tipo); setNetwork(prompt.red || ''); setContent(prompt.contenido); setIsDefault(prompt.por_defecto); setState(prompt.estado_id); setVersion(prompt.version_actual); setEtag(response.headers.get('ETag') || ''); setReady(true); }
    }).catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [editId]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !ready) return;
    if (content.trim().length < 20) { setNotice('El prompt debe tener al menos 20 caracteres.'); return; }
    if (isDefault && state !== 1) { setNotice('Un prompt por defecto debe estar activo.'); return; }
    setBusy(true); setNotice('');
    try {
      const response = await api(editId ? `/prompts/${editId}` : '/prompts', {
        method: editId ? 'PATCH' : 'POST', headers: editId ? { 'If-Match': etag } : undefined,
        body: JSON.stringify({ tipo: kind, red: perNetwork(kind) ? network || null : null,
          nombre: name, contenido: content, por_defecto: isDefault, estado_id: state }),
      });
      const saved = await response.json() as Prompt;
      toast(editId ? 'Prompt actualizado' : 'Prompt creado', `${saved.nombre} · v${saved.version_actual}`);
      navigate(`/prompts/${saved.id}`);
    } catch (error) { setNotice(message(error)); toast('No se pudo guardar', message(error), 'err'); }
    finally { setBusy(false); }
  }
  function addVariable(value: string) { setContent(current => current + value); }
  return <>
    <div className="page-heading"><div><h1>{editId ? 'Editar prompt' : 'Nuevo prompt'}</h1><p>{DESCRIPTION}</p></div></div>
    <form className="panel creation-form" onSubmit={submit}><div className="panel-heading"><h2>{editId ? 'Editar prompt' : 'Nuevo prompt'}</h2></div><div className="creation-form-body"><div className="form-grid">
      <div className="field"><label htmlFor="prompt-name">Nombre *</label><input id="prompt-name" value={name} onChange={event => setName(event.target.value)} required /></div>
      <div className="field"><label htmlFor="prompt-type">Tipo</label><select id="prompt-type" value={kind} onChange={event => { setKind(event.target.value); if (!perNetwork(event.target.value)) setNetwork(''); }}>{TYPES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></div>
      {perNetwork(kind) && <div className="field"><label htmlFor="prompt-network">Red social</label><select id="prompt-network" value={network} onChange={event => setNetwork(event.target.value)}><option value="">General (todas las redes)</option>{NETWORKS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span className="help">Úsalo como ajuste para una red específica.</span></div>}
      <div className="field"><label htmlFor="prompt-state">Estado</label><select id="prompt-state" value={state} onChange={event => setState(Number(event.target.value))}><option value={1}>Activo</option><option value={0}>Inactivo</option></select></div>
      <label className="create-check span2"><input type="checkbox" checked={isDefault} onChange={event => setIsDefault(event.target.checked)} /><span>Usar como prompt por defecto de su tipo y red</span></label>
      <div className="field span2"><label htmlFor="prompt-content">Contenido del prompt *</label><div className="chips prompt-variables">{VARIABLES.map(variable => <button className="chip" type="button" key={variable} onClick={() => addVariable(variable)}>{variable}</button>)}</div><textarea id="prompt-content" rows={12} className="code" value={content} onChange={event => setContent(event.target.value)} required /><span className="help">{content.length} caracteres · ~{Math.ceil(content.length / 4)} tokens{version ? ` · al cambiar el contenido se crea la versión v${version + 1}` : ''}</span></div>
    </div>{notice && <p className="control-notice error" role="alert">{notice}</p>}</div><div className="form-actions creation-actions"><Link className="button" to={editId ? `/prompts/${editId}` : '/prompts'}><Icon name="arrow" size={15} />Cancelar</Link><button className="button primary" type="submit" disabled={!ready || busy}><Icon name="check" size={15} />{busy ? 'Guardando…' : 'Guardar'}</button></div></form>
  </>;
}

export function PromptDetail({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const autoHistory = searchParams.get('historial') === '1';
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));
  const [prompt, setPrompt] = useState<Prompt | null>(null);
  const [notice, setNotice] = useState('');
  const [versions, setVersions] = useState<PromptVersion[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<AuditEvent[]>([]);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setPrompt(null); setNotice(''); setHistory([]); setHistoryOpen(false);
    Promise.all([api(`/prompts/${id}`), api(`/prompts/${id}/versiones`)]).then(async ([detail, versionResponse]) => {
      const [row, versionRows] = await Promise.all([detail.json() as Promise<Prompt>, versionResponse.json() as Promise<PromptVersion[]>]);
      if (live) { setPrompt(row); setVersions(versionRows); }
    }).catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [id]);
  async function loadHistory(cursor?: string) {
    if (historyBusy) return;
    setHistoryOpen(true); setHistoryBusy(true); setHistoryError('');
    const params = new URLSearchParams({ limite: '25' });
    if (cursor) params.set('cursor', cursor);
    try {
      const response = await api(`/prompts/${id}/historial?${params}`);
      const events = await response.json() as AuditEvent[];
      setHistory(previous => cursor ? [...previous, ...events] : events);
      setNextCursor(response.headers.get('X-Next-Cursor'));
    } catch (error) { setHistoryError(message(error)); }
    finally { setHistoryBusy(false); }
  }
  useEffect(() => { if (autoHistory && canHistory) void loadHistory(); }, [id, autoHistory, canHistory]);
  return <>
    <div className="page-heading"><div><h1>Detalle de prompt</h1><p>{DESCRIPTION}</p></div>{prompt && prompt.estado_id !== -1 && yo?.permisos.prompts?.includes('editar') && <Link className="button primary heading-action" to={`/prompts/${prompt.id}/editar`}><Icon name="edit" size={16} />Editar</Link>}</div>
    {notice && <p className="control-notice error" role="alert">{notice}</p>}
    {prompt && <section className="panel creation-form"><div className="panel-heading"><h2>{prompt.nombre}</h2></div><div className="creation-form-body"><dl className="client-access-kv"><dt>Tipo</dt><dd>{typeLabel(prompt.tipo)}</dd><dt>Red</dt><dd>{networkLabel(prompt.red)}</dd><dt>Versión</dt><dd>v{prompt.version_actual}</dd><dt>Por defecto</dt><dd>{prompt.por_defecto ? <span className="badge grad">★ Por defecto</span> : 'No'}</dd><dt>Estado</dt><dd><StateBadge state={prompt.estado_id} /></dd></dl><div className="field prompt-detail-content"><label>Contenido</label><pre>{prompt.contenido}</pre></div><div className="field prompt-detail-versions"><label>Versiones inmutables</label>{versions.length ? <ol>{versions.map(item => <li key={item.version}><details><summary>v{item.version} · {new Date(item.creado_en).toLocaleString('es-CO')}</summary><pre>{item.contenido}</pre></details></li>)}</ol> : <p>No hay versiones registradas.</p>}</div><AuditMetadata record={prompt} canViewUsers={Boolean(yo?.permisos.usuarios?.includes('ver'))} /></div><div className="form-actions client-detail-actions"><Link className="button" to="/prompts">Volver a Prompts</Link>{canHistory && <button className="button" type="button" onClick={() => historyOpen ? setHistoryOpen(false) : void loadHistory()}><Icon name="clock" size={15} />{historyOpen ? 'Ocultar historial' : 'Ver historial de cambios'}</button>}</div></section>}
    {prompt && historyOpen && <section className="panel role-history" aria-label="Historial de cambios"><div className="panel-heading"><h2>Historial de cambios</h2></div>{historyError && <p className="control-notice error" role="alert">{historyError}</p>}{historyBusy && !history.length ? <p className="role-history-empty" role="status">Cargando historial…</p> : !history.length && !historyError ? <p className="role-history-empty">No hay cambios registrados para este prompt.</p> : <ol>{history.map(event => <li key={`${event.fecha}-${event.id}`}><strong>{event.accion}</strong><span>{new Date(event.fecha).toLocaleString('es-CO')} · Usuario {event.usuario_id ?? 'sistema'}</span><details><summary>Ver datos registrados</summary><pre>Antes: {JSON.stringify(event.antes, null, 2) || '—'}{'\n'}Después: {JSON.stringify(event.despues, null, 2) || '—'}</pre></details></li>)}</ol>}{nextCursor && <button className="button" type="button" disabled={historyBusy} onClick={() => void loadHistory(nextCursor)}>Ver más</button>}</section>}
  </>;
}
