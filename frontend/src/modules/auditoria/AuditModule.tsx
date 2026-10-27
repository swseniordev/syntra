import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Icon } from '../../shared/Icon';
import { EmptyState } from '../../shared/EmptyState';
import { api, ApiError } from '../../shared/api';
import type { Yo } from '../../shared/api';
import { useToast } from '../../shared/Toast';
import { createAuditExportIdempotencyKey, downloadAuditExport, rememberAuditExport } from '../../shared/auditExports';

type AuditEvent = { id: number; fecha: string; usuario_id: number | null; modulo: string; accion: string;
  entidad_tipo: string; entidad_id: string | null; entidad_nombre: string | null;
  antes: Record<string, unknown> | null; despues: Record<string, unknown> | null;
  detalle: string | null; ip: string | null; request_id: string | null };
type User = { id: number; nombre: string };
type Page<T> = { items: T[]; siguiente: string | null; total_aprox?: number };
type AuditSummary = { por_dia: { dia: string; total: number }[]; por_modulo: { modulo: string; total: number }[] };
type ExportProcess = { id: number; estado: string; procesados: number; total: number; errores: number };
type Accepted = { proceso_id: number; tipo: string; estado: string };
const MODULES = [['clientes', 'Clientes'], ['cuentas', 'Cuentas'], ['usuarios', 'Usuarios'], ['roles', 'Roles'],
  ['grupos', 'Grupos'], ['prompts', 'Prompts'], ['regex', 'Regex'], ['paises', 'Países']];
const ACTIONS = [['crear', 'Creación', 'ok'], ['editar', 'Actualización', 'info'], ['eliminar', 'Eliminación lógica', 'err'],
  ['restaurar', 'Restauración', 'warn'], ['cambio_estado', 'Cambio de estado', 'warn']];
const PERIODS = [['1', 'Últimas 24 h'], ['7', 'Últimos 7 días'], ['30', 'Últimos 30 días'], ['365', 'Último año']];
const DESCRIPTION = 'Trazabilidad de los cambios realizados en la plataforma.';

function message(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'El servidor no pudo completar la operación. Inténtalo de nuevo.';
    if (error.status === 401) return 'La sesión venció. Ingresa de nuevo.';
    if (error.status === 403) return 'No tienes permiso para consultar Auditoría.';
    return error.message;
  }
  return 'No se pudo cargar Auditoría.';
}

function formatDate(value: string) { return new Date(value).toLocaleString('es-CO'); }
function actionLabel(value: string) { return ACTIONS.find(([code]) => code === value)?.[1] || value; }
function actionClass(value: string) { return ACTIONS.find(([code]) => code === value)?.[2] || 'outline'; }
function changedFields(event: AuditEvent): string[] {
  const before = event.antes || {};
  const after = event.despues || {};
  return [...new Set([...Object.keys(before), ...Object.keys(after)])]
    .filter(key => JSON.stringify(before[key]) !== JSON.stringify(after[key]));
}

function bogotaDay(value: Date): string {
  const pieces = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Bogota',
    year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(value);
  const part = (name: string) => pieces.find(item => item.type === name)?.value || '';
  return `${part('year')}-${part('month')}-${part('day')}`;
}

function DailyChart({ summary, anchor }: { summary: AuditSummary; anchor: number }) {
  const counts = new Map(summary.por_dia.map(row => [row.dia, row.total]));
  const days = Array.from({ length: 30 }, (_, index) => bogotaDay(new Date(anchor - (29 - index) * 86_400_000)));
  const values = days.map(day => counts.get(day) || 0);
  const maximum = Math.max(4, ...values);
  const labels = [0, 1, 2, 3, 4].map(step => Math.round(maximum * step / 4));
  return <div className="audit-chart-body"><svg className="audit-daily-chart" viewBox="0 0 620 170" role="img" aria-label="Eventos de auditoría por día durante los últimos 30 días">
    {labels.map((label, index) => { const y = 142 - index * 31; return <g key={index}><line x1="42" x2="614" y1={y} y2={y} className="audit-grid-line" /><text x="34" y={y + 4} textAnchor="end">{label}</text></g>; })}
    {days.map((day, index) => { const height = Math.max(1, values[index] / maximum * 124); const x = 47 + index * 19;
      return <g key={day}><rect className="audit-chart-bar" x={x} y={142 - height} width="12" height={height} rx="3"><title>{day}: {values[index]} eventos</title></rect>{index % 5 === 0 && <text x={x + 6} y="163" textAnchor="middle">{day.slice(8)} {new Date(`${day}T12:00:00Z`).toLocaleDateString('es-CO', { month: 'short', timeZone: 'UTC' })}</text>}</g>; })}
  </svg></div>;
}

