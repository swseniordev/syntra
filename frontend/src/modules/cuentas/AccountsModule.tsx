import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Icon } from '../../shared/Icon';
import { EmptyState } from '../../shared/EmptyState';
import { AuditMetadata } from '../../shared/AuditMetadata';
import { api, ApiError } from '../../shared/api';
import type { Cliente, Yo } from '../../shared/api';
import { StateBadge } from '../../shared/StateBadge';
import { ConfirmDialog } from '../../shared/ConfirmDialog';
import { useToast } from '../../shared/Toast';

type Account = { id: number; cliente_id: number; cliente_nombre: string; nombre: string; actor_principal: string | null; entidad: string | null; taxonomia: string | null; prompt_clusters: string; prompt_temas: string; estado_id: number; creado_en: string; creado_por: number | null; actualizado_en: string; actualizado_por: number | null };
type AccountPage = { items: Account[]; siguiente: string | null; total_aprox: number };
type ClientPage = { items: Cliente[]; siguiente: string | null };
type Prompt = { id: number; tipo: string; nombre: string; contenido: string; por_defecto: boolean; version_actual: number };
type PromptPage = { items: Prompt[]; siguiente: string | null };
type AuditEvent = { id: number; fecha: string; usuario_id: number | null; accion: string; antes: Record<string, unknown> | null; despues: Record<string, unknown> | null };
const STATES = [['vigentes', 'Vigentes'], ['activos', 'Activos'], ['inactivos', 'Inactivos'], ['eliminados', 'Eliminados']] as const;
const TAXONOMIES = [['gobierno', 'Gobierno estatal'], ['comparativo', 'Comparativo de gobernadores'], ['electoral', 'Electoral / partidos']] as const;
const DESCRIPTION = 'Unidad de monitoreo de un cliente (marca, producto o tema). Define los prompts base de clusters y temas finales.';

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'El servidor no pudo completar la operación. Inténtalo de nuevo.';
    if (error.status === 401) return 'La sesión venció. Ingresa de nuevo.';
    if (error.status === 403) return 'No tienes permiso para realizar esta acción.';
    return error.message;
  }
  return 'No se pudo completar la operación.';
}

async function loadClients(): Promise<Cliente[]> {
  const rows: Cliente[] = [];
  let cursor: string | null = null;
  do {
    const params = new URLSearchParams({ estado: 'activos', limite: '200' });
    if (cursor) params.set('cursor', cursor);
    const page: ClientPage = await (await api(`/clientes?${params}`)).json();
    rows.push(...page.items);
    cursor = page.siguiente;
  } while (cursor);
  return rows;
}

async function loadPrompts(kind: 'cluster' | 'temas'): Promise<Prompt[]> {
  const rows: Prompt[] = [];
  let cursor: string | null = null;
  do {
    const params = new URLSearchParams({ estado: 'activos', tipo: kind, limite: '200' });
    if (cursor) params.set('cursor', cursor);
    const page: PromptPage = await (await api(`/prompts?${params}`)).json();
    rows.push(...page.items);
    cursor = page.siguiente;
  } while (cursor);
  return rows;
}

