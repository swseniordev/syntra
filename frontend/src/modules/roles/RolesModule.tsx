import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Icon } from '../../shared/Icon';
import { EmptyState } from '../../shared/EmptyState';
import { AuditMetadata } from '../../shared/AuditMetadata';
import { StateBadge } from '../../shared/StateBadge';
import { ConfirmDialog } from '../../shared/ConfirmDialog';
import { api, ApiError } from '../../shared/api';
import type { Yo } from '../../shared/api';
import { useToast } from '../../shared/Toast';

type Role = {
  id: number; nombre: string; descripcion: string | null; ver_todas: boolean;
  permisos: Record<string, string[]>; estado_id: number; creado_en: string; creado_por: number | null; actualizado_en: string; actualizado_por: number | null;
};
type CatalogPair = { modulo: string; modulo_nombre: string; accion: string; accion_nombre: string };
type RolePage = { items: Role[]; siguiente: string | null; total_aprox: number };
type AuditEvent = { id: number; fecha: string; usuario_id: number | null; accion: string; antes: Record<string, unknown> | null; despues: Record<string, unknown> | null };
const STATES = [['vigentes', 'Vigentes'], ['activos', 'Activos'], ['inactivos', 'Inactivos'], ['eliminados', 'Eliminados']] as const;
const ACTIONS = ['ver', 'crear', 'editar', 'eliminar', 'ejecutar', 'exportar'] as const;
const ERROR_FALLBACK = 'No se pudo completar la operación.';

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'El servidor no pudo completar la operación. Inténtalo de nuevo.';
    if (error.status === 401) return 'La sesión venció. Ingresa de nuevo.';
    if (error.status === 403) return 'No tienes permiso para realizar esta acción.';
    return error.message;
  }
  return ERROR_FALLBACK;
}

function countPermissions(role: Role): number {
  return Object.values(role.permisos).reduce((total, actions) => total + actions.length, 0);
}

