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

type User = { id: number; nombre: string; email: string; telefono: string | null; rol_id: number;
  grupo_ids: number[]; ultimo_acceso: string | null; estado_id: number; creado_en: string; creado_por: number | null; actualizado_en: string; actualizado_por: number | null };
type Role = { id: number; nombre: string; ver_todas: boolean; estado_id: number };
type Group = { id: number; nombre: string; cuenta_ids: number[]; estado_id: number };
type Page<T> = { items: T[]; siguiente: string | null; total_aprox: number };
type AuditEvent = { id: number; fecha: string; usuario_id: number | null; accion: string;
  antes: Record<string, unknown> | null; despues: Record<string, unknown> | null };
const STATES = [['vigentes', 'Vigentes'], ['activos', 'Activos'], ['inactivos', 'Inactivos'], ['eliminados', 'Eliminados']] as const;
const DESCRIPTION = 'Personas con acceso a la plataforma. El rol define qué pueden hacer; los grupos definen qué cuentas pueden ver.';

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'El servidor no pudo completar la operación. Inténtalo de nuevo.';
    if (error.status === 401) return 'La sesión venció. Ingresa de nuevo.';
    if (error.status === 403) return 'No tienes permiso para realizar esta acción.';
    return error.message;
  }
  return 'No se pudo completar la operación.';
}

async function allRows<T>(path: string, state = 'vigentes'): Promise<T[]> {
  const rows: T[] = [];
  let cursor: string | null = null;
  do {
    const params = new URLSearchParams({ estado: state, limite: '200' });
    if (cursor) params.set('cursor', cursor);
    const page = await (await api(`${path}?${params}`)).json() as Page<T>;
    rows.push(...page.items);
    cursor = page.siguiente;
  } while (cursor);
  return rows;
}

