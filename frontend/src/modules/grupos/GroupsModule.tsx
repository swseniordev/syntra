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

type Group = { id: number; nombre: string; descripcion: string | null; usuario_ids: number[]; cuenta_ids: number[];
  estado_id: number; creado_en: string; creado_por: number | null; actualizado_en: string; actualizado_por: number | null };
type User = { id: number; nombre: string; email: string; rol_id: number; estado_id: number };
type Account = { id: number; nombre: string; cliente_nombre: string; estado_id: number };
type Page<T> = { items: T[]; siguiente: string | null; total_aprox: number };
type AuditEvent = { id: number; fecha: string; usuario_id: number | null; accion: string;
  antes: Record<string, unknown> | null; despues: Record<string, unknown> | null };
const STATES = [['vigentes', 'Vigentes'], ['activos', 'Activos'], ['inactivos', 'Inactivos'], ['eliminados', 'Eliminados']] as const;
const DESCRIPTION = 'Asocia usuarios con cuentas. Un usuario sin rol global solo verá las cuentas de sus grupos activos.';

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'El servidor no pudo completar la operación. Inténtalo de nuevo.';
    if (error.status === 401) return 'La sesión venció. Ingresa de nuevo.';
    if (error.status === 403) return 'No tienes permiso para realizar esta acción.';
    return error.message;
  }
  return 'No se pudo completar la operación.';
}

async function allRows<T>(path: string): Promise<T[]> {
  const rows: T[] = [];
  let cursor: string | null = null;
  do {
    const params = new URLSearchParams({ estado: 'vigentes', limite: '200' });
    if (cursor) params.set('cursor', cursor);
    const page = await (await api(`${path}?${params}`)).json() as Page<T>;
    rows.push(...page.items);
    cursor = page.siguiente;
  } while (cursor);
  return rows;
}