export function RolesList({ yo }: { yo: Yo | null }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [state, setState] = useState<(typeof STATES)[number][0]>('vigentes');
  const [page, setPage] = useState<RolePage | null>(null);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<Role | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const toast = useToast();
  useEffect(() => {
    let live = true;
    setLoading(true);
    const params = new URLSearchParams({ q: query.trim(), estado: state, limite: '25' });
    api(`/roles?${params}`).then(response => response.json()).then((data: RolePage) => {
      if (live) { setPage(data); setNotice(''); }
    }).catch(error => { if (live) setNotice(message(error)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [query, state, refresh]);

  async function changeState(role: Role) {
    try {
      const next = role.estado_id === 1 ? 0 : 1;
      await api(`/roles/${role.id}/estado`, { method: 'POST', body: JSON.stringify({ estado_id: next }) });
      toast('Estado actualizado', role.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo cambiar el estado', message(error), 'err'); }
  }

  async function remove() {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await api(`/roles/${deleteTarget.id}`, { method: 'DELETE' });
      toast('Rol eliminado', deleteTarget.nombre);
      setDeleteTarget(null);
      setRefresh(value => value + 1);
    } catch (error) { setDeleteError(message(error)); toast('No se pudo eliminar', message(error), 'err'); }
    finally { setDeleting(false); }
  }

  async function restore(role: Role) {
    try {
      await api(`/roles/${role.id}/restaurar`, { method: 'POST' });
      toast('Rol restaurado', role.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo restaurar', message(error), 'err'); }
  }

  async function loadMore() {
    if (!page?.siguiente || loadingMore) return;
    setLoadingMore(true);
    const params = new URLSearchParams({ q: query.trim(), estado: state, limite: '25', cursor: page.siguiente });
    try {
      const more = await (await api(`/roles?${params}`)).json() as RolePage;
      setPage(current => current ? { ...more, items: [...current.items, ...more.items] } : more);
    } catch (error) { setNotice(message(error)); }
    finally { setLoadingMore(false); }
  }

  const mayCreate = Boolean(yo?.permisos.roles?.includes('crear'));
  const mayEdit = Boolean(yo?.permisos.roles?.includes('editar'));
  const mayDelete = Boolean(yo?.permisos.roles?.includes('eliminar'));
  const mayHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));
  return <>
    <div className="page-heading"><div><h1>Roles y accesos</h1><p>Matriz de permisos por módulo y acción. Los roles con acceso global ven todas las cuentas; los demás, solo las de sus grupos.</p></div>{mayCreate && <Link className="button primary heading-action" to="/roles/nuevo"><Icon name="plus" size={16} />Nuevo rol</Link>}</div>
    <section className="panel entity-list-panel">
      <div className="module-toolbar entity-toolbar" aria-label="Filtros de roles"><label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar roles…" aria-label="Buscar roles" /></label><div className="seg status-segment" role="group" aria-label="Filtrar roles por estado">{STATES.map(([key, label]) => <button type="button" key={key} className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}</button>)}</div></div>
      {notice && <p className="control-notice error" role="alert">{notice}</p>}
      <div className="table-wrap"><table className="data-table client-table roles-table"><thead><tr><th>Rol</th><th>Alcance</th><th>Permisos</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={5} className="empty-cell" role="status">Cargando roles…</td></tr> : page?.items.length ? page.items.map(role =>
          <tr key={role.id} className={role.estado_id === -1 ? 'client-row-deleted' : 'client-row'} tabIndex={role.estado_id === -1 ? undefined : 0} aria-label={role.estado_id === -1 ? `Rol eliminado ${role.nombre}` : `Ver detalle de ${role.nombre}`}
            onClick={event => { if (role.estado_id !== -1 && (!(event.target instanceof Element) || !event.target.closest('a,button,[data-row-action]'))) navigate(`/roles/${role.id}`); }}
            onKeyDown={event => { if (role.estado_id !== -1 && event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); navigate(`/roles/${role.id}`); } }}>
            <td><strong>{role.nombre}</strong><br /><small>{role.descripcion || '—'}</small></td>
            <td><span className={`badge ${role.ver_todas ? 'grad' : 'info'}`}>{role.ver_todas ? 'Todas las cuentas' : 'Por grupos'}</span></td>
            <td>{countPermissions(role)} / 67</td><td><StateBadge state={role.estado_id} /></td>
            <td><div className="client-row-actions">
              {role.estado_id === -1 ? mayDelete && <button className="button client-restore-action" type="button" title="Restaurar como inactivo" aria-label={`Restaurar ${role.nombre}`} onClick={event => { event.stopPropagation(); void restore(role); }}><Icon name="undo" size={14} />Restaurar</button> : <>
                {mayEdit && <><Link className="client-row-action" to={`/roles/${role.id}/editar`} title="Editar" aria-label={`Editar ${role.nombre}`} onClick={event => event.stopPropagation()}><Icon name="edit" size={16} /></Link><button className="client-row-action" type="button" title={role.estado_id === 1 ? 'Inactivar' : 'Activar'} aria-label={`${role.estado_id === 1 ? 'Inactivar' : 'Activar'} ${role.nombre}`} onClick={event => { event.stopPropagation(); void changeState(role); }}><Icon name="power" size={16} /></button></>}
                {mayHistory && <Link className="client-row-action" to={`/roles/${role.id}?historial=1`} title="Ver historial de cambios" aria-label={`Ver historial de cambios de ${role.nombre}`} onClick={event => event.stopPropagation()}><Icon name="clock" size={16} /></Link>}
                {mayDelete && <button className="client-row-action client-row-action-danger" type="button" title="Eliminar" aria-label={`Eliminar ${role.nombre}`} onClick={event => { event.stopPropagation(); setDeleteTarget(role); setDeleteError(''); }}><Icon name="trash" size={16} /></button>}
              </>}
            </div></td>
          </tr>) : <tr><td colSpan={5} className="empty-cell"><EmptyState title={state === 'eliminados' ? 'No hay registros eliminados' : query.trim() ? 'Sin resultados para los filtros' : 'Aún no hay roles'} detail={query.trim() ? 'Prueba con otro término de búsqueda.' : 'El contenido aparecerá cuando haya información disponible.'} /></td></tr>}
      </tbody></table></div>
      {page?.siguiente && <div className="form-actions"><button className="button" type="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? 'Cargando…' : 'Cargar más'}</button></div>}
    </section>
    {deleteTarget && <ConfirmDialog title="Eliminar rol" description={<><strong>{deleteTarget.nombre}</strong> pasará a estado Eliminado. ¿Desea Continuar?.</>} error={deleteError} busy={deleting} confirmLabel="Eliminar" busyLabel="Eliminando…" onConfirm={() => void remove()} onClose={() => setDeleteTarget(null)} />}
  </>;
}

export function RoleForm({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const editId = id ? Number(id) : null;
  const navigate = useNavigate();
  const toast = useToast();
  const [catalog, setCatalog] = useState<CatalogPair[]>([]);
  const [role, setRole] = useState<Role | null>(null);
  const [etag, setEtag] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [state, setState] = useState(1);
  const [allAccounts, setAllAccounts] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let live = true;
    Promise.all([api('/roles/catalogo-permisos'), editId ? api(`/roles/${editId}`) : Promise.resolve(null)])
      .then(async ([catalogResponse, roleResponse]) => {
        const pairs = (await catalogResponse.json()).items as CatalogPair[];
        const loaded = roleResponse ? await roleResponse.json() as Role : null;
        if (!live) return;
        setCatalog(pairs);
        if (loaded && roleResponse) {
          setRole(loaded); setEtag(roleResponse.headers.get('ETag') || '');
          setName(loaded.nombre); setDescription(loaded.descripcion || '');
          setState(loaded.estado_id); setAllAccounts(loaded.ver_todas);
          setSelected(new Set(Object.entries(loaded.permisos).flatMap(([module, actions]) => actions.map(action => `${module}:${action}`))));
        }
        setReady(true);
      }).catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [editId]);

  function toggle(pair: CatalogPair) {
    const key = `${pair.modulo}:${pair.accion}`;
    setSelected(previous => { const next = new Set(previous); if (next.has(key)) next.delete(key); else next.add(key); return next; });
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim() || busy || !ready) { setNotice('El nombre del rol es obligatorio.'); return; }
    const permissions: Record<string, string[]> = {};
    for (const pair of catalog) if (selected.has(`${pair.modulo}:${pair.accion}`)) (permissions[pair.modulo] ??= []).push(pair.accion);
    const body = { nombre: name.trim(), descripcion: description.trim() || null, ver_todas: allAccounts, permisos: permissions, ...(!editId ? { estado_id: state } : {}) };
    setBusy(true);
    try {
      const response = await api(editId ? `/roles/${editId}` : '/roles', { method: editId ? 'PATCH' : 'POST', headers: editId ? { 'If-Match': etag } : undefined, body: JSON.stringify(body) });
      const saved = await response.json() as Role;
      toast(editId ? 'Rol actualizado' : 'Rol creado', saved.nombre);
      navigate(`/roles/${saved.id}`);
    } catch (error) { setNotice(message(error)); }
    finally { setBusy(false); }
  }

  const byModule = [...new Set(catalog.map(pair => pair.modulo))];
  const labels = Object.fromEntries(catalog.map(pair => [pair.modulo, pair.modulo_nombre]));
  const pairMap = new Map(catalog.map(pair => [`${pair.modulo}:${pair.accion}`, pair]));
  return <>
    <div className="page-heading"><div><h1>{editId ? 'Editar rol' : 'Nuevo rol'}</h1><p>Matriz de permisos por módulo y acción.</p></div></div>
    <form className="panel creation-form" onSubmit={submit}>
      <div className="panel-heading"><h2>{editId ? role?.nombre || 'Editar rol' : 'Nuevo rol'}</h2></div>
      <div className="creation-form-body"><div className="form-grid"><div className="field"><label htmlFor="role-name">Nombre del rol *</label><input id="role-name" value={name} onChange={event => setName(event.target.value)} required /></div>{!editId && <div className="field"><label htmlFor="role-state">Estado</label><select id="role-state" value={state} onChange={event => setState(Number(event.target.value))}><option value={1}>Activo</option><option value={0}>Inactivo</option></select></div>}<div className="field span2"><label htmlFor="role-description">Descripción</label><textarea id="role-description" rows={3} value={description} onChange={event => setDescription(event.target.value)} /></div><label className="create-check span2"><input type="checkbox" checked={allAccounts} disabled={!yo?.rol.ver_todas} onChange={event => setAllAccounts(event.target.checked)} /><span>Acceso a todas las cuentas — ignora la restricción por grupos de usuarios</span></label></div>
        <section className="field span2 permission-section"><label>Permisos por módulo</label><p className="field-help">Solo se muestran los 67 pares aprobados. Puedes asignar únicamente los permisos que posees.</p><div className="table-wrap permission-wrap"><table className="permission-table"><thead><tr><th>Módulo</th>{ACTIONS.map(action => <th key={action}>{catalog.find(pair => pair.accion === action)?.accion_nombre || action}</th>)}</tr></thead><tbody>{byModule.map(module => <tr key={module}><th scope="row">{labels[module]}</th>{ACTIONS.map(action => { const pair = pairMap.get(`${module}:${action}`); return <td key={action}>{pair ? <input type="checkbox" aria-label={`${pair.modulo_nombre}: ${pair.accion_nombre}`} checked={selected.has(`${module}:${action}`)} disabled={!yo?.permisos[module]?.includes(action)} onChange={() => toggle(pair)} /> : <span aria-label="No asignable">—</span>}</td>; })}</tr>)}</tbody></table></div></section>
        {notice && <p className="control-notice error" role="alert">{notice}</p>}
      </div>
      <div className="form-actions creation-actions"><Link className="button" to={editId ? `/roles/${editId}` : '/roles'}><Icon name="arrow" size={15} />Cancelar</Link><button type="submit" className="button primary" disabled={!ready || busy}><Icon name="check" size={15} />{busy ? 'Guardando…' : 'Guardar'}</button></div>
    </form>
  </>;
}

export function RoleDetail({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const autoHistory = searchParams.get('historial') === '1';
  const [role, setRole] = useState<Role | null>(null);
  const [notice, setNotice] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<AuditEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState('');
  useEffect(() => {
    let live = true;
    setHistoryOpen(false);
    setHistory([]);
    setNextCursor(null);
    api(`/roles/${id}`).then(response => response.json()).then((data: Role) => { if (live) setRole(data); })
      .catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [id]);
  async function loadHistory(cursor?: string) {
    if (historyBusy) return;
    setHistoryOpen(true);
    setHistoryBusy(true);
    setHistoryError('');
    try {
      const params = new URLSearchParams({ limite: '25' });
      if (cursor) params.set('cursor', cursor);
      const response = await api(`/roles/${id}/historial?${params}`);
      const events = await response.json() as AuditEvent[];
      setHistory(previous => cursor ? [...previous, ...events] : events);
      setNextCursor(response.headers.get('X-Next-Cursor'));
    } catch (error) { setHistoryError(message(error)); }
    finally { setHistoryBusy(false); }
  }
  useEffect(() => {
    if (autoHistory && yo?.permisos.auditoria?.includes('ver')) void loadHistory();
  }, [id, autoHistory, yo?.permisos.auditoria]);
  return <>
    <div className="page-heading"><div><h1>Detalle de rol</h1><p>Permisos y alcance del rol.</p></div>{role && yo?.permisos.roles?.includes('editar') && role.estado_id !== -1 && <Link className="button primary heading-action" to={`/roles/${role.id}/editar`}><Icon name="edit" size={16} />Editar</Link>}</div>
    {notice && <p className="control-notice error" role="alert">{notice}</p>}
    {role && <section className="panel creation-form"><div className="panel-heading"><h2>{role.nombre}</h2></div><div className="creation-form-body"><dl className="client-access-kv"><dt>Descripción</dt><dd>{role.descripcion || '—'}</dd><dt>Alcance</dt><dd>{role.ver_todas ? 'Todas las cuentas' : 'Por grupos'}</dd><dt>Estado</dt><dd><StateBadge state={role.estado_id} /></dd><dt>Permisos</dt><dd>{Object.entries(role.permisos).map(([module, actions]) => <p key={module}><strong>{module}:</strong> {actions.join(', ')}</p>)}</dd></dl><AuditMetadata record={role} canViewUsers={Boolean(yo?.permisos.usuarios?.includes('ver'))} /></div><div className="form-actions client-detail-actions"><Link className="button" to="/roles">Volver a Roles</Link>{yo?.permisos.auditoria?.includes('ver') && <button className="button" type="button" onClick={() => historyOpen ? setHistoryOpen(false) : loadHistory()}><Icon name="clock" size={15} />{historyOpen ? 'Ocultar historial' : 'Ver historial de cambios'}</button>}</div></section>}
    {role && historyOpen && <section className="panel role-history" aria-label="Historial de cambios"><div className="panel-heading"><h2>Historial de cambios</h2></div>{historyError && <p className="control-notice error" role="alert">{historyError}</p>}{historyBusy && !history.length ? <p className="role-history-empty" role="status">Cargando historial…</p> : !history.length && !historyError ? <p className="role-history-empty">No hay cambios registrados para este rol.</p> : <ol>{history.map(event => <li key={`${event.fecha}-${event.id}`}><strong>{event.accion}</strong><span>{new Date(event.fecha).toLocaleString('es-CO')} · Usuario {event.usuario_id ?? 'sistema'}</span><details><summary>Ver datos registrados</summary><pre>Antes: {JSON.stringify(event.antes, null, 2) || '—'}{'\n'}Después: {JSON.stringify(event.despues, null, 2) || '—'}</pre></details></li>)}</ol>}{nextCursor && <button type="button" className="button" disabled={historyBusy} onClick={() => loadHistory(nextCursor)}>Ver más</button>}</section>}
  </>;
}