function ModuleChart({ summary }: { summary: AuditSummary }) {
  const rows = summary.por_modulo.slice(0, 6);
  const maximum = Math.max(1, ...rows.map(row => row.total));
  return <div className="audit-chart-body audit-module-chart">{rows.length ? rows.map(row => <div className="audit-hbar-row" key={row.modulo} title={`${row.modulo}: ${row.total} eventos`}>
    <span className="audit-hbar-label">{MODULES.find(([code]) => code === row.modulo)?.[1] || row.modulo}</span><span className="audit-hbar-track"><span className="audit-hbar-fill" style={{ width: `${Math.max(1.5, row.total / maximum * 100)}%` }} /></span><strong>{row.total}</strong>
  </div>) : <p className="muted">Sin eventos en los últimos 30 días.</p>}</div>;
}

export function AuditList({ yo }: { yo: Yo | null }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [periodAnchor] = useState(() => Date.now());
  const [query, setQuery] = useState('');
  const [module, setModule] = useState('');
  const [user, setUser] = useState('');
  const [action, setAction] = useState('');
  const [period, setPeriod] = useState('30');
  const [users, setUsers] = useState<User[]>([]);
  const [pages, setPages] = useState<Page<AuditEvent>[]>([]);
  const [pageIndex, setPageIndex] = useState(0);
  const [activeFilterKey, setActiveFilterKey] = useState('');
  const requestGeneration = useRef(0);
  const [summary, setSummary] = useState<AuditSummary | null>(null);
  const [summaryError, setSummaryError] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [notice, setNotice] = useState('');
  const [exporting, setExporting] = useState(false);
  const [exportProcess, setExportProcess] = useState<ExportProcess | null>(null);
  const filterKey = JSON.stringify([query.trim(), module, user, action, period]);
  const canExport = Boolean(yo?.permisos.auditoria?.includes('ver') && yo?.permisos.procesos?.includes('ver'));

  useEffect(() => {
    let live = true;
    const startDay = bogotaDay(new Date(periodAnchor - 29 * 86_400_000));
    const params = new URLSearchParams({ desde: `${startDay}T00:00:00-05:00`, hasta: new Date(periodAnchor).toISOString() });
    api(`/auditoria/resumen?${params}`).then(response => response.json())
      .then((data: AuditSummary) => { if (live) setSummary(data); })
      .catch(error => { if (live) setSummaryError(message(error)); });
    return () => { live = false; };
  }, [periodAnchor]);

  useEffect(() => {
    if (!exportProcess || !['en_cola', 'en_ejecucion'].includes(exportProcess.estado)) return;
    let live = true;
    let timer: number;
    async function poll() {
      try {
        const result = await (await api(`/procesos/${exportProcess!.id}`)).json() as ExportProcess;
        if (!live) return;
        setExportProcess(result);
        if (result.estado === 'completado') toast('Exportación lista', 'El archivo de Auditoría ya se puede descargar.');
        else if (result.estado === 'error') toast('Falló la exportación', 'Consulta el estado del proceso o inténtalo de nuevo.', 'err');
        else timer = window.setTimeout(() => void poll(), 2500);
      } catch (error) { if (live) setNotice(message(error)); }
    }
    timer = window.setTimeout(() => void poll(), 1000);
    return () => { live = false; window.clearTimeout(timer); };
  }, [exportProcess?.id, exportProcess?.estado, toast]);

  async function startExport() {
    if (!canExport || exporting) return;
    setExporting(true); setNotice('');
    const params = parameters();
    const body = { modulo: module || undefined, usuario_id: user ? Number(user) : undefined,
      accion: action || undefined, desde: params.get('desde'), q: query.trim() || undefined };
    try {
      const result = await (await api('/auditoria/exportar', { method: 'POST',
        headers: { 'Idempotency-Key': createAuditExportIdempotencyKey() }, body: JSON.stringify(body) })).json() as Accepted;
      setExportProcess({ id: result.proceso_id, estado: result.estado, procesados: 0, total: 0, errores: 0 });
      if (yo?.usuario?.id) rememberAuditExport(yo.usuario.id, result.proceso_id);
      toast('Exportación solicitada', 'Se generará un XLSX con los filtros actuales.');
    } catch (error) { setNotice(message(error)); toast('No se pudo solicitar la exportación', message(error), 'err'); }
    finally { setExporting(false); }
  }

  async function downloadExport() {
    if (!exportProcess || exportProcess.estado !== 'completado') return;
    try {
      await downloadAuditExport(exportProcess.id);
    } catch (error) { setNotice(message(error)); toast('No se pudo descargar', message(error), 'err'); }
  }

  useEffect(() => {
    let live = true;
    api('/usuarios?estado=vigentes&limite=200').then(response => response.json())
      .then((data: Page<User>) => { if (live) setUsers(data.items); })
      .catch(() => { if (live) setUsers([]); });
    return () => { live = false; };
  }, []);

  function parameters(cursor?: string) {
    const from = new Date(periodAnchor - Number(period) * 86_400_000).toISOString();
    const params = new URLSearchParams({ desde: from, limite: '25' });
    if (query.trim()) params.set('q', query.trim());
    if (module) params.set('modulo', module);
    if (user) params.set('usuario_id', user);
    if (action) params.set('accion', action);
    if (cursor) params.set('cursor', cursor);
    return params;
  }

  useEffect(() => {
    let live = true;
    const generation = ++requestGeneration.current;
    setLoading(true); setPages([]); setPageIndex(0); setLoadingMore(false); setActiveFilterKey(filterKey);
    const timer = window.setTimeout(async () => {
      try {
        const result = await (await api(`/auditoria?${parameters()}`)).json() as Page<AuditEvent>;
        if (live && requestGeneration.current === generation) { setPages([result]); setNotice(''); }
      } catch (error) { if (live) setNotice(message(error)); }
      finally { if (live) setLoading(false); }
    }, 180);
    return () => { live = false; window.clearTimeout(timer); };
  }, [query, module, user, action, period]);

  const page = activeFilterKey === filterKey ? pages[pageIndex] || null : null;
  async function loadMore() {
    if (loadingMore) return;
    if (pages[pageIndex + 1]) { setPageIndex(index => index + 1); return; }
    if (!page?.siguiente) return;
    const generation = requestGeneration.current;
    setLoadingMore(true);
    try {
      const result = await (await api(`/auditoria?${parameters(page.siguiente)}`)).json() as Page<AuditEvent>;
      if (generation === requestGeneration.current) { setPages(current => [...current, result]); setPageIndex(index => index + 1); }
    } catch (error) { if (generation === requestGeneration.current) setNotice(message(error)); }
    finally { if (generation === requestGeneration.current) setLoadingMore(false); }
  }
  const userName = (identifier: number | null) => identifier === null ? 'Sistema' : users.find(row => row.id === identifier)?.nombre || `Usuario ${identifier}`;
  return <>
    <div className="page-heading"><div><h1>Log de auditoría</h1><p>{DESCRIPTION}</p></div><button className="button primary heading-action" type="button" disabled={!canExport || exporting} onClick={() => void startExport()} title={!canExport ? 'Se requieren permisos de Auditoría y Procesos' : 'Exportar el log filtrado'}><Icon name="download" size={16} />{exporting ? 'Solicitando…' : 'Exportar log'}</button></div>
    {exportProcess && <section className="panel audit-export-status" role="status" aria-live="polite"><strong>Exportación #{exportProcess.id}</strong><span className={`badge ${exportProcess.estado === 'completado' ? 'ok' : exportProcess.estado === 'error' ? 'err' : 'info'}`}>{exportProcess.estado === 'en_cola' ? 'En cola' : exportProcess.estado === 'en_ejecucion' ? 'En proceso' : exportProcess.estado === 'completado' ? 'Completada' : exportProcess.estado === 'error' ? 'Error' : exportProcess.estado}</span>{exportProcess.estado === 'completado' && <button className="button primary" type="button" onClick={() => void downloadExport()}><Icon name="download" size={16} />Descargar XLSX</button>}</section>}
    <div className="dashboard-grid audit-charts"><section className="panel"><header className="panel-heading"><h2>Actividad diaria</h2><span className="panel-sub">últimos 30 días</span></header>{summary ? summary.por_dia.some(row => row.total > 0) ? <DailyChart summary={summary} anchor={periodAnchor} /> : <EmptyState icon="chart" title="Sin actividad para el periodo" detail="El gráfico aparecerá cuando haya eventos registrados." /> : <div className="audit-chart-body"><p className={summaryError ? 'control-notice error' : 'muted'} role={summaryError ? 'alert' : 'status'}>{summaryError || 'Cargando actividad…'}</p></div>}</section><section className="panel"><header className="panel-heading"><h2>Eventos por módulo</h2></header>{summary ? summary.por_modulo.some(row => row.total > 0) ? <ModuleChart summary={summary} /> : <EmptyState icon="grid" title="Sin eventos por módulo" detail="El gráfico aparecerá cuando haya eventos registrados." /> : <div className="audit-chart-body"><p className={summaryError ? 'control-notice error' : 'muted'} role={summaryError ? 'alert' : 'status'}>{summaryError || 'Cargando módulos…'}</p></div>}</section></div>
    <section className="panel entity-list-panel"><div className="module-toolbar audit-toolbar" aria-label="Filtros del log de auditoría"><label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar en el log…" aria-label="Buscar en el log" /></label><select aria-label="Módulo" value={module} onChange={event => setModule(event.target.value)}><option value="">Módulo: todos</option>{MODULES.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select><select aria-label="Usuario" value={user} onChange={event => setUser(event.target.value)}><option value="">Usuario: todos</option>{users.map(row => <option key={row.id} value={row.id}>{row.nombre}</option>)}</select><select aria-label="Acción" value={action} onChange={event => setAction(event.target.value)}><option value="">Acción: todas</option>{ACTIONS.map(([code, label]) => <option key={code} value={code}>{label}</option>)}</select><select aria-label="Periodo" value={period} onChange={event => setPeriod(event.target.value)}>{PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
      {notice && <p className="control-notice error" role="alert">{notice}</p>}
      <div className="table-wrap"><table className="data-table audit-table client-table"><thead><tr><th>Fecha</th><th>Usuario</th><th>Módulo</th><th>Acción</th><th>Entidad</th><th>Cambios</th><th></th></tr></thead><tbody>
        {loading || activeFilterKey !== filterKey ? <tr><td colSpan={7} className="empty-cell" role="status">Cargando eventos…</td></tr> : page?.items.length ? page.items.map(event => <tr key={`${event.fecha}-${event.id}`} className="client-row" tabIndex={0} aria-label={`Ver evento ${event.id} de ${event.entidad_nombre || event.entidad_tipo}`}
          onClick={() => navigate(`/auditoria/${event.id}?fecha=${encodeURIComponent(event.fecha)}`)}
          onKeyDown={key => { if (key.target === key.currentTarget && (key.key === 'Enter' || key.key === ' ')) { key.preventDefault(); navigate(`/auditoria/${event.id}?fecha=${encodeURIComponent(event.fecha)}`); } }}>
          <td>{formatDate(event.fecha)}</td><td>{userName(event.usuario_id)}</td><td>{MODULES.find(([code]) => code === event.modulo)?.[1] || event.modulo}</td><td><span className={`badge ${actionClass(event.accion)}`}>{actionLabel(event.accion)}</span></td><td><strong>{event.entidad_nombre || event.entidad_tipo}</strong><small>{event.entidad_id ? ` #${event.entidad_id}` : ''}</small></td><td>{changedFields(event).slice(0, 3).map(field => <span className="badge outline" key={field}>{field}</span>)}{changedFields(event).length > 3 && <span className="muted">+{changedFields(event).length - 3}</span>}</td><td><Icon name="chevron" size={16} /></td>
        </tr>) : <tr><td colSpan={7} className="empty-cell"><EmptyState icon="scroll" title="Sin eventos para los filtros" detail="Amplía el rango de fechas o limpia los filtros." /></td></tr>}
      </tbody></table></div><div className="table-pager"><span>{page?.items.length ?? 0} eventos</span><div className="table-pager-actions"><button type="button" title="Página anterior" aria-label="Página anterior" disabled={loading || loadingMore || activeFilterKey !== filterKey || pageIndex === 0} onClick={() => setPageIndex(index => index - 1)}><Icon name="chevron_left" size={16} /></button><span className="table-pager-current">{pageIndex + 1}</span><button type="button" title="Página siguiente" aria-label="Página siguiente" disabled={loading || loadingMore || activeFilterKey !== filterKey || (!page?.siguiente && !pages[pageIndex + 1])} onClick={() => void loadMore()}><Icon name="chevron" size={16} /></button></div></div>
    </section>
  </>;
}

export function AuditDetail() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const date = params.get('fecha');
  const [event, setEvent] = useState<AuditEvent | null>(null);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    if (!date) { setNotice('Falta la fecha que identifica el evento.'); return; }
    let live = true;
    api(`/auditoria/${id}?${new URLSearchParams({ fecha: date })}`).then(response => response.json())
      .then((data: AuditEvent) => { if (live) setEvent(data); })
      .catch(error => { if (live) setNotice(message(error)); });
    return () => { live = false; };
  }, [id, date]);
  const keys = event ? changedFields(event) : [];
  return <>
    <div className="page-heading"><div><h1>Detalle del evento</h1><p>{DESCRIPTION}</p></div></div>
    {notice && <p className="control-notice error" role="alert">{notice}</p>}
    {event && <section className="panel creation-form"><div className="panel-heading"><h2>{event.entidad_nombre || event.entidad_tipo}</h2><span className={`badge ${actionClass(event.accion)}`}>{actionLabel(event.accion)}</span></div><div className="creation-form-body"><dl className="client-access-kv"><dt>Fecha</dt><dd>{formatDate(event.fecha)}</dd><dt>Módulo</dt><dd>{event.modulo}</dd><dt>Usuario</dt><dd>{event.usuario_id ?? 'Sistema'}</dd><dt>Entidad</dt><dd>{event.entidad_tipo}{event.entidad_id ? ` #${event.entidad_id}` : ''}</dd><dt>Detalle</dt><dd>{event.detalle || '—'}</dd><dt>IP</dt><dd>{event.ip || '—'}</dd><dt>Solicitud</dt><dd>{event.request_id || '—'}</dd></dl><h3>Cambios</h3>{keys.length ? <div className="audit-diff-table table-wrap"><table className="data-table"><thead><tr><th>Campo</th><th>Antes</th><th>Después</th></tr></thead><tbody>{keys.map(key => <tr key={key}><th scope="row">{key}</th><td>{JSON.stringify(event.antes?.[key]) ?? '—'}</td><td>{JSON.stringify(event.despues?.[key]) ?? '—'}</td></tr>)}</tbody></table></div> : <p className="muted">Sin diferencias de campos registradas.</p>}</div><div className="form-actions client-detail-actions"><Link className="button" to="/auditoria">Volver a Auditoría</Link></div></section>}
  </>;
}
