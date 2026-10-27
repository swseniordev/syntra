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

type Country = {
  id: number; nombre: string; codigo: string; idioma: string; estado_id: number;
  creado_en: string; creado_por: number | null; actualizado_en: string; actualizado_por: number | null;
};
type CountryPage = { items: Country[]; siguiente: string | null; total_aprox: number };
type AuditEvent = { id: number; fecha: string; usuario_id: number | null; accion: string; antes: Record<string, unknown> | null; despues: Record<string, unknown> | null };
const STATES = [['vigentes', 'Vigentes'], ['activos', 'Activos'], ['inactivos', 'Inactivos'], ['eliminados', 'Eliminados']] as const;
const LANGUAGES = [['es-419', 'Español (Latinoamérica)'], ['es', 'Español (España)'], ['en-US', 'Inglés (EE. UU.)'], ['pt-BR', 'Portugués (Brasil)'], ['fr', 'Francés']] as const;
const DESCRIPTION = 'Países disponibles para las búsquedas de Google News en los procesos de scraping. El país define el portal (edición local) de Google News y el idioma de los resultados.';

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'El servidor no pudo completar la operación. Inténtalo de nuevo.';
    if (error.status === 401) return 'La sesión venció. Ingresa de nuevo.';
    if (error.status === 403) return 'No tienes permiso para realizar esta acción.';
    return error.message;
  }
  return 'No se pudo completar la operación.';
}

function languageLabel(value: string) { return LANGUAGES.find(([code]) => code === value)?.[1] ?? value; }

