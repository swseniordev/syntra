import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Icon } from '../../shared/Icon';
import { StateBadge } from '../../shared/StateBadge';
import { EmptyState } from '../../shared/EmptyState';
import { ConfirmDialog } from '../../shared/ConfirmDialog';
import { api } from '../../shared/api';
import type { Cliente, ClienteDetalle, CuentaResumen, Yo } from '../../shared/api';
import { useToast } from '../../shared/Toast';
import { PageHeading } from '../../shared/PageHeading';
import { clientError } from '../../shared/httpErrors';
import { ENTITY_SPECS, ENTITY_STATES, CreationFormPage } from '../general/GenericEntityModule';
import { formatClientDateTime } from '../../app/runtime';
export function ClientsPage({ yo }: { yo: Yo | null }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [state, setState] = useState('vig');
  const [sector, setSector] = useState('');
  const [sectorOptions, setSectorOptions] = useState<string[]>([]);
  const [items, setItems] = useState<Cliente[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [reload, setReload] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<Cliente | null>(null);
  const [deleteError, setDeleteError] = useState('');
  const [deleting, setDeleting] = useState(false);
  const [restoringId, setRestoringId] = useState<number | null>(null);
  const [changingId, setChangingId] = useState<number | null>(null);
  const canCreate = yo?.permisos.clientes?.includes('crear') ?? false;
  const canEdit = yo?.permisos.clientes?.includes('editar') ?? false;
  const canDelete = yo?.permisos.clientes?.includes('eliminar') ?? false;
  const canHistory = yo?.permisos.auditoria?.includes('ver') ?? false;
  useEffect(() => {
    let live = true;
    api('/clientes/sectores').then(response => response.json()).then(data => {
      if (live) setSectorOptions(data.items as string[]);
    }).catch(() => { if (live) setSectorOptions([]); });
    return () => { live = false; };
  }, [reload]);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setItems([]);
    setNext(null);
    setNotice('');
    const timeout = window.setTimeout(async () => {
      const params = new URLSearchParams({ estado: { vig: 'vigentes', act: 'activos', ina: 'inactivos', del: 'eliminados' }[state] || 'vigentes' });
      if (query.trim()) params.set('q', query.trim());
      if (sector) params.set('sector', sector);
      try {
        const response = await api(`/clientes?${params}`);
        const page = await response.json();
        if (live) { setItems(page.items); setNext(page.siguiente); setNotice(''); }
      } catch (error) { if (live) setNotice(error instanceof Error ? error.message : 'No se pudo cargar Clientes.'); }
      finally { if (live) setLoading(false); }
    }, 180);
    return () => { live = false; window.clearTimeout(timeout); };
  }, [query, state, sector, reload]);
  async function deleteClient() {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    setDeleteError('');
    try {
      await api(`/clientes/${deleteTarget.id}`, { method: 'DELETE' });
      toast('Eliminado lógicamente', deleteTarget.nombre);
      setDeleteTarget(null);
      setReload(value => value + 1);
    } catch (error) {
      const message = clientError(error, 'No se pudo eliminar el cliente.');
      setDeleteError(message);
      toast('No se pudo eliminar', message, 'err');
    } finally { setDeleting(false); }
  }
  async function changeClientState(client: Cliente) {
    if (changingId !== null) return;
    setChangingId(client.id);
    try {
      await api(`/clientes/${client.id}/estado`, {
        method: 'POST', body: JSON.stringify({ estado_id: client.estado_id === 1 ? 0 : 1 }),
      });
      toast(client.estado_id === 1 ? 'Inactivado' : 'Activado', client.nombre);
      setReload(value => value + 1);
    } catch (error) {
      toast('No se pudo cambiar el estado', clientError(error, 'Inténtalo de nuevo.'), 'err');
    } finally { setChangingId(null); }
  }
  async function restoreClient(client: Cliente) {
    if (restoringId !== null) return;
    setRestoringId(client.id);
    try {
      await api(`/clientes/${client.id}/restaurar`, { method: 'POST' });
      toast('Restaurado como Inactivo', `${client.nombre} — actívalo cuando esté listo.`);
      setReload(value => value + 1);
    } catch (error) {
      toast('No se pudo restaurar', clientError(error, 'Inténtalo de nuevo.'), 'err');
    } finally { setRestoringId(null); }
  }
  async function loadMore() {
    if (!next || loadingMore) return;
    setLoadingMore(true);
    const params = new URLSearchParams({ estado: { vig: 'vigentes', act: 'activos', ina: 'inactivos', del: 'eliminados' }[state] || 'vigentes', cursor: next });
    if (query.trim()) params.set('q', query.trim());
    if (sector) params.set('sector', sector);
    try {
      const page = await (await api(`/clientes?${params}`)).json();
      setItems(current => [...current, ...page.items]);
      setNext(page.siguiente);
    } catch (error) { setNotice(error instanceof Error ? error.message : 'No se pudo cargar la página.'); }
    finally { setLoadingMore(false); }
  }
  return <>
    <PageHeading title="Clientes" description={ENTITY_SPECS['/clientes'].description} action={canCreate ? { label: 'Nuevo cliente', icon: 'plus', path: '/clientes/nuevo', className: 'client-create-action' } : undefined} />
    <section className="panel entity-list-panel">
      <div className="module-toolbar entity-toolbar" aria-label="Filtros de Clientes">
        <label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar clientes…" aria-label="Buscar clientes" /></label>
        <select aria-label="Sector" value={sector} onChange={event => setSector(event.target.value)}><option value="">Sector: todos</option>{sectorOptions.map(option => <option key={option} value={option}>{option}</option>)}</select>
        <div className="seg status-segment" role="group" aria-label="Filtrar clientes por estado">{ENTITY_STATES.map(([key, label]) => <button type="button" key={key} className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}<span className="n">—</span></button>)}</div>
      </div>
      {notice && <p className="control-notice error" role="alert">{notice}</p>}
      <div className="table-wrap"><table className="data-table client-table"><thead><tr>{['Cliente', 'Sector', 'Cuentas', 'Contacto', 'Estado', 'Actualizado', 'Acciones'].map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>{loading ? <tr><td colSpan={7} className="empty-cell" role="status">Cargando clientes…</td></tr> : items.length ? items.map(client =>
        <tr key={client.id} className={client.estado_id === -1 ? 'client-row-deleted' : 'client-row'} tabIndex={client.estado_id === -1 ? undefined : 0} aria-label={client.estado_id === -1 ? `Cliente eliminado ${client.nombre}` : `Ver detalle de ${client.nombre}`} onClick={event => { if (client.estado_id !== -1 && (!(event.target instanceof Element) || !event.target.closest('a,button,[data-row-action]'))) navigate(`/clientes/${client.id}`); }} onKeyDown={event => { if (client.estado_id !== -1 && event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) { event.preventDefault(); navigate(`/clientes/${client.id}`); } }}>
          <td><strong>{client.nombre}</strong></td><td>{client.sector || '—'}</td><td>—</td><td>{client.contacto || '—'}</td><td><StateBadge state={client.estado_id} /></td><td>{new Date(client.actualizado_en).toLocaleDateString('es-CO')}</td>
          <td><div className="client-row-actions">
            {client.estado_id === -1 ? canDelete && <button className="button client-restore-action" type="button" title="Restaurar como inactivo" aria-label={`Restaurar ${client.nombre}`} disabled={restoringId === client.id} onClick={event => { event.stopPropagation(); void restoreClient(client); }}><Icon name="undo" size={14} />{restoringId === client.id ? 'Restaurando…' : 'Restaurar'}</button> : <>
              {canEdit && <><Link className="client-row-action" to={`/clientes/${client.id}/editar`} title="Editar" aria-label={`Editar ${client.nombre}`} onClick={event => event.stopPropagation()}><Icon name="edit" size={16} /></Link><button className="client-row-action" type="button" title={client.estado_id === 1 ? 'Inactivar' : 'Activar'} aria-label={`${client.estado_id === 1 ? 'Inactivar' : 'Activar'} ${client.nombre}`} disabled={changingId === client.id} onClick={event => { event.stopPropagation(); void changeClientState(client); }}><Icon name="power" size={16} /></button></>}
              {canHistory && <Link className="client-row-action" to={`/clientes/${client.id}?historial=1`} title="Ver historial de cambios" aria-label={`Ver historial de cambios de ${client.nombre}`} onClick={event => event.stopPropagation()}><Icon name="clock" size={16} /></Link>}
              {canDelete && <button className="client-row-action client-row-action-danger" type="button" title="Eliminar" aria-label={`Eliminar ${client.nombre}`} onClick={event => { event.stopPropagation(); setDeleteError(''); setDeleteTarget(client); }}><Icon name="trash" size={16} /></button>}
            </>}
          </div></td>
        </tr>) : !notice && <tr><td colSpan={7} className="empty-cell"><EmptyState title={query || sector ? 'Sin resultados para los filtros' : state === 'del' ? 'No hay registros eliminados' : 'Aún no hay clientes'} detail="El contenido aparecerá cuando haya información disponible." /></td></tr>}</tbody></table></div>
      {next && <div className="form-actions"><button type="button" className="button" onClick={loadMore} disabled={loadingMore}>{loadingMore ? 'Cargando…' : 'Cargar más'}</button></div>}
    </section>
    {deleteTarget && <ConfirmDialog title="Eliminar cliente" description={<><strong>{deleteTarget.nombre}</strong> pasará a estado Eliminado. ¿Desea Continuar?.</>} error={deleteError} busy={deleting} confirmLabel="Eliminar" busyLabel="Eliminando…" onConfirm={deleteClient} onClose={() => setDeleteTarget(null)} />}
  </>;
}