export function AccountsList({ yo }: { yo: Yo | null }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [state, setState] = useState<(typeof STATES)[number][0]>('vigentes');
  const [clientId, setClientId] = useState('');
  const [clientOptions, setClientOptions] = useState<Array<{ id: number; nombre: string }>>([]);
  const [page, setPage] = useState<AccountPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<Account | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [changingId, setChangingId] = useState<number | null>(null);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const canCreate = Boolean(yo?.permisos.cuentas?.includes('crear'));
  const canEdit = Boolean(yo?.permisos.cuentas?.includes('editar'));
  const canDelete = Boolean(yo?.permisos.cuentas?.includes('eliminar'));
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));
  const canReadClients = Boolean(yo?.permisos.clientes?.includes('ver'));

  useEffect(() => {
    if (!canReadClients) return;
    let live = true;
    loadClients().then(rows => { if (live) setClientOptions(rows.map(row => ({ id: row.id, nombre: row.nombre }))); })
      .catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [canReadClients]);
  function params(cursor?: string) {
    const result = new URLSearchParams({ estado: state, limite: '25' });
    if (query.trim()) result.set('q', query.trim());
    if (clientId) result.set('cliente_id', clientId);
    if (cursor) result.set('cursor', cursor);
    return result;
  }
  useEffect(() => {
    let live = true;
    setLoading(true); setPage(null);
    const timer = window.setTimeout(async () => {
      try {
        const result = await (await api(`/cuentas?${params()}`)).json() as AccountPage;
        if (live) { setPage(result); setNotice(''); }
      } catch (error) { if (live) setNotice(message(error)); }
      finally { if (live) setLoading(false); }
    }, 180);
    return () => { live = false; window.clearTimeout(timer); };
  }, [query, state, clientId, refresh]);
  async function loadMore() {
    if (!page?.siguiente || loadingMore) return;
    setLoadingMore(true);
    try {
      const result = await (await api(`/cuentas?${params(page.siguiente)}`)).json() as AccountPage;
      setPage(current => current ? { ...result, items: [...current.items, ...result.items] } : result);
    } catch (error) { setNotice(message(error)); }
    finally { setLoadingMore(false); }
  }
  async function changeState(item: Account) {
    if (changingId !== null) return;
    setChangingId(item.id);
    try {
      await api(`/cuentas/${item.id}/estado`, { method: 'POST', body: JSON.stringify({ estado_id: item.estado_id === 1 ? 0 : 1 }) });
      toast(item.estado_id === 1 ? 'Inactivada' : 'Activada', item.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo cambiar el estado', message(error), 'err'); }
    finally { setChangingId(null); }
  }
  async function restore(item: Account) {
    if (restoringId !== null) return;
    setRestoringId(item.id);
    try {
      await api(`/cuentas/${item.id}/restaurar`, { method: 'POST' });
      toast('Restaurada como Inactiva', item.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo restaurar', message(error), 'err'); }
    finally { setRestoringId(null); }
  }
  async function remove() {
    if (!deleteTarget || deleting) return;
    setDeleting(true); setDeleteError('');
    try {
      await api(`/cuentas/${deleteTarget.id}`, { method: 'DELETE' });
      toast('Eliminada lógicamente', deleteTarget.nombre);
      setDeleteTarget(null); setRefresh(value => value + 1);
    } catch (error) { setDeleteError(message(error)); toast('No se pudo eliminar', message(error), 'err'); }
    finally { setDeleting(false); }
  }
  const clients = canReadClients ? clientOptions : Array.from(new Map(page?.items.map(item => [item.cliente_id, { id: item.cliente_id, nombre: item.cliente_nombre }]) ?? []).values());
  return <>
    <div className="page-heading"><div><h1>Cuentas</h1><p>{DESCRIPTION}</p></div>{canCreate && <Link className="button primary heading-action" to="/cuentas/nueva"><Icon name="plus" size={16} />Nueva cuenta</Link>}</div>
    <section className="panel entity-list-panel"><div className="module-toolbar entity-toolbar" aria-label="Filtros de Cuentas"><label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar cuentas…" aria-label="Buscar cuentas" /></label><select aria-label="Cliente" value={clientId} onChange={event => setClientId(event.target.value)}><option value="">Cliente: todos</option>{clients.map(row => <option value={row.id} key={row.id}>{row.nombre}</option>)}</select><div className="seg status-segment" role="group" aria-label="Filtrar cuentas por estado">{STATES.map(([key, label]) => <button key={key} type="button" className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}</button>)}</div></div>
      {notice && <p className="control-notice error" role="alert">{notice}</p>}
      <div className="table-wrap"><table className="data-table client-table account-table"><thead><tr><th>Cuenta</th><th>Cliente</th><th>Estado</th><th>Actualizado</th><th>Acciones</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={5} className="empty-cell" role="status">Cargando cuentas…</td></tr> : page?.items.length ? page.items.map(item => <tr key={item.id} className={item.estado_id === -1 ? 'client-row-deleted' : 'client-row'} tabIndex={item.estado_id === -1 ? undefined : 0} aria-label={item.estado_id === -1 ? `Cuenta eliminada ${item.nombre}` : `Ver detalle de ${item.nombre}`}
          onClick={event => { if (item.estado_id !== -1 && (!(event.target instanceof Element) || !event.target.closest('a,button,[data-row-action]'))) navigate(`/cuentas/${item.id}`); }}
          onKeyDown={event => { if (item.estado_id !== -1 && event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); navigate(`/cuentas/${item.id}`); } }}>
          <td><strong>{item.nombre}</strong><small className="account-subtitle">Taxonomía: {TAXONOMIES.find(([code]) => code === item.taxonomia)?.[1] || '—'}</small></td><td>{item.cliente_nombre}</td><td><StateBadge state={item.estado_id} /></td><td>{new Date(item.actualizado_en).toLocaleDateString('es-CO')}</td>
          <td><div className="client-row-actions">{item.estado_id === -1 ? canDelete && <button className="button client-restore-action" type="button" title="Restaurar como inactiva" aria-label={`Restaurar ${item.nombre}`} disabled={restoringId === item.id} onClick={event => { event.stopPropagation(); void restore(item); }}><Icon name="undo" size={14} />Restaurar</button> : <>
            {canEdit && <><Link className="client-row-action" to={`/cuentas/${item.id}/editar`} title="Editar" aria-label={`Editar ${item.nombre}`} onClick={event => event.stopPropagation()}><Icon name="edit" size={16} /></Link><button className="client-row-action" type="button" title={item.estado_id === 1 ? 'Inactivar' : 'Activar'} aria-label={`${item.estado_id === 1 ? 'Inactivar' : 'Activar'} ${item.nombre}`} disabled={changingId === item.id} onClick={event => { event.stopPropagation(); void changeState(item); }}><Icon name="power" size={16} /></button></>}
            {canHistory && <Link className="client-row-action" to={`/cuentas/${item.id}?historial=1`} title="Ver historial de cambios" aria-label={`Ver historial de cambios de ${item.nombre}`} onClick={event => event.stopPropagation()}><Icon name="clock" size={16} /></Link>}
            {canDelete && <button className="client-row-action client-row-action-danger" type="button" title="Eliminar" aria-label={`Eliminar ${item.nombre}`} onClick={event => { event.stopPropagation(); setDeleteError(''); setDeleteTarget(item); }}><Icon name="trash" size={16} /></button>}
          </>}</div></td>
        </tr>) : <tr><td colSpan={5} className="empty-cell"><EmptyState title={state === 'eliminados' ? 'No hay registros eliminados' : query.trim() ? 'Sin resultados para los filtros' : 'Aún no hay cuentas'} detail={query.trim() ? 'Prueba con otro término de búsqueda.' : 'El contenido aparecerá cuando haya información disponible.'} /></td></tr>}
      </tbody></table></div>{page?.siguiente && <div className="form-actions"><button type="button" className="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? 'Cargando…' : 'Cargar más'}</button></div>}
    </section>
    {deleteTarget && <ConfirmDialog title="Eliminar cuenta" description={<><strong>{deleteTarget.nombre}</strong> pasará a estado Eliminado. ¿Desea Continuar?.</>} error={deleteError} busy={deleting} confirmLabel="Eliminar" busyLabel="Eliminando…" onConfirm={() => void remove()} onClose={() => setDeleteTarget(null)} />}
  </>;
}

export function AccountForm() {
  const { id } = useParams();
  const editId = id ? Number(id) : null;
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState('');
  const [clientId, setClientId] = useState('');
  const [clientName, setClientName] = useState('');
  const [clients, setClients] = useState<Cliente[]>([]);
  const [actor, setActor] = useState('');
  const [entity, setEntity] = useState('');
  const [taxonomy, setTaxonomy] = useState('gobierno');
  const [state, setState] = useState(1);
  const [clusters, setClusters] = useState('');
  const [themes, setThemes] = useState('');
  const [defaultClusters, setDefaultClusters] = useState<Prompt[]>([]);
  const [defaultThemes, setDefaultThemes] = useState<Prompt[]>([]);
  const [etag, setEtag] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let live = true;
    Promise.all([loadClients(), loadPrompts('cluster'), loadPrompts('temas'),
      editId ? api(`/cuentas/${editId}`).then(async response => ({ row: await response.json() as Account, etag: response.headers.get('ETag') || '' })) : Promise.resolve(null),
    ]).then(([clientRows, clusterRows, themeRows, loaded]) => {
      if (!live) return;
      setClients(clientRows); setDefaultClusters(clusterRows); setDefaultThemes(themeRows);
      if (loaded) {
        const item = loaded.row;
        setName(item.nombre); setClientId(String(item.cliente_id)); setClientName(item.cliente_nombre);
        setActor(item.actor_principal || ''); setEntity(item.entidad || ''); setTaxonomy(item.taxonomia || 'gobierno');
        setClusters(item.prompt_clusters); setThemes(item.prompt_temas); setState(item.estado_id); setEtag(loaded.etag);
      }
      setReady(true);
    }).catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [editId]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !ready) return;
    if (clusters.trim().length < 20 || themes.trim().length < 20) { setNotice('Cada prompt debe tener al menos 20 caracteres.'); return; }
    setBusy(true); setNotice('');
    try {
      const response = await api(editId ? `/cuentas/${editId}` : '/cuentas', {
        method: editId ? 'PATCH' : 'POST', headers: editId ? { 'If-Match': etag } : undefined,
        body: JSON.stringify({ cliente_id: Number(clientId), nombre: name, actor_principal: actor || null,
          entidad: entity || null, taxonomia: taxonomy, prompt_clusters: clusters, prompt_temas: themes, estado_id: state }),
      });
      const saved = await response.json() as Account;
      toast(editId ? 'Cuenta actualizada' : 'Cuenta creada', saved.nombre);
      navigate(`/cuentas/${saved.id}`);
    } catch (error) { setNotice(message(error)); toast('No se pudo guardar', message(error), 'err'); }
    finally { setBusy(false); }
  }
  return <>
    <div className="page-heading"><div><h1>{editId ? 'Editar cuenta' : 'Nueva cuenta'}</h1><p>{DESCRIPTION}</p></div></div>
    <form className="panel creation-form" onSubmit={submit}><div className="panel-heading"><h2>{editId ? 'Editar cuenta' : 'Nueva cuenta'}</h2></div><div className="creation-form-body"><div className="form-grid">
      <div className="field"><label htmlFor="account-name">Nombre de la cuenta *</label><input id="account-name" value={name} onChange={event => setName(event.target.value)} placeholder="Ej. Gob. Nuevo León · Nombre del gobernador" required /></div>
      <div className="field"><label htmlFor="account-client">Cliente asociado *</label><select id="account-client" value={clientId} onChange={event => setClientId(event.target.value)} required><option value="">Selecciona un cliente</option>{clients.map(row => <option key={row.id} value={row.id}>{row.nombre}</option>)}{clientId && !clients.some(row => String(row.id) === clientId) && <option value={clientId}>{clientName}</option>}</select></div>
      <div className="field"><label htmlFor="account-actor">Actor o término principal</label><input id="account-actor" value={actor} onChange={event => setActor(event.target.value)} placeholder="Ej. el gobernador Salazar" /><span className="help">Persona, institución o partido de referencia en el análisis.</span></div>
      <div className="field"><label htmlFor="account-entity">Entidad federativa</label><input id="account-entity" value={entity} onChange={event => setEntity(event.target.value)} /></div>
      <div className="field"><label htmlFor="account-taxonomy">Taxonomía base</label><select id="account-taxonomy" value={taxonomy} onChange={event => setTaxonomy(event.target.value)}>{TAXONOMIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
      <div className="field"><label htmlFor="account-state">Estado</label><select id="account-state" value={state} onChange={event => setState(Number(event.target.value))}><option value={1}>Activo</option><option value={0}>Inactivo</option></select></div>
      <div className="field span2"><div className="account-prompt-heading"><label htmlFor="account-clusters">Prompt de clusters *</label><select aria-label="Cargar prompt de clusters por defecto" defaultValue="" onChange={event => { const prompt = defaultClusters.find(row => String(row.id) === event.target.value); if (prompt) { setClusters(prompt.contenido); toast('Prompt cargado', `${prompt.nombre} v${prompt.version_actual}`); } event.target.value = ''; }}><option value="">Cargar desde prompts por defecto…</option>{defaultClusters.map(prompt => <option key={prompt.id} value={prompt.id}>{prompt.por_defecto ? '★ ' : ''}{prompt.nombre} (v{prompt.version_actual})</option>)}</select></div><textarea id="account-clusters" className="account-prompt-content" rows={7} value={clusters} onChange={event => setClusters(event.target.value)} required /><span className="help">Variables: {'{{cuenta}}'}, {'{{num_clusters}}'}, {'{{num_subclusters}}'}</span></div>
      <div className="field span2"><div className="account-prompt-heading"><label htmlFor="account-themes">Prompt de temas finales *</label><select aria-label="Cargar prompt de temas finales por defecto" defaultValue="" onChange={event => { const prompt = defaultThemes.find(row => String(row.id) === event.target.value); if (prompt) { setThemes(prompt.contenido); toast('Prompt cargado', `${prompt.nombre} v${prompt.version_actual}`); } event.target.value = ''; }}><option value="">Cargar desde prompts por defecto…</option>{defaultThemes.map(prompt => <option key={prompt.id} value={prompt.id}>{prompt.por_defecto ? '★ ' : ''}{prompt.nombre} (v{prompt.version_actual})</option>)}</select></div><textarea id="account-themes" className="account-prompt-content" rows={7} value={themes} onChange={event => setThemes(event.target.value)} required /><span className="help">Variables: {'{{cuenta}}'}, {'{{num_clusters}}'}, {'{{num_subclusters}}'}</span></div>
    </div>{notice && <p className="control-notice error" role="alert">{notice}</p>}</div><div className="form-actions creation-actions"><Link className="button" to={editId ? `/cuentas/${editId}` : '/cuentas'}><Icon name="arrow" size={15} />Cancelar</Link><button className="button primary" type="submit" disabled={!ready || busy}><Icon name="check" size={15} />{busy ? 'Guardando…' : 'Guardar'}</button></div></form>
  </>;
}

export function AccountDetail({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const autoHistory = searchParams.get('historial') === '1';
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));
  const [item, setItem] = useState<Account | null>(null);
  const [notice, setNotice] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<AuditEvent[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [historyBusy, setHistoryBusy] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setItem(null); setNotice(''); setHistory([]); setHistoryOpen(false);
    api(`/cuentas/${id}`).then(response => response.json()).then((value: Account) => { if (live) setItem(value); })
      .catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [id]);
  async function loadHistory(cursor?: string) {
    if (historyBusy) return;
    setHistoryOpen(true); setHistoryBusy(true); setHistoryError('');
    const params = new URLSearchParams({ limite: '25' });
    if (cursor) params.set('cursor', cursor);
    try {
      const response = await api(`/cuentas/${id}/historial?${params}`);
      const events = await response.json() as AuditEvent[];
      setHistory(previous => cursor ? [...previous, ...events] : events);
      setNextCursor(response.headers.get('X-Next-Cursor'));
    } catch (error) { setHistoryError(message(error)); }
    finally { setHistoryBusy(false); }
  }
  useEffect(() => { if (autoHistory && canHistory) void loadHistory(); }, [id, autoHistory, canHistory]);
  return <>
    <div className="page-heading"><div><h1>Detalle de cuenta</h1><p>{DESCRIPTION}</p></div>{item && item.estado_id !== -1 && yo?.permisos.cuentas?.includes('editar') && <Link className="button primary heading-action" to={`/cuentas/${item.id}/editar`}><Icon name="edit" size={16} />Editar</Link>}</div>
    {notice && <p className="control-notice error" role="alert">{notice}</p>}
    {item && <section className="panel creation-form"><div className="panel-heading"><h2>{item.nombre}</h2></div><div className="creation-form-body"><dl className="client-access-kv"><dt>Cliente</dt><dd>{item.cliente_nombre}</dd><dt>Actor o término principal</dt><dd>{item.actor_principal || '—'}</dd><dt>Entidad federativa</dt><dd>{item.entidad || '—'}</dd><dt>Taxonomía base</dt><dd>{TAXONOMIES.find(([code]) => code === item.taxonomia)?.[1] || '—'}</dd><dt>Estado</dt><dd><StateBadge state={item.estado_id} /></dd><dt>Prompt de clusters</dt><dd className="account-prompt-detail">{item.prompt_clusters}</dd><dt>Prompt de temas finales</dt><dd className="account-prompt-detail">{item.prompt_temas}</dd></dl><AuditMetadata record={item} canViewUsers={Boolean(yo?.permisos.usuarios?.includes('ver'))} /></div><div className="form-actions client-detail-actions"><Link className="button" to="/cuentas">Volver a Cuentas</Link>{canHistory && <button className="button" type="button" onClick={() => historyOpen ? setHistoryOpen(false) : void loadHistory()}><Icon name="clock" size={15} />{historyOpen ? 'Ocultar historial' : 'Ver historial de cambios'}</button>}</div></section>}
    {item && historyOpen && <section className="panel role-history" aria-label="Historial de cambios"><div className="panel-heading"><h2>Historial de cambios</h2></div>{historyError && <p className="control-notice error" role="alert">{historyError}</p>}{historyBusy && !history.length ? <p className="role-history-empty" role="status">Cargando historial…</p> : !history.length && !historyError ? <p className="role-history-empty">No hay cambios registrados para esta cuenta.</p> : <ol>{history.map(event => <li key={`${event.fecha}-${event.id}`}><strong>{event.accion}</strong><span>{new Date(event.fecha).toLocaleString('es-CO')} · Usuario {event.usuario_id ?? 'sistema'}</span><details><summary>Ver datos registrados</summary><pre>Antes: {JSON.stringify(event.antes, null, 2) || '—'}{'\n'}Después: {JSON.stringify(event.despues, null, 2) || '—'}</pre></details></li>)}</ol>}{nextCursor && <button className="button" type="button" disabled={historyBusy} onClick={() => void loadHistory(nextCursor)}>Ver más</button>}</section>}
  </>;
}