export function CountriesList({ yo }: { yo: Yo | null }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [state, setState] = useState<(typeof STATES)[number][0]>('vigentes');
  const [page, setPage] = useState<CountryPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<Country | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [changingId, setChangingId] = useState<number | null>(null);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const canCreate = Boolean(yo?.permisos.paises?.includes('crear'));
  const canEdit = Boolean(yo?.permisos.paises?.includes('editar'));
  const canDelete = Boolean(yo?.permisos.paises?.includes('eliminar'));
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));

  useEffect(() => {
    let live = true;
    setLoading(true);
    setPage(null);
    const timer = window.setTimeout(async () => {
      const params = new URLSearchParams({ estado: state, limite: '25' });
      if (query.trim()) params.set('q', query.trim());
      try {
        const result = await (await api(`/paises?${params}`)).json() as CountryPage;
        if (live) { setPage(result); setNotice(''); }
      } catch (error) { if (live) setNotice(message(error)); }
      finally { if (live) setLoading(false); }
    }, 180);
    return () => { live = false; window.clearTimeout(timer); };
  }, [query, state, refresh]);

  async function loadMore() {
    if (!page?.siguiente || loadingMore) return;
    setLoadingMore(true);
    const params = new URLSearchParams({ estado: state, limite: '25', cursor: page.siguiente });
    if (query.trim()) params.set('q', query.trim());
    try {
      const result = await (await api(`/paises?${params}`)).json() as CountryPage;
      setPage(current => current ? { ...result, items: [...current.items, ...result.items] } : result);
    } catch (error) { setNotice(message(error)); }
    finally { setLoadingMore(false); }
  }

  async function changeState(country: Country) {
    if (changingId !== null) return;
    setChangingId(country.id);
    try {
      await api(`/paises/${country.id}/estado`, { method: 'POST', body: JSON.stringify({ estado_id: country.estado_id === 1 ? 0 : 1 }) });
      toast(country.estado_id === 1 ? 'Inactivado' : 'Activado', country.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo cambiar el estado', message(error), 'err'); }
    finally { setChangingId(null); }
  }

  async function restore(country: Country) {
    if (restoringId !== null) return;
    setRestoringId(country.id);
    try {
      await api(`/paises/${country.id}/restaurar`, { method: 'POST' });
      toast('Restaurado como Inactivo', country.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo restaurar', message(error), 'err'); }
    finally { setRestoringId(null); }
  }

  async function remove() {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await api(`/paises/${deleteTarget.id}`, { method: 'DELETE' });
      toast('Eliminado lógicamente', deleteTarget.nombre);
      setDeleteTarget(null);
      setRefresh(value => value + 1);
    } catch (error) { setDeleteError(message(error)); toast('No se pudo eliminar', message(error), 'err'); }
    finally { setDeleting(false); }
  }

  return <>
    <div className="page-heading"><div><h1>Países (Google News)</h1><p>{DESCRIPTION}</p></div>{canCreate && <Link className="button primary heading-action" to="/paises/nuevo"><Icon name="plus" size={16} />Nuevo país</Link>}</div>
    <section className="panel entity-list-panel">
      <div className="module-toolbar entity-toolbar" aria-label="Filtros de Países"><label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar países…" aria-label="Buscar países" /></label><div className="seg status-segment" role="group" aria-label="Filtrar países por estado">{STATES.map(([key, label]) => <button key={key} type="button" className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}</button>)}</div></div>
      {notice && <p className="control-notice error" role="alert">{notice}</p>}
      <div className="table-wrap"><table className="data-table client-table country-table"><thead><tr><th>País</th><th>Idioma</th><th>Edición de Google News</th><th>Estado</th><th>Actualizado</th><th>Acciones</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={6} className="empty-cell" role="status">Cargando países…</td></tr> : page?.items.length ? page.items.map(country => <tr key={country.id} className={country.estado_id === -1 ? 'client-row-deleted' : 'client-row'} tabIndex={country.estado_id === -1 ? undefined : 0} aria-label={country.estado_id === -1 ? `País eliminado ${country.nombre}` : `Ver detalle de ${country.nombre}`}
          onClick={event => { if (country.estado_id !== -1 && (!(event.target instanceof Element) || !event.target.closest('a,button,[data-row-action]'))) navigate(`/paises/${country.id}`); }}
          onKeyDown={event => { if (country.estado_id !== -1 && event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); navigate(`/paises/${country.id}`); } }}>
          <td><div className="cell-main"><span className="avatar small country-code">{country.codigo}</span><span><strong>{country.nombre}</strong><small>Código ISO {country.codigo}</small></span></div></td>
          <td>{languageLabel(country.idioma)}</td><td className="country-edition">hl={country.idioma}&amp;gl={country.codigo}&amp;ceid={country.codigo}:{country.idioma}</td><td><StateBadge state={country.estado_id} /></td><td>{new Date(country.actualizado_en).toLocaleDateString('es-CO')}</td>
          <td><div className="client-row-actions">{country.estado_id === -1 ? canDelete && <button className="button client-restore-action" type="button" title="Restaurar como inactivo" aria-label={`Restaurar ${country.nombre}`} disabled={restoringId === country.id} onClick={event => { event.stopPropagation(); void restore(country); }}><Icon name="undo" size={14} />Restaurar</button> : <>
            {canEdit && <><Link className="client-row-action" to={`/paises/${country.id}/editar`} title="Editar" aria-label={`Editar ${country.nombre}`} onClick={event => event.stopPropagation()}><Icon name="edit" size={16} /></Link><button className="client-row-action" type="button" title={country.estado_id === 1 ? 'Inactivar' : 'Activar'} aria-label={`${country.estado_id === 1 ? 'Inactivar' : 'Activar'} ${country.nombre}`} disabled={changingId === country.id} onClick={event => { event.stopPropagation(); void changeState(country); }}><Icon name="power" size={16} /></button></>}
            {canHistory && <Link className="client-row-action" to={`/paises/${country.id}?historial=1`} title="Ver historial de cambios" aria-label={`Ver historial de cambios de ${country.nombre}`} onClick={event => event.stopPropagation()}><Icon name="clock" size={16} /></Link>}
            {canDelete && <button className="client-row-action client-row-action-danger" type="button" title="Eliminar" aria-label={`Eliminar ${country.nombre}`} onClick={event => { event.stopPropagation(); setDeleteError(''); setDeleteTarget(country); }}><Icon name="trash" size={16} /></button>}
          </>}</div></td>
        </tr>) : <tr><td colSpan={6} className="empty-cell"><EmptyState title={state === 'eliminados' ? 'No hay registros eliminados' : query.trim() ? 'Sin resultados para los filtros' : 'Aún no hay países'} detail={query.trim() ? 'Prueba con otro término de búsqueda.' : 'El contenido aparecerá cuando haya información disponible.'} /></td></tr>}
      </tbody></table></div>
      {page?.siguiente && <div className="form-actions"><button type="button" className="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? 'Cargando…' : 'Cargar más'}</button></div>}
    </section>
    {deleteTarget && <ConfirmDialog title="Eliminar país" description={<><strong>{deleteTarget.nombre}</strong> pasará a estado Eliminado. ¿Desea Continuar?.</>} error={deleteError} busy={deleting} confirmLabel="Eliminar" busyLabel="Eliminando…" onConfirm={() => void remove()} onClose={() => setDeleteTarget(null)} />}
  </>;
}

export function CountryForm() {
  const { id } = useParams();
  const editId = id ? Number(id) : null;
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [language, setLanguage] = useState('es-419');
  const [state, setState] = useState(1);
  const [etag, setEtag] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(!editId);
  useEffect(() => {
    if (!editId) return;
    let live = true;
    api(`/paises/${editId}`).then(async response => {
      const country = await response.json() as Country;
      if (live) { setName(country.nombre); setCode(country.codigo); setLanguage(country.idioma); setState(country.estado_id); setEtag(response.headers.get('ETag') || ''); setReady(true); }
    }).catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [editId]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !ready) return;
    setBusy(true); setNotice('');
    try {
      const response = await api(editId ? `/paises/${editId}` : '/paises', {
        method: editId ? 'PATCH' : 'POST', headers: editId ? { 'If-Match': etag } : undefined,
        body: JSON.stringify({ nombre: name, codigo: code, idioma: language, estado_id: state }),
      });
      const saved = await response.json() as Country;
      toast(editId ? 'País actualizado' : 'País creado', saved.nombre);
      navigate(`/paises/${saved.id}`);
    } catch (error) { setNotice(message(error)); toast('No se pudo guardar', message(error), 'err'); }
    finally { setBusy(false); }
  }
  return <>
    <div className="page-heading"><div><h1>{editId ? 'Editar país' : 'Nuevo país'}</h1><p>{DESCRIPTION}</p></div></div>
    <form className="panel creation-form" onSubmit={submit}><div className="panel-heading"><h2>{editId ? 'Editar país' : 'Nuevo país'}</h2></div><div className="creation-form-body"><div className="form-grid">
      <div className="field"><label htmlFor="country-name">Nombre del país *</label><input id="country-name" value={name} onChange={event => setName(event.target.value)} required placeholder="Ej. México" /></div>
      <div className="field"><label htmlFor="country-code">Código ISO (2 letras) *</label><input id="country-code" value={code} onChange={event => setCode(event.target.value.toUpperCase())} maxLength={2} pattern="[A-Z]{2}" required placeholder="MX" className="country-code-input" /><span className="help">ISO 3166-1 alfa-2. Define el portal de Google News.</span></div>
      <div className="field"><label htmlFor="country-language">Idioma de los resultados</label><select id="country-language" value={language} onChange={event => setLanguage(event.target.value)}>{LANGUAGES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></div>
      <div className="field"><label htmlFor="country-state">Estado</label><select id="country-state" value={state} onChange={event => setState(Number(event.target.value))}><option value={1}>Activo</option><option value={0}>Inactivo</option></select></div>
    </div>{notice && <p className="control-notice error" role="alert">{notice}</p>}</div><div className="form-actions creation-actions"><Link className="button" to={editId ? `/paises/${editId}` : '/paises'}><Icon name="arrow" size={15} />Cancelar</Link><button className="button primary" type="submit" disabled={!ready || busy}><Icon name="check" size={15} />{busy ? 'Guardando…' : 'Guardar'}</button></div></form>
  </>;
}

export function CountryDetail({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const autoHistory = searchParams.get('historial') === '1';
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));
  const [country, setCountry] = useState<Country | null>(null);
  const [notice, setNotice] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<AuditEvent[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [historyBusy, setHistoryBusy] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setCountry(null); setNotice(''); setHistory([]); setHistoryOpen(false);
    api(`/paises/${id}`).then(response => response.json()).then((value: Country) => { if (live) setCountry(value); })
      .catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [id]);
  async function loadHistory(cursor?: string) {
    if (historyBusy) return;
    setHistoryOpen(true); setHistoryBusy(true); setHistoryError('');
    const params = new URLSearchParams({ limite: '25' });
    if (cursor) params.set('cursor', cursor);
    try {
      const response = await api(`/paises/${id}/historial?${params}`);
      const events = await response.json() as AuditEvent[];
      setHistory(previous => cursor ? [...previous, ...events] : events);
      setNextCursor(response.headers.get('X-Next-Cursor'));
    } catch (error) { setHistoryError(message(error)); }
    finally { setHistoryBusy(false); }
  }
  useEffect(() => { if (autoHistory && canHistory) void loadHistory(); }, [id, autoHistory, canHistory]);
  return <>
    <div className="page-heading"><div><h1>Detalle de país</h1><p>{DESCRIPTION}</p></div>{country && country.estado_id !== -1 && yo?.permisos.paises?.includes('editar') && <Link className="button primary heading-action" to={`/paises/${country.id}/editar`}><Icon name="edit" size={16} />Editar</Link>}</div>
    {notice && <p className="control-notice error" role="alert">{notice}</p>}
    {country && <section className="panel creation-form"><div className="panel-heading"><h2>{country.nombre}</h2></div><div className="creation-form-body"><dl className="client-access-kv"><dt>Código ISO</dt><dd>{country.codigo}</dd><dt>Idioma</dt><dd>{languageLabel(country.idioma)}</dd><dt>Edición de Google News</dt><dd>hl={country.idioma}&amp;gl={country.codigo}&amp;ceid={country.codigo}:{country.idioma}</dd><dt>Estado</dt><dd><StateBadge state={country.estado_id} /></dd></dl><AuditMetadata record={country} canViewUsers={Boolean(yo?.permisos.usuarios?.includes('ver'))} /></div><div className="form-actions client-detail-actions"><Link className="button" to="/paises">Volver a Países</Link>{canHistory && <button className="button" type="button" onClick={() => historyOpen ? setHistoryOpen(false) : void loadHistory()}><Icon name="clock" size={15} />{historyOpen ? 'Ocultar historial' : 'Ver historial de cambios'}</button>}</div></section>}
    {country && historyOpen && <section className="panel role-history" aria-label="Historial de cambios"><div className="panel-heading"><h2>Historial de cambios</h2></div>{historyError && <p className="control-notice error" role="alert">{historyError}</p>}{historyBusy && !history.length ? <p className="role-history-empty" role="status">Cargando historial…</p> : !history.length && !historyError ? <p className="role-history-empty">No hay cambios registrados para este país.</p> : <ol>{history.map(event => <li key={`${event.fecha}-${event.id}`}><strong>{event.accion}</strong><span>{new Date(event.fecha).toLocaleString('es-CO')} · Usuario {event.usuario_id ?? 'sistema'}</span><details><summary>Ver datos registrados</summary><pre>Antes: {JSON.stringify(event.antes, null, 2) || '—'}{'\n'}Después: {JSON.stringify(event.despues, null, 2) || '—'}</pre></details></li>)}</ol>}{nextCursor && <button className="button" type="button" disabled={historyBusy} onClick={() => void loadHistory(nextCursor)}>Ver más</button>}</section>}
  </>;
}