export function ClientDetail({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const [historyOpen, setHistoryOpen] = useState(searchParams.get('historial') === '1');
  const [client, setClient] = useState<ClienteDetalle | null>(null);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [accounts, setAccounts] = useState<CuentaResumen[]>([]);
  const [accountsLoading, setAccountsLoading] = useState(false);
  const [accountsNotice, setAccountsNotice] = useState('');
  const canViewAccounts = yo?.permisos.cuentas?.includes('ver') ?? false;
  const canViewHistory = yo?.permisos.auditoria?.includes('ver') ?? false;
  useEffect(() => {
    let live = true;
    setLoading(true);
    setClient(null);
    setNotice('');
    api(`/clientes/${id}`).then(response => response.json()).then(data => { if (live) setClient(data); }).catch(error => { if (live) setNotice(error instanceof Error ? error.message : 'No se pudo cargar el cliente.'); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [id]);
  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    setAccounts([]);
    setAccountsNotice('');
    setAccountsLoading(canViewAccounts);
    if (canViewAccounts) {
      void (async () => {
        try {
          let cursor: string | null = null;
          const found: CuentaResumen[] = [];
          do {
            const params = new URLSearchParams({ cliente_id: String(id), estado: 'vigentes', limite: '200' });
            if (cursor) params.set('cursor', cursor);
            const page = await (await api(`/cuentas?${params}`, { signal: controller.signal })).json();
            found.push(...(page.items as CuentaResumen[]));
            cursor = page.siguiente;
          } while (cursor && live);
          if (live) setAccounts(found);
        } catch (error) {
          if (live) setAccountsNotice(error instanceof Error ? error.message : 'No se pudieron cargar las cuentas.');
        } finally { if (live) setAccountsLoading(false); }
      })();
    }
    return () => { live = false; controller.abort(); };
  }, [id, canViewAccounts]);
  return <>
    <PageHeading title={client?.nombre || 'Cliente'} description="Detalle del cliente" action={client && client.estado_id !== -1 && yo?.permisos.clientes?.includes('editar') ? { label: 'Editar cliente', path: `/clientes/${client.id}/editar`, icon: 'edit' } : undefined} />
    {loading && <p className="control-notice" role="status">Cargando cliente…</p>}
    {notice && <p className="control-notice error" role="alert">{notice}</p>}
    {client && <section className="panel creation-form"><div className="panel-heading"><h2>{client.nombre}</h2></div><div className="creation-form-body"><div className="form-grid"><div className="field"><label>RFC</label><p>{client.rfc || '—'}</p></div><div className="field"><label>Sector</label><p>{client.sector || '—'}</p></div><div className="field"><label>Contacto</label><p>{client.contacto || '—'}</p></div><div className="field"><label>Estado</label><p><StateBadge state={client.estado_id} /></p></div></div><section className="fieldset client-access" aria-labelledby="client-access-title"><h3 className="fieldset-title" id="client-access-title"><Icon name="shield" size={16} />Accesos al cliente</h3><dl className="client-access-kv"><dt>Cuentas</dt><dd>{!canViewAccounts ? 'No tienes permiso para consultar cuentas asociadas.' : accountsLoading ? <span role="status">Cargando cuentas…</span> : accountsNotice ? <span role="alert">{accountsNotice}</span> : accounts.length ? <ul className="client-account-list">{accounts.map(account => <li key={account.id}><span>{account.nombre}</span><span className={`client-account-status ${account.estado_id === 1 ? 'active' : 'inactive'}`}>{account.estado_id === 1 ? 'Activa' : 'Inactiva'}</span></li>)}</ul> : 'No hay cuentas asociadas.'}</dd></dl></section><p className="client-audit-foot">Creado por <b>{client.creado_por_nombre || (client.creado_por == null ? 'No registrado' : 'Usuario no disponible')}</b> · <time dateTime={client.creado_en}>{formatClientDateTime(client.creado_en)}</time><br />Actualizado por <b>{client.actualizado_por_nombre || (client.actualizado_por == null ? 'No registrado' : 'Usuario no disponible')}</b> · <time dateTime={client.actualizado_en}>{formatClientDateTime(client.actualizado_en)}</time></p></div><div className="form-actions client-detail-actions"><Link className="button" to="/clientes">Volver a Clientes</Link>{canViewHistory && <button className="button" type="button" onClick={() => setHistoryOpen(open => !open)}><Icon name="clock" size={15} />{historyOpen ? 'Ocultar historial' : 'Ver historial de cambios'}</button>}</div></section>}
    {client && canViewHistory && historyOpen && <ClientHistoryPanel key={client.id} clientId={client.id} />}
  </>;
}

type ClientAuditEvent = { id: number; fecha: string; accion: string; usuario_id: number | null;
  antes: Record<string, unknown> | null; despues: Record<string, unknown> | null };

function ClientHistoryPanel({ clientId }: { clientId: number }) {
  const [events, setEvents] = useState<ClientAuditEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  async function load(next?: string) {
    setBusy(true); setError('');
    const params = new URLSearchParams({ limite: '25' });
    if (next) params.set('cursor', next);
    try {
      const response = await api(`/clientes/${clientId}/historial?${params}`);
      const rows = await response.json() as ClientAuditEvent[];
      setEvents(previous => next ? [...previous, ...rows] : rows);
      setCursor(response.headers.get('X-Next-Cursor'));
    } catch (cause) { setError(clientError(cause, 'No se pudo consultar el historial.')); }
    finally { setBusy(false); }
  }
  useEffect(() => { void load(); }, [clientId]);
  return <section className="panel role-history" aria-label="Historial de cambios"><div className="panel-heading"><h2>Historial de cambios</h2></div>
    {error && <p className="control-notice error" role="alert">{error} <button className="button small" type="button" onClick={() => void load(cursor || undefined)}>Reintentar</button></p>}
    {busy && !events.length ? <p className="role-history-empty" role="status">Cargando historial…</p>
      : !events.length && !error ? <EmptyState icon="clock" title="Sin cambios registrados" detail="Los eventos de este cliente aparecerán aquí." />
        : <ol>{events.map(event => <li key={`${event.fecha}-${event.id}`}><strong>{event.accion}</strong><span>{formatClientDateTime(event.fecha)} · Usuario {event.usuario_id ?? 'sistema'}</span><details><summary>Ver datos registrados</summary><pre>Antes: {JSON.stringify(event.antes, null, 2) || '—'}{'\n'}Después: {JSON.stringify(event.despues, null, 2) || '—'}</pre></details></li>)}</ol>}
    {cursor && <button className="button" type="button" disabled={busy} onClick={() => void load(cursor)}>Ver más</button>}
  </section>;
}

export function ClientEditRoute() {
  const { id } = useParams();
  return <CreationFormPage path="/clientes" editId={Number(id)} />;
}