export function UsersList({ yo }: { yo: Yo | null }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [state, setState] = useState<(typeof STATES)[number][0]>('vigentes');
  const [roleFilter, setRoleFilter] = useState('');
  const [roles, setRoles] = useState<Role[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [page, setPage] = useState<Page<User> | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<User | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [busyId, setBusyId] = useState<number | null>(null);
  const canCreate = Boolean(yo?.permisos.usuarios?.includes('crear'));
  const canEdit = Boolean(yo?.permisos.usuarios?.includes('editar'));
  const canDelete = Boolean(yo?.permisos.usuarios?.includes('eliminar'));
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));

  useEffect(() => {
    let live = true;
    Promise.all([yo?.permisos.roles?.includes('ver') ? allRows<Role>('/roles') : Promise.resolve([] as Role[]),
      yo?.permisos.grupos?.includes('ver') ? allRows<Group>('/grupos') : Promise.resolve([] as Group[])])
      .then(([roleRows, groupRows]) => { if (live) { setRoles(roleRows); setGroups(groupRows); } })
      .catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [yo]);

  function params(cursor?: string) {
    const result = new URLSearchParams({ estado: state, limite: '25' });
    if (query.trim()) result.set('q', query.trim());
    if (roleFilter) result.set('rol_id', roleFilter);
    if (cursor) result.set('cursor', cursor);
    return result;
  }
  useEffect(() => {
    let live = true;
    setLoading(true); setPage(null);
    const timer = window.setTimeout(() => {
      api(`/usuarios?${params()}`).then(response => response.json() as Promise<Page<User>>)
        .then(data => { if (live) { setPage(data); setNotice(''); } })
        .catch(error => { if (live) setNotice(message(error)); })
        .finally(() => { if (live) setLoading(false); });
    }, 180);
    return () => { live = false; window.clearTimeout(timer); };
  }, [query, state, roleFilter, refresh]);

  async function loadMore() {
    if (!page?.siguiente || loadingMore) return;
    setLoadingMore(true);
    try {
      const data = await (await api(`/usuarios?${params(page.siguiente)}`)).json() as Page<User>;
      setPage(current => current ? { ...data, items: [...current.items, ...data.items] } : data);
    } catch (error) { setNotice(message(error)); }
    finally { setLoadingMore(false); }
  }
  async function changeState(user: User) {
    if (busyId !== null) return;
    setBusyId(user.id);
    try {
      await api(`/usuarios/${user.id}/estado`, { method: 'POST', body: JSON.stringify({ estado_id: user.estado_id === 1 ? 0 : 1 }) });
      toast(user.estado_id === 1 ? 'Inactivado' : 'Activado', user.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo cambiar el estado', message(error), 'err'); }
    finally { setBusyId(null); }
  }
  async function restore(user: User) {
    if (busyId !== null) return;
    setBusyId(user.id);
    try {
      await api(`/usuarios/${user.id}/restaurar`, { method: 'POST' });
      toast('Restaurado como Inactivo', user.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo restaurar', message(error), 'err'); }
    finally { setBusyId(null); }
  }
  async function remove() {
    if (!deleteTarget || busyId !== null) return;
    setBusyId(deleteTarget.id); setDeleteError('');
    try {
      await api(`/usuarios/${deleteTarget.id}`, { method: 'DELETE' });
      toast('Eliminado lógicamente', deleteTarget.nombre);
      setDeleteTarget(null); setRefresh(value => value + 1);
    } catch (error) { setDeleteError(message(error)); toast('No se pudo eliminar', message(error), 'err'); }
    finally { setBusyId(null); }
  }
  const roleName = (id: number) => roles.find(row => row.id === id)?.nombre || `Rol ${id}`;
  const groupNames = (user: User) => groups.filter(group => user.grupo_ids.includes(group.id)).map(group => group.nombre);
  const accountCount = (user: User) => new Set(groups.filter(group => group.estado_id === 1 && user.grupo_ids.includes(group.id)).flatMap(group => group.cuenta_ids)).size;

  return <>
    <div className="page-heading"><div><h1>Usuarios</h1><p>{DESCRIPTION}</p></div>{canCreate && <Link className="button primary heading-action" to="/usuarios/nuevo"><Icon name="plus" size={16} />Nuevo usuario</Link>}</div>
    <section className="panel entity-list-panel"><div className="module-toolbar entity-toolbar" aria-label="Filtros de Usuarios"><label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar usuarios…" aria-label="Buscar usuarios" /></label><select aria-label="Filtrar por rol" value={roleFilter} onChange={event => setRoleFilter(event.target.value)}><option value="">Rol: todos</option>{roles.map(role => <option key={role.id} value={role.id}>{role.nombre}</option>)}</select><div className="seg status-segment" role="group" aria-label="Filtrar usuarios por estado">{STATES.map(([key, label]) => <button key={key} type="button" className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}</button>)}</div></div>
      {notice && <p className="control-notice error" role="alert">{notice}</p>}
      <div className="table-wrap"><table className="data-table client-table users-table"><thead><tr><th>Usuario</th><th>Rol</th><th>Grupos</th><th>Cuentas visibles</th><th>Último acceso</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={7} className="empty-cell" role="status">Cargando usuarios…</td></tr> : page?.items.length ? page.items.map(user => <tr key={user.id} className={user.estado_id === -1 ? 'client-row-deleted' : 'client-row'} tabIndex={user.estado_id === -1 ? undefined : 0} aria-label={user.estado_id === -1 ? `Usuario eliminado ${user.nombre}` : `Ver detalle de ${user.nombre}`}
          onClick={event => { if (user.estado_id !== -1 && (!(event.target instanceof Element) || !event.target.closest('a,button,[data-row-action]'))) navigate(`/usuarios/${user.id}`); }}
          onKeyDown={event => { if (user.estado_id !== -1 && event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); navigate(`/usuarios/${user.id}`); } }}>
          <td><div className="cell-main"><span className="avatar small"><Icon name="user" size={15} /></span><span><strong>{user.nombre}</strong><small>{user.email}</small></span></div></td>
          <td><span className="badge outline"><Icon name="shield" size={12} />{roleName(user.rol_id)}</span></td>
          <td>{groupNames(user).length ? groupNames(user).map(name => <span className="badge info" key={name}>{name}</span>) : <span className="muted">—</span>}</td>
          <td>{roles.find(role => role.id === user.rol_id)?.ver_todas ? <span className="badge grad">Todas</span> : <b>{accountCount(user)}</b>}</td>
          <td>{user.ultimo_acceso ? new Date(user.ultimo_acceso).toLocaleString('es-CO') : '—'}</td><td><StateBadge state={user.estado_id} /></td>
          <td><div className="client-row-actions">{user.estado_id === -1 ? canDelete && <button className="button client-restore-action" type="button" title="Restaurar como inactivo" aria-label={`Restaurar ${user.nombre}`} disabled={busyId === user.id} onClick={event => { event.stopPropagation(); void restore(user); }}><Icon name="undo" size={14} />Restaurar</button> : <>
            {canEdit && <><Link className="client-row-action" to={`/usuarios/${user.id}/editar`} title="Editar" aria-label={`Editar ${user.nombre}`} onClick={event => event.stopPropagation()}><Icon name="edit" size={16} /></Link><button className="client-row-action" type="button" title={user.estado_id === 1 ? 'Inactivar' : 'Activar'} aria-label={`${user.estado_id === 1 ? 'Inactivar' : 'Activar'} ${user.nombre}`} disabled={busyId === user.id || user.id === yo?.usuario.id} onClick={event => { event.stopPropagation(); void changeState(user); }}><Icon name="power" size={16} /></button></>}
            {canHistory && <Link className="client-row-action" to={`/usuarios/${user.id}?historial=1`} title="Ver historial de cambios" aria-label={`Ver historial de cambios de ${user.nombre}`} onClick={event => event.stopPropagation()}><Icon name="clock" size={16} /></Link>}
            {canDelete && <button className="client-row-action client-row-action-danger" type="button" title="Eliminar" aria-label={`Eliminar ${user.nombre}`} disabled={user.id === yo?.usuario.id} onClick={event => { event.stopPropagation(); setDeleteError(''); setDeleteTarget(user); }}><Icon name="trash" size={16} /></button>}
          </>}</div></td>
        </tr>) : <tr><td colSpan={7} className="empty-cell"><EmptyState title={state === 'eliminados' ? 'No hay registros eliminados' : query.trim() ? 'Sin resultados para los filtros' : 'Aún no hay usuarios'} detail={query.trim() ? 'Prueba con otro término de búsqueda.' : 'El contenido aparecerá cuando haya información disponible.'} /></td></tr>}
      </tbody></table></div>{page?.siguiente && <div className="form-actions"><button className="button" type="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? 'Cargando…' : 'Cargar más'}</button></div>}
    </section>
    {deleteTarget && <ConfirmDialog title="Eliminar usuario" description={<><strong>{deleteTarget.nombre}</strong> pasará a estado Eliminado y se revocarán sus sesiones. ¿Desea continuar?</>} error={deleteError} busy={busyId === deleteTarget.id} confirmLabel="Eliminar" busyLabel="Eliminando…" onConfirm={() => void remove()} onClose={() => setDeleteTarget(null)} />}
  </>;
}

export function UserForm({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const editId = id ? Number(id) : null;
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [roleId, setRoleId] = useState('');
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [state, setState] = useState(1);
  const [roles, setRoles] = useState<Role[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [etag, setEtag] = useState('');
  const [notice, setNotice] = useState('');
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    Promise.all([allRows<Role>('/roles'), yo?.permisos.grupos?.includes('ver') ? allRows<Group>('/grupos') : Promise.resolve([] as Group[]),
      editId ? api(`/usuarios/${editId}`).then(async response => ({ row: await response.json() as User, etag: response.headers.get('ETag') || '' })) : Promise.resolve(null),
    ]).then(([roleRows, groupRows, loaded]) => {
      if (!live) return;
      setRoles(roleRows); setGroups(groupRows);
      if (loaded) { setName(loaded.row.nombre); setEmail(loaded.row.email); setPhone(loaded.row.telefono || '');
        setRoleId(String(loaded.row.rol_id)); setGroupIds(loaded.row.grupo_ids); setState(loaded.row.estado_id); setEtag(loaded.etag); }
      setReady(true);
    }).catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [editId, yo]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || busy) return;
    setBusy(true); setNotice('');
    try {
      const response = await api(editId ? `/usuarios/${editId}` : '/usuarios', {
        method: editId ? 'PATCH' : 'POST', headers: editId ? { 'If-Match': etag } : undefined,
        body: JSON.stringify({ nombre: name, email, telefono: phone || null, rol_id: Number(roleId),
          grupo_ids: groupIds, ...(editId ? { estado_id: state } : {}) }),
      });
      const saved = await response.json() as User;
      toast(editId ? 'Usuario actualizado' : 'Usuario creado', editId ? saved.nombre : 'Correo de acceso encolado; entrega pendiente.');
      navigate(`/usuarios/${saved.id}`);
    } catch (error) { setNotice(message(error)); toast('No se pudo guardar', message(error), 'err'); }
    finally { setBusy(false); }
  }
  return <>
    <div className="page-heading"><div><h1>{editId ? 'Editar usuario' : 'Nuevo usuario'}</h1><p>{DESCRIPTION}</p></div></div>
    <form className="panel creation-form user-form" onSubmit={submit}><div className="panel-heading"><h2>{editId ? 'Editar usuario' : 'Nuevo usuario'}</h2></div><div className="creation-form-body"><div className="form-grid">
      <div className="field"><label htmlFor="user-name">Nombre completo *</label><input id="user-name" value={name} onChange={event => setName(event.target.value)} required /></div>
      <div className="field"><label htmlFor="user-email">Correo corporativo *</label><input id="user-email" type="email" value={email} onChange={event => setEmail(event.target.value)} required /></div>
      <div className="field"><label htmlFor="user-phone">Teléfono</label><input id="user-phone" value={phone} onChange={event => setPhone(event.target.value)} placeholder="+57 300 000 0000" /></div>
      <div className="field"><label htmlFor="user-role">Rol *</label><select id="user-role" value={roleId} onChange={event => setRoleId(event.target.value)} required><option value="">Selecciona un rol</option>{roles.filter(role => role.estado_id === 1 || role.id === Number(roleId)).map(role => <option key={role.id} value={role.id}>{role.nombre}{role.ver_todas ? ' · todas las cuentas' : ' · por grupos'}</option>)}</select></div>
      <div className="field"><label htmlFor="user-state">Estado</label><select id="user-state" value={state} disabled={!editId || editId === yo?.usuario.id} onChange={event => setState(Number(event.target.value))}><option value={1}>Activo</option><option value={0}>Inactivo</option></select></div>
      <div className="field span2"><label>Grupos de usuarios</label><div className="chips">{groups.map(group => <label key={group.id} className={`chip${groupIds.includes(group.id) ? ' on' : ''}`}><input type="checkbox" checked={groupIds.includes(group.id)} onChange={event => setGroupIds(current => event.target.checked ? [...current, group.id].sort((a, b) => a - b) : current.filter(value => value !== group.id))} />{group.nombre} <span className="muted">· {group.cuenta_ids.length} cuentas</span></label>)}{!groups.length && <span className="muted">Sin grupos disponibles.</span>}</div><small className="user-group-help">Si el rol no tiene acceso global, el usuario solo verá las cuentas asociadas a sus grupos.</small></div>
    </div>{!editId && <div className="user-mail-notice" role="note"><Icon name="info" size={17} /><span>Al guardar se encolará una contraseña temporal para envío por correo. El usuario quedará activo; el envío es asíncrono y guardar no garantiza que el correo ya se haya entregado.</span></div>}
    {notice && <p className="control-notice error" role="alert">{notice}</p>}</div><div className="form-actions creation-actions"><Link className="button" to={editId ? `/usuarios/${editId}` : '/usuarios'}><Icon name="arrow" size={15} />Cancelar</Link><button className="button primary" type="submit" disabled={!ready || busy}><Icon name="check" size={15} />{busy ? 'Guardando…' : 'Guardar'}</button></div></form>
  </>;
}

export function UserDetail({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const autoHistory = searchParams.get('historial') === '1';
  const toast = useToast();
  const [user, setUser] = useState<User | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [notice, setNotice] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<AuditEvent[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [historyBusy, setHistoryBusy] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [resendConfirm, setResendConfirm] = useState(false);
  const [resendBusy, setResendBusy] = useState(false);
  const [resendError, setResendError] = useState('');
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));
  useEffect(() => {
    let live = true;
    setUser(null); setNotice(''); setHistory([]); setHistoryOpen(false);
    Promise.all([api(`/usuarios/${id}`).then(response => response.json() as Promise<User>),
      yo?.permisos.roles?.includes('ver') ? allRows<Role>('/roles') : Promise.resolve([] as Role[]),
      yo?.permisos.grupos?.includes('ver') ? allRows<Group>('/grupos') : Promise.resolve([] as Group[]),
    ]).then(([row, roleRows, groupRows]) => { if (live) { setUser(row); setRoles(roleRows); setGroups(groupRows); } })
      .catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [id, yo]);
  async function loadHistory(cursor?: string) {
    if (historyBusy) return;
    setHistoryOpen(true); setHistoryBusy(true); setHistoryError('');
    const params = new URLSearchParams({ limite: '25' });
    if (cursor) params.set('cursor', cursor);
    try {
      const response = await api(`/usuarios/${id}/historial?${params}`);
      const events = await response.json() as AuditEvent[];
      setHistory(previous => cursor ? [...previous, ...events] : events);
      setNextCursor(response.headers.get('X-Next-Cursor'));
    } catch (error) { setHistoryError(message(error)); }
    finally { setHistoryBusy(false); }
  }
  useEffect(() => { if (autoHistory && canHistory) void loadHistory(); }, [id, autoHistory, canHistory]);
  async function resend() {
    if (!user || resendBusy) return;
    setResendBusy(true); setResendError('');
    try {
      await api(`/usuarios/${user.id}/invitar`, { method: 'POST' });
      toast('Correo encolado', 'Se generará una contraseña nueva y se enviará al usuario. La entrega está pendiente.');
      setResendConfirm(false);
    } catch (error) { setResendError(message(error)); toast('No se pudo reenviar', message(error), 'err'); }
    finally { setResendBusy(false); }
  }
  const roleName = roles.find(role => role.id === user?.rol_id)?.nombre || `Rol ${user?.rol_id || '—'}`;
  const userGroups = groups.filter(group => user?.grupo_ids.includes(group.id));
  return <>
    <div className="page-heading"><div><h1>Detalle de usuario</h1><p>{DESCRIPTION}</p></div>{user && user.estado_id !== -1 && yo?.permisos.usuarios?.includes('editar') && <Link className="button primary heading-action" to={`/usuarios/${user.id}/editar`}><Icon name="edit" size={16} />Editar</Link>}</div>
    {notice && <p className="control-notice error" role="alert">{notice}</p>}
    {user && <section className="panel creation-form"><div className="panel-heading"><h2>{user.nombre}</h2></div><div className="creation-form-body"><dl className="client-access-kv"><dt>Correo corporativo</dt><dd>{user.email}</dd><dt>Teléfono</dt><dd>{user.telefono || '—'}</dd><dt>Rol</dt><dd><span className="badge outline"><Icon name="shield" size={12} />{roleName}</span></dd><dt>Grupos</dt><dd>{userGroups.length ? userGroups.map(group => <span className="badge info" key={group.id}>{group.nombre}</span>) : '—'}</dd><dt>Estado</dt><dd><StateBadge state={user.estado_id} /></dd><dt>Último acceso</dt><dd>{user.ultimo_acceso ? new Date(user.ultimo_acceso).toLocaleString('es-CO') : '—'}</dd></dl>
      {user.estado_id === 1 && yo?.permisos.usuarios?.includes('editar') && <div className="mt fieldset"><div className="fieldset-title"><Icon name="key" size={16} />Acceso</div><button className="button small" type="button" onClick={() => setResendConfirm(true)}><Icon name="mail" size={14} />Reenviar correo con nueva contraseña</button></div>}<AuditMetadata record={user} canViewUsers={Boolean(yo?.permisos.usuarios?.includes('ver'))} /></div><div className="form-actions client-detail-actions"><Link className="button" to="/usuarios">Volver a Usuarios</Link>{canHistory && <button className="button" type="button" onClick={() => historyOpen ? setHistoryOpen(false) : void loadHistory()}><Icon name="clock" size={15} />{historyOpen ? 'Ocultar historial' : 'Ver historial de cambios'}</button>}</div></section>}
    {user && historyOpen && <section className="panel role-history" aria-label="Historial de cambios"><div className="panel-heading"><h2>Historial de cambios</h2></div>{historyError && <p className="control-notice error" role="alert">{historyError}</p>}{historyBusy && !history.length ? <p className="role-history-empty" role="status">Cargando historial…</p> : !history.length && !historyError ? <p className="role-history-empty">No hay cambios registrados para este usuario.</p> : <ol>{history.map(event => <li key={`${event.fecha}-${event.id}`}><strong>{event.accion}</strong><span>{new Date(event.fecha).toLocaleString('es-CO')} · Usuario {event.usuario_id ?? 'sistema'}</span><details><summary>Ver datos registrados</summary><pre>Antes: {JSON.stringify(event.antes, null, 2) || '—'}{'\n'}Después: {JSON.stringify(event.despues, null, 2) || '—'}</pre></details></li>)}</ol>}{nextCursor && <button className="button" type="button" disabled={historyBusy} onClick={() => void loadHistory(nextCursor)}>Ver más</button>}</section>}
    {resendConfirm && user && <ConfirmDialog title="Reenviar correo de acceso" description={<>Se generará una contraseña nueva para <strong>{user.nombre}</strong> y se revocarán sus sesiones activas. La entrega del correo ocurrirá de forma asíncrona. ¿Desea continuar?</>} error={resendError} busy={resendBusy} confirmLabel="Reenviar" busyLabel="Encolando…" onConfirm={() => void resend()} onClose={() => setResendConfirm(false)} />}
  </>;
}