export function GroupsList({ yo }: { yo: Yo | null }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [state, setState] = useState<(typeof STATES)[number][0]>('vigentes');
  const [page, setPage] = useState<Page<Group> | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [notice, setNotice] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<Group | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [changingId, setChangingId] = useState<number | null>(null);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const canCreate = Boolean(yo?.permisos.grupos?.includes('crear'));
  const canEdit = Boolean(yo?.permisos.grupos?.includes('editar'));
  const canDelete = Boolean(yo?.permisos.grupos?.includes('eliminar'));
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));

  useEffect(() => {
    let live = true;
    setLoading(true); setPage(null);
    const timer = window.setTimeout(async () => {
      const params = new URLSearchParams({ estado: state, limite: '25' });
      if (query.trim()) params.set('q', query.trim());
      try {
        const result = await (await api(`/grupos?${params}`)).json() as Page<Group>;
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
      const result = await (await api(`/grupos?${params}`)).json() as Page<Group>;
      setPage(current => current ? { ...result, items: [...current.items, ...result.items] } : result);
    } catch (error) { setNotice(message(error)); }
    finally { setLoadingMore(false); }
  }

  async function changeState(group: Group) {
    if (changingId !== null) return;
    setChangingId(group.id);
    try {
      await api(`/grupos/${group.id}/estado`, { method: 'POST', body: JSON.stringify({ estado_id: group.estado_id === 1 ? 0 : 1 }) });
      toast(group.estado_id === 1 ? 'Inactivado' : 'Activado', group.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo cambiar el estado', message(error), 'err'); }
    finally { setChangingId(null); }
  }

  async function restore(group: Group) {
    if (restoringId !== null) return;
    setRestoringId(group.id);
    try {
      await api(`/grupos/${group.id}/restaurar`, { method: 'POST' });
      toast('Restaurado como Inactivo', group.nombre);
      setRefresh(value => value + 1);
    } catch (error) { toast('No se pudo restaurar', message(error), 'err'); }
    finally { setRestoringId(null); }
  }

  async function remove() {
    if (!deleteTarget || deleting) return;
    setDeleting(true); setDeleteError('');
    try {
      await api(`/grupos/${deleteTarget.id}`, { method: 'DELETE' });
      toast('Eliminado lógicamente', deleteTarget.nombre);
      setDeleteTarget(null); setRefresh(value => value + 1);
    } catch (error) { setDeleteError(message(error)); toast('No se pudo eliminar', message(error), 'err'); }
    finally { setDeleting(false); }
  }

  return <>
    <div className="page-heading"><div><h1>Grupos de usuarios</h1><p>{DESCRIPTION}</p></div>{canCreate && <Link className="button primary heading-action" to="/grupos/nuevo"><Icon name="plus" size={16} />Nuevo grupo</Link>}</div>
    <section className="panel entity-list-panel"><div className="module-toolbar entity-toolbar" aria-label="Filtros de Grupos"><label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar grupos…" aria-label="Buscar grupos" /></label><div className="seg status-segment" role="group" aria-label="Filtrar grupos por estado">{STATES.map(([key, label]) => <button key={key} type="button" className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}</button>)}</div></div>
      {notice && <p className="control-notice error" role="alert">{notice}</p>}
      <div className="table-wrap"><table className="data-table client-table group-table"><thead><tr><th>Grupo</th><th>Usuarios</th><th>Cuentas asociadas</th><th>Estado</th><th>Actualizado</th><th>Acciones</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={6} className="empty-cell" role="status">Cargando grupos…</td></tr> : page?.items.length ? page.items.map(group => <tr key={group.id} className={group.estado_id === -1 ? 'client-row-deleted' : 'client-row'} tabIndex={group.estado_id === -1 ? undefined : 0} aria-label={group.estado_id === -1 ? `Grupo eliminado ${group.nombre}` : `Ver detalle de ${group.nombre}`}
          onClick={event => { if (group.estado_id !== -1 && (!(event.target instanceof Element) || !event.target.closest('a,button,[data-row-action]'))) navigate(`/grupos/${group.id}`); }}
          onKeyDown={event => { if (group.estado_id !== -1 && event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); navigate(`/grupos/${group.id}`); } }}>
          <td><div className="cell-main"><span className="avatar small"><Icon name="layers" size={15} /></span><span><strong>{group.nombre}</strong><small>{group.descripcion || 'Sin descripción'}</small></span></div></td>
          <td>{group.usuario_ids.length}</td><td>{group.cuenta_ids.length}</td><td><StateBadge state={group.estado_id} /></td><td>{new Date(group.actualizado_en).toLocaleDateString('es-CO')}</td>
          <td><div className="client-row-actions">{group.estado_id === -1 ? canDelete && <button className="button client-restore-action" type="button" title="Restaurar como inactivo" aria-label={`Restaurar ${group.nombre}`} disabled={restoringId === group.id} onClick={event => { event.stopPropagation(); void restore(group); }}><Icon name="undo" size={14} />Restaurar</button> : <>
            {canEdit && <><Link className="client-row-action" to={`/grupos/${group.id}/editar`} title="Editar" aria-label={`Editar ${group.nombre}`} onClick={event => event.stopPropagation()}><Icon name="edit" size={16} /></Link><button className="client-row-action" type="button" title={group.estado_id === 1 ? 'Inactivar' : 'Activar'} aria-label={`${group.estado_id === 1 ? 'Inactivar' : 'Activar'} ${group.nombre}`} disabled={changingId === group.id} onClick={event => { event.stopPropagation(); void changeState(group); }}><Icon name="power" size={16} /></button></>}
            {canHistory && <Link className="client-row-action" to={`/grupos/${group.id}?historial=1`} title="Ver historial de cambios" aria-label={`Ver historial de cambios de ${group.nombre}`} onClick={event => event.stopPropagation()}><Icon name="clock" size={16} /></Link>}
            {canDelete && <button className="client-row-action client-row-action-danger" type="button" title="Eliminar" aria-label={`Eliminar ${group.nombre}`} onClick={event => { event.stopPropagation(); setDeleteError(''); setDeleteTarget(group); }}><Icon name="trash" size={16} /></button>}
          </>}</div></td>
        </tr>) : <tr><td colSpan={6} className="empty-cell"><EmptyState title={state === 'eliminados' ? 'No hay registros eliminados' : query.trim() ? 'Sin resultados para los filtros' : 'Aún no hay grupos'} detail={query.trim() ? 'Prueba con otro término de búsqueda.' : 'El contenido aparecerá cuando haya información disponible.'} /></td></tr>}
      </tbody></table></div>{page?.siguiente && <div className="form-actions"><button className="button" type="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? 'Cargando…' : 'Cargar más'}</button></div>}
    </section>
    {deleteTarget && <ConfirmDialog title="Eliminar grupo" description={<><strong>{deleteTarget.nombre}</strong> pasará a estado Eliminado. ¿Desea Continuar?.</>} error={deleteError} busy={deleting} confirmLabel="Eliminar" busyLabel="Eliminando…" onConfirm={() => void remove()} onClose={() => setDeleteTarget(null)} />}
  </>;
}

function Selection<T extends { id: number; nombre: string }>({ title, items, selected, setSelected, detail }: {
  title: string; items: T[]; selected: number[]; setSelected: (ids: number[]) => void; detail: (row: T) => string;
}) {
  const [query, setQuery] = useState('');
  const visible = items.filter(item => `${item.nombre} ${detail(item)}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <section className="group-picker" aria-label={`Seleccionar ${title.toLocaleLowerCase()}`}><div className="group-picker-heading"><Icon name={title === 'Usuarios' ? 'user' : 'briefcase'} size={16} /><strong>{title}</strong><span className="group-picker-count" aria-label={`${selected.length} seleccionados`}>{selected.length}</span></div><label className="group-picker-filter"><Icon name="search" size={15} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Filtrar…" aria-label={`Filtrar ${title.toLocaleLowerCase()}`} /></label><div className="group-picker-items">{visible.map(item => <label key={item.id} className={`group-picker-item${selected.includes(item.id) ? ' on' : ''}`}><input type="checkbox" checked={selected.includes(item.id)} onChange={event => setSelected(event.target.checked ? [...selected, item.id].sort((a, b) => a - b) : selected.filter(id => id !== item.id))} /><span><b>{item.nombre}</b><small>{detail(item)}</small></span></label>)}{!visible.length && <p className="group-picker-empty">{items.length ? 'Sin resultados para el filtro.' : 'Sin opciones disponibles.'}</p>}</div></section>;
}

export function GroupForm() {
  const { id } = useParams();
  const editId = id ? Number(id) : null;
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [state, setState] = useState(1);
  const [users, setUsers] = useState<User[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [userIds, setUserIds] = useState<number[]>([]);
  const [accountIds, setAccountIds] = useState<number[]>([]);
  const [etag, setEtag] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let live = true;
    Promise.all([allRows<User>('/usuarios'), allRows<Account>('/cuentas'),
      editId ? api(`/grupos/${editId}`).then(async response => ({ row: await response.json() as Group, etag: response.headers.get('ETag') || '' })) : Promise.resolve(null),
    ]).then(([userRows, accountRows, loaded]) => {
      if (!live) return;
      setUsers(userRows); setAccounts(accountRows);
      if (loaded) { setName(loaded.row.nombre); setDescription(loaded.row.descripcion || ''); setState(loaded.row.estado_id);
        setUserIds(loaded.row.usuario_ids); setAccountIds(loaded.row.cuenta_ids); setEtag(loaded.etag); }
      setReady(true);
    }).catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [editId]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !ready) return;
    setBusy(true); setNotice('');
    try {
      const response = await api(editId ? `/grupos/${editId}` : '/grupos', {
        method: editId ? 'PATCH' : 'POST', headers: editId ? { 'If-Match': etag } : undefined,
        body: JSON.stringify({ nombre: name, descripcion: description || null,
          usuario_ids: userIds, cuenta_ids: accountIds, estado_id: state }),
      });
      const saved = await response.json() as Group;
      toast(editId ? 'Grupo actualizado' : 'Grupo creado', saved.nombre);
      navigate(`/grupos/${saved.id}`);
    } catch (error) { setNotice(message(error)); toast('No se pudo guardar', message(error), 'err'); }
    finally { setBusy(false); }
  }
  return <>
    <div className="page-heading"><div><h1>{editId ? 'Editar grupo' : 'Nuevo grupo'}</h1><p>{DESCRIPTION}</p></div></div>
    <form className="panel creation-form" onSubmit={submit}><div className="panel-heading"><h2>{editId ? 'Editar grupo' : 'Nuevo grupo'}</h2></div><div className="creation-form-body"><div className="form-grid">
      <div className="field"><label htmlFor="group-name">Nombre del grupo *</label><input id="group-name" value={name} onChange={event => setName(event.target.value)} required /></div>
      <div className="field"><label htmlFor="group-state">Estado</label><select id="group-state" value={state} onChange={event => setState(Number(event.target.value))}><option value={1}>Activo</option><option value={0}>Inactivo</option></select></div>
      <div className="field span2"><label htmlFor="group-description">Descripción</label><input id="group-description" value={description} onChange={event => setDescription(event.target.value)} /></div>
    </div><div className="group-picker-grid"><Selection title="Usuarios" items={users} selected={userIds} setSelected={setUserIds} detail={row => row.email} /><Selection title="Cuentas" items={accounts} selected={accountIds} setSelected={setAccountIds} detail={row => row.cliente_nombre} /></div>
    {notice && <p className="control-notice error" role="alert">{notice}</p>}</div><div className="form-actions creation-actions"><Link className="button" to={editId ? `/grupos/${editId}` : '/grupos'}><Icon name="arrow" size={15} />Cancelar</Link><button className="button primary" type="submit" disabled={!ready || busy}><Icon name="check" size={15} />{busy ? 'Guardando…' : 'Guardar'}</button></div></form>
  </>;
}

export function GroupDetail({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const autoHistory = searchParams.get('historial') === '1';
  const canHistory = Boolean(yo?.permisos.auditoria?.includes('ver'));
  const [group, setGroup] = useState<Group | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [notice, setNotice] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<AuditEvent[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [historyBusy, setHistoryBusy] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setGroup(null); setNotice(''); setHistory([]); setHistoryOpen(false);
    const userCatalog = yo?.permisos.usuarios?.includes('ver') ? allRows<User>('/usuarios') : Promise.resolve([] as User[]);
    const accountCatalog = yo?.permisos.cuentas?.includes('ver') ? allRows<Account>('/cuentas') : Promise.resolve([] as Account[]);
    Promise.all([api(`/grupos/${id}`).then(response => response.json() as Promise<Group>), userCatalog, accountCatalog])
      .then(([row, userRows, accountRows]) => { if (live) { setGroup(row); setUsers(userRows); setAccounts(accountRows); } })
      .catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [id, yo]);
  async function loadHistory(cursor?: string) {
    if (historyBusy) return;
    setHistoryOpen(true); setHistoryBusy(true); setHistoryError('');
    const params = new URLSearchParams({ limite: '25' });
    if (cursor) params.set('cursor', cursor);
    try {
      const response = await api(`/grupos/${id}/historial?${params}`);
      const events = await response.json() as AuditEvent[];
      setHistory(previous => cursor ? [...previous, ...events] : events);
      setNextCursor(response.headers.get('X-Next-Cursor'));
    } catch (error) { setHistoryError(message(error)); }
    finally { setHistoryBusy(false); }
  }
  useEffect(() => { if (autoHistory && canHistory) void loadHistory(); }, [id, autoHistory, canHistory]);
  const userName = (identifier: number) => users.find(item => item.id === identifier)?.nombre || `Usuario ${identifier}`;
  const accountName = (identifier: number) => accounts.find(item => item.id === identifier)?.nombre || `Cuenta ${identifier}`;
  return <>
    <div className="page-heading"><div><h1>Detalle de grupo</h1><p>{DESCRIPTION}</p></div>{group && group.estado_id !== -1 && yo?.permisos.grupos?.includes('editar') && <Link className="button primary heading-action" to={`/grupos/${group.id}/editar`}><Icon name="edit" size={16} />Editar</Link>}</div>
    {notice && <p className="control-notice error" role="alert">{notice}</p>}
    {group && <section className="panel creation-form"><div className="panel-heading"><h2>{group.nombre}</h2></div><div className="creation-form-body"><dl className="client-access-kv"><dt>Descripción</dt><dd>{group.descripcion || '—'}</dd><dt>Estado</dt><dd><StateBadge state={group.estado_id} /></dd><dt>Usuarios</dt><dd>{yo?.permisos.usuarios?.includes('ver') ? group.usuario_ids.map(userName).join(', ') || '—' : `${group.usuario_ids.length} vinculados`}</dd><dt>Cuentas asociadas</dt><dd>{group.cuenta_ids.map(accountName).join(', ') || '—'}</dd></dl><AuditMetadata record={group} canViewUsers={Boolean(yo?.permisos.usuarios?.includes('ver'))} /></div><div className="form-actions client-detail-actions"><Link className="button" to="/grupos">Volver a Grupos</Link>{canHistory && <button className="button" type="button" onClick={() => historyOpen ? setHistoryOpen(false) : void loadHistory()}><Icon name="clock" size={15} />{historyOpen ? 'Ocultar historial' : 'Ver historial de cambios'}</button>}</div></section>}
    {group && historyOpen && <section className="panel role-history" aria-label="Historial de cambios"><div className="panel-heading"><h2>Historial de cambios</h2></div>{historyError && <p className="control-notice error" role="alert">{historyError}</p>}{historyBusy && !history.length ? <p className="role-history-empty" role="status">Cargando historial…</p> : !history.length && !historyError ? <p className="role-history-empty">No hay cambios registrados para este grupo.</p> : <ol>{history.map(event => <li key={`${event.fecha}-${event.id}`}><strong>{event.accion}</strong><span>{new Date(event.fecha).toLocaleString('es-CO')} · Usuario {event.usuario_id ?? 'sistema'}</span><details><summary>Ver datos registrados</summary><pre>Antes: {JSON.stringify(event.antes, null, 2) || '—'}{'\n'}Después: {JSON.stringify(event.despues, null, 2) || '—'}</pre></details></li>)}</ol>}{nextCursor && <button className="button" type="button" disabled={historyBusy} onClick={() => void loadHistory(nextCursor)}>Ver más</button>}</section>}
  </>;
}
