import { Fragment, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ChangeEvent, CSSProperties, FormEvent, RefObject } from 'react';
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Brand } from '../shared/Brand';
import { Icon } from '../shared/Icon';
import { StateBadge } from '../shared/StateBadge';
import { EmptyState } from '../shared/EmptyState';
import { ConfirmDialog } from '../shared/ConfirmDialog';
import { navigation, routeLabels } from '../shared/navigation';
import { api, ApiError, hasToken, login as loginApi, logout as logoutApi, refreshAccess, watchToken } from '../shared/api';
import type { Cliente, ClienteDetalle, CuentaResumen, Yo } from '../shared/api';
import { ToastProvider, useToast } from '../shared/Toast';
import { RoleDetail, RoleForm, RolesList } from './RolesModule';
import { CountriesList, CountryDetail, CountryForm } from './CountriesModule';
import { PromptsList, PromptDetail, PromptForm } from './PromptsModule';
import { RegexList, RegexDetail, RegexForm } from './RegexModule';
import { AccountsList, AccountDetail, AccountForm } from './AccountsModule';
import { GroupsList, GroupDetail, GroupForm } from './GroupsModule';
import { AuditList, AuditDetail } from './AuditModule';
import { UsersList, UserDetail, UserForm } from './UsersModule';
import { downloadAuditExport, trackedExportIds } from '../shared/auditExports';
import type { TrackedExport } from '../shared/auditExports';
import { MeasurementFileHistory, MeasurementFilePicker, MeasurementUploadDialog, uploadMeasurementFiles } from './MeasurementFiles';
import type { PendingMeasurementFile } from './MeasurementFiles';
import { LoadActionSelector, loadOptionDefinitions } from './LoadActionSelector';

const previewRequested = new URLSearchParams(window.location.search).get('preview') === '1';
const previewMode = import.meta.env.DEV && previewRequested;
const clientDateTime = new Intl.DateTimeFormat('es-CO', { day: '2-digit', month: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'America/Bogota' });
const clientMonths = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
function formatClientDateTime(value: string) {
  const parts = Object.fromEntries(clientDateTime.formatToParts(new Date(value)).map(part => [part.type, part.value]));
  return `${parts.day} ${clientMonths[Number(parts.month) - 1]} ${parts.year}, ${parts.hour}:${parts.minute}`;
}
function toLocalDateTimeInput(value: Date) {
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}
function defaultMeltwaterWindow() {
  const start = new Date();
  const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
  return { start: toLocalDateTimeInput(start), end: toLocalDateTimeInput(end) };
}
function clientError(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'El servidor no pudo completar la operación. Inténtalo de nuevo.';
    if (error.status === 401) return 'La sesión venció. Ingresa de nuevo.';
    if (error.status === 403) return 'No tienes permiso para realizar esta acción.';
    return typeof error.message === 'string' && error.message !== '[object Object]' ? error.message : fallback;
  }
  return fallback;
}

function postLoginPath(state: unknown): string {
  if (!state || typeof state !== 'object' || !('from' in state)) return '/';
  const from = state.from;
  if (typeof from !== 'string' || !from.startsWith('/') || from.startsWith('//') || from.includes('\\')) return '/';
  return from.split(/[?#]/)[0] === '/acceso' ? '/' : from;
}

function AccessPage() {
  const toast = useToast();
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setNotice('');
    try {
      await loginApi(String(data.get('email') || ''), String(data.get('password') || ''), data.get('recordarme') === 'on');
      navigate(postLoginPath(location.state), { replace: true });
    } catch (error) {
      const message = error instanceof ApiError && error.status === 401
        ? error.message : clientError(error, 'No se pudo conectar con el servidor.');
      setNotice(message);
      toast('No se pudo iniciar sesión', message, 'err');
    } finally { setBusy(false); }
  }
  return (
    <main className="login-page">
      <section className="login-brand-panel">
        <div className="login-brand"><Brand inverse /></div>
        <div className="login-brand-copy">
          <h1>Convierte la conversación social en <span>decisiones</span>.</h1>
          <p>Mediciones, clusters con IA, sentimiento, detección de bots e informes ejecutivos en una sola plataforma.</p>
        </div>
        <div className="brand-claims" aria-label="Información institucional">
          <div><strong>6</strong><span>redes y medios monitoreados</span></div>
          <div><strong>&lt; 15 min</strong><span>SLA por ejecución</span></div>
          <div><strong>100%</strong><span>trazabilidad auditada</span></div>
        </div>
        <svg className="login-wave" viewBox="0 0 800 220" preserveAspectRatio="none" aria-hidden="true">
          <defs><linearGradient id="login-wave-gradient" x1="0" x2="1"><stop offset="0" stopColor="#04B8FB" /><stop offset=".35" stopColor="#1293F8" /><stop offset=".7" stopColor="#3655D2" /><stop offset="1" stopColor="#7850EE" /></linearGradient></defs>
          {[0, 1, 2, 3].map((index) => <path key={index} d={`M0 ${150 - index * 18} C 160 ${90 - index * 20}, 300 ${200 - index * 10}, 460 ${130 - index * 16} S 720 ${80 - index * 8}, 800 ${120 - index * 14}`} stroke="url(#login-wave-gradient)" strokeWidth={2 - index * 0.3} fill="none" opacity={1 - index * 0.2} />)}
        </svg>
      </section>
      <section className="login-form-panel">
        <form className="login-card" onSubmit={submit}>
          <img className="login-symbol" src="/brand/symbol.png" alt="" />
          <h2>Bienvenido de nuevo</h2>
          <p className="muted">Ingresa con tu cuenta corporativa de Syntra.</p>
          <div className="stack">
            <div className="field"><label htmlFor="email">Correo electrónico</label><input id="email" name="email" type="email" autoComplete="username" placeholder="Correo electrónico" /></div>
            <div className="field"><label htmlFor="password">Contraseña</label><input id="password" name="password" type="password" autoComplete="current-password" placeholder="Contraseña" /></div>
          </div>
          <div className="login-options"><label className="remember"><input type="checkbox" name="recordarme" /> Recordarme</label></div>
          <button className="button primary full" type="submit" disabled={busy}>Ingresar <Icon name="arrow" size={16} /></button>
          <p className={`implementation-note${notice ? ' error' : ''}`} role="status">{notice}</p>
        </form>
      </section>
    </main>
  );
}

type HeadingAction = { label: string; path?: string; icon?: string; onClick?: () => void; disabled?: boolean; className?: string };
function PageHeading({ title, description, action }: { title: string; description?: string; action?: string | HeadingAction }) {
  const content = typeof action === 'string' ? action : <>{action?.icon && <Icon name={action.icon} size={16} />}{action?.label}</>;
  const className = `button primary heading-action${typeof action === 'object' && action?.className ? ` ${action.className}` : ''}`;
  return <div className="page-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{typeof action === 'string' ? <button className={className} disabled>{action}</button> : action && (action.path ? <Link className={className} to={`${action.path}${previewMode ? '?preview=1' : ''}`}>{content}</Link> : <button className={className} type="button" disabled={action.disabled} onClick={action.onClick}>{content}</button>)}</div>;
}

function HomePage({ onOpenSearch }: { onOpenSearch: () => void }) {
  const route = (path: string) => `${path}${previewMode ? '?preview=1' : ''}`;
  const metrics = [
    { title: 'Registros cargados', icon: 'upload', detail: 'Nuevos en 24 h · duplicados omitidos' },
    { title: 'Por fiscalizar', icon: 'alert', detail: 'Descartados por relevancia' },
    { title: 'Incorporados', icon: 'check', detail: 'Metadata actualizada · transcritos' },
    { title: 'En tableros', icon: 'grid', detail: 'Pendientes de análisis · publicación' },
    { title: 'SLA < 15 min', icon: 'clock', detail: 'Ejecuciones · últimas 24 h' },
  ];
  return <>
    <section className="welcome-band"><div className="welcome-copy"><p className="eyebrow">SYNTRA · ESCUCHA SOCIAL</p><h1>Inicio</h1><p>Resumen de actividad y seguimiento de mediciones.</p></div><div className="welcome-actions"><Link className="button primary" to={route('/mediciones/nueva')}><Icon name="plus" size={16} /> Nueva medición</Link><Link className="button" to={route('/mediciones')}><Icon name="pulse" size={16} /> Mediciones</Link><Link className="button" to={route('/procesos')}><Icon name="cycle" size={16} /> Procesos</Link><button className="button" type="button" onClick={onOpenSearch}><Icon name="search" size={16} /> Buscar <kbd>Ctrl K</kbd></button></div></section>
    <div className="metric-grid">{metrics.map(({ title, icon, detail }) => <section className="panel metric-card" key={title}><span>{title}</span><strong>—</strong><small>{detail}</small><i><Icon name={icon} size={18} /></i></section>)}</div>
    <div className="dashboard-grid"><section className="panel"><header className="panel-heading"><h2>Conversación publicada · últimas 3 semanas</h2><span className="panel-sub">neto —</span><div className="chart-legend"><span><i className="legend-dot" style={{ background: 'var(--syntra-blue)' }} /> Positivo</span><span><i className="legend-dot" style={{ background: '#A6B1C4' }} /> Neutral</span><span><i className="legend-dot" style={{ background: '#E5484D' }} /> Negativo</span></div></header><div className="chart-placeholder"><EmptyState title="Sin datos para el periodo" detail="La gráfica aparecerá cuando haya registros publicados." /></div></section><section className="panel"><header className="panel-heading"><h2>Cargado por fuente</h2><span className="panel-sub">quién incorporó</span></header><EmptyState title="Sin datos para mostrar" detail="Las fuentes aparecerán cuando haya cargas registradas." /></section></div>
    <div className="dashboard-grid"><section className="panel"><header className="panel-heading"><h2>Procesos recientes</h2><span className="panel-sub">en vivo</span><Link className="button small" to={route('/procesos')}>Ver monitor</Link></header><EmptyState title="Sin procesos recientes" detail="Las cargas, fiscalizaciones y procesamientos aparecerán aquí." /></section><div className="dashboard-stack"><section className="panel"><header className="panel-heading"><h2>Pendientes por medición</h2></header><EmptyState title="Sin información disponible" detail="Los pendientes aparecerán cuando existan mediciones y procesos." /></section><section className="panel"><header className="panel-heading"><h2>Actividad reciente</h2><Link className="button small" to={route('/auditoria')}>Auditoría</Link></header><EmptyState title="Sin actividad reciente" detail="Los cambios realizados en la plataforma aparecerán aquí." /></section></div></div>
  </>;
}

const MEASUREMENT_DESCRIPTION = 'El corazón de Syntra: cada medición carga datos de varias fuentes, los fiscaliza, los enriquece, los analiza con IA y publica su tablero e informes.';
const SOURCE_LABELS: Record<string, string> = {
  archivo: 'Archivos (Excel)', meltwater: 'API Meltwater', scraper: 'Scrapers',
  googlenews: 'Google News', manual: 'Manual',
};
const SOURCE_FILTERS = Object.entries(SOURCE_LABELS);
const MEASUREMENT_STATES = [['vig', 'Vigentes'], ['act', 'Activas'], ['ina', 'Borradores / inactivas'], ['del', 'Eliminadas']];

function MeasurementSources({ sources }: { sources: string[] }) {
  return sources.length
    ? <div className="measurement-source-badges">{sources.map(source => <span className="badge outline" key={source}>{SOURCE_LABELS[source] || source}</span>)}</div>
    : <span className="muted">Sin fuentes activas</span>;
}

function MeasurementCard({ measurement, onOpen }: { measurement: any; onOpen: () => void }) {
  return <article className="measurement-card" role="link" tabIndex={0} aria-label={`Abrir medición ${measurement.nombre}`}
    onClick={onOpen} onKeyDown={event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen(); }
    }}>
    <div className="measurement-card-top"><span className="eyebrow">Medición</span><StateBadge state={measurement.estado_id} /></div>
    <h2>{measurement.nombre}</h2>
    <p className="measurement-card-account">{measurement.cuenta_nombre || 'Cuenta no disponible'}</p>
    <div className="measurement-card-row"><span>Coyuntura</span><strong>{measurement.coyuntura ? 'Sí' : 'No'}</strong></div>
    <div className="measurement-card-sources"><span className="measurement-card-label">Fuentes activas</span><MeasurementSources sources={measurement.fuentes || []} /></div>
    <div className="measurement-card-footer"><span>Preparación: {measurement.preparacion_estado || '—'}</span>
      <span>{measurement.creado_en ? formatClientDateTime(measurement.creado_en) : '—'}</span></div>
  </article>;
}

function MeasurementsPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [client, setClient] = useState('');
  const [source, setSource] = useState('');
  const [onlyCurrent, setOnlyCurrent] = useState(false);
  const [state, setState] = useState('vig');
  const [view, setView] = useState<'cards' | 'list'>('cards');
  const [measurements, setMeasurements] = useState<any[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [clients, setClients] = useState<any[]>([]);
  const statusParam = state === 'act' ? 'activos' : state === 'ina' ? 'inactivos' : state === 'del' ? 'eliminados' : 'vigentes';
  const loadPage = async (cursor?: string, append = false) => {
    if (append) setLoadingMore(true); else setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ limite: '25', estado: statusParam });
      if (query.trim()) params.set('q', query.trim());
      if (client) params.set('cliente_id', client);
      if (onlyCurrent) params.set('coyuntura', 'true');
      if (source) params.set('fuente', source);
      if (cursor) params.set('cursor', cursor);
      const response = await api(`/mediciones?${params}`);
      const body = await response.json();
      const items = Array.isArray(body) ? body : (body.items || []);
      setMeasurements(current => append ? [...current, ...items] : items);
      setNextCursor(body.siguiente || response.headers.get('X-Next-Cursor'));
    } catch (cause) {
      setError(clientError(cause, 'No se pudieron cargar las mediciones.'));
    } finally { setLoading(false); setLoadingMore(false); }
  };
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setMeasurements([]); setNextCursor(null);
    const params = new URLSearchParams({ limite: '25', estado: state === 'act' ? 'activos' : state === 'ina' ? 'inactivos' : state === 'del' ? 'eliminados' : 'vigentes' });
    if (query.trim()) params.set('q', query.trim());
    if (client) params.set('cliente_id', client);
    if (onlyCurrent) params.set('coyuntura', 'true');
    if (source) params.set('fuente', source);
    api(`/mediciones?${params}`).then(async response => ({ response, body: await response.json() }))
      .then(({ response, body }) => {
        if (!active) return;
        setMeasurements(Array.isArray(body) ? body : (body.items || []));
        setNextCursor(body.siguiente || response.headers.get('X-Next-Cursor'));
      })
      .catch(cause => { if (active) setError(clientError(cause, 'No se pudieron cargar las mediciones.')); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [query, client, source, onlyCurrent, state]);
  useEffect(() => {
    let active = true;
    api('/clientes?estado=activos&limite=200').then(response => response.json()).then(body => {
      if (active) setClients(Array.isArray(body) ? body : (body.items || []));
    }).catch(() => { if (active) setClients([]); });
    return () => { active = false; };
  }, []);
  return <>
    <PageHeading title="Mediciones" description={MEASUREMENT_DESCRIPTION} action={{ label: 'Nueva medición', path: '/mediciones/nueva', icon: 'plus' }} />
    <section className="panel module-toolbar measurement-filters" aria-label="Filtros de mediciones">
      <label className="search-field"><Icon name="search" size={17} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar medición o cuenta…" aria-label="Buscar mediciones" /></label>
      <select value={client} onChange={event => setClient(event.target.value)} aria-label="Cliente"><option value="">Cliente: todos</option>{clients.map(item => <option key={item.id} value={item.id}>{item.nombre}</option>)}</select>
      <select value={source} onChange={event => setSource(event.target.value)} aria-label="Fuente"><option value="">Fuente: todas</option>{SOURCE_FILTERS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
      <button className={`chip${onlyCurrent ? ' on' : ''}`} type="button" aria-pressed={onlyCurrent} onClick={() => setOnlyCurrent(value => !value)}><Icon name="zap" size={14} /> Solo coyuntura</button>
      <div className="seg status-segment" role="group" aria-label="Estado de mediciones">{MEASUREMENT_STATES.map(([key, label]) => <button type="button" key={key} className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}<span className="n">—</span></button>)}</div>
      <div className="seg view-segment" role="group" aria-label="Vista de mediciones"><button type="button" className={view === 'cards' ? 'on' : ''} aria-label="Vista de tarjetas" aria-pressed={view === 'cards'} onClick={() => setView('cards')}><Icon name="grid" size={15} /></button><button type="button" className={view === 'list' ? 'on' : ''} aria-label="Vista de lista" aria-pressed={view === 'list'} onClick={() => setView('list')}><Icon name="menu" size={15} /></button></div>
    </section>
    <section className={`measurement-results ${view === 'list' ? 'list-view' : 'cards-view'}`} aria-live="polite">
      {error && <p className="control-notice error" role="alert">{error}</p>}
      {loading ? <EmptyState title="Cargando mediciones…" /> : measurements.length === 0
        ? <EmptyState title={query || client || source || onlyCurrent || state !== 'vig' ? 'No hay mediciones para estos filtros' : 'Aún no hay mediciones'} detail="Las mediciones aparecerán cuando haya datos disponibles." />
        : view === 'cards'
          ? <div className="measurement-card-grid">{measurements.map(item => <MeasurementCard key={item.id} measurement={item}
              onOpen={() => navigate(`/mediciones/${item.id}${previewMode ? '?preview=1' : ''}`)} />)}</div>
          : <div className="panel measurement-list-panel"><div className="table-scroll"><table className="measurement-static-table"><thead><tr><th>Medición</th><th>Fuentes</th><th className="num">Registros</th><th className="num">Por fiscalizar</th><th className="num">En tablero</th><th>Sentimiento</th><th>Estado</th><th>Actualizado</th></tr></thead><tbody>{measurements.map(item => <tr key={item.id} className="measurement-selectable-row" tabIndex={0}
              aria-label={`Abrir medición ${item.nombre}`} onClick={() => navigate(`/mediciones/${item.id}${previewMode ? '?preview=1' : ''}`)}
              onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); navigate(`/mediciones/${item.id}${previewMode ? '?preview=1' : ''}`); } }}>
              <td><strong>{item.nombre}</strong><small className="measurement-table-account">{item.cuenta_nombre || '—'}</small></td>
              <td><MeasurementSources sources={item.fuentes || []} /></td><td className="num" title="Métrica no disponible en la API">—</td>
              <td className="num" title="Métrica no disponible en la API">—</td><td className="num" title="Métrica no disponible en la API">—</td>
              <td><span className="muted" title="Sentimiento agregado no disponible en la API">—</span></td><td><StateBadge state={item.estado_id} /></td>
              <td>{item.actualizado_en ? formatClientDateTime(item.actualizado_en) : item.creado_en ? formatClientDateTime(item.creado_en) : '—'}</td></tr>)}</tbody></table></div></div>}
      {nextCursor && !loading && <div className="load-more-row"><button className="button" type="button" disabled={loadingMore} onClick={() => void loadPage(nextCursor, true)}>{loadingMore ? 'Cargando…' : 'Cargar más'}</button></div>}
    </section>
  </>;
}

const PROCESS_DESCRIPTION = 'Los indicadores y la tabla superiores están reservados al módulo de mediciones. El seguimiento operativo disponible al final corresponde al envío de correos y a las exportaciones de Auditoría.';
const MEASUREMENT_PROCESS_TYPES = [['preparar_medicion', 'Preparación de medición'], ['carga', 'Carga de datos'], ['fiscalizacion_ia', 'Fiscalización con IA'], ['incorporacion', 'Incorporación'], ['actualizacion_masiva', 'Actualización masiva (Excel)'], ['metadata', 'Actualización de metadata'], ['transcripcion', 'Transcripción audio/video'], ['analisis', 'Análisis IA'], ['reaplicar_regex', 'Reaplicación de regex y cruces'], ['publicacion', 'Actualización del tablero']];
const MEASUREMENT_PROCESS_STATES = [['en_cola', 'En cola'], ['en_ejecucion', 'En ejecución'], ['completado', 'Completado'], ['advertencia', 'Con advertencias'], ['error', 'Error'], ['cancelado', 'Cancelado']];
type QueueStatus = { cola: string; en_cola: number; en_ejecucion: number; con_error: number; mas_antigua_s: number; workers: number };
type WorkerStatus = { id: string; servidor: string; colas: string[]; iniciado_en: string; latido: string; tareas_en_curso: number; vivo: boolean };
type MonitoredProcess = { id: number; tipo: string; estado: string; progreso: number; total: number; procesados: number; ok: number; errores: number; creado_en: string; iniciado_en: string | null; finalizado_en: string | null; duracion_ms: number | null; sla_ms: number | null };
type MonitoredTask = { id: number; clave: string; tipo: string; estado: string; intentos: number; ok: number; errores: number; error_codigo: string | null; error_mensaje: string; iniciado_en: string | null; finalizado_en: string | null };
const processLabels: Record<string, string> = { correo_acceso: 'Envío de correo', exportacion: 'Exportación de Auditoría', preparar_medicion: 'Preparación de medición' };
const processStateLabels: Record<string, string> = { en_cola: 'En cola', en_ejecucion: 'En ejecución', completado: 'Completado', advertencia: 'Con advertencias', error: 'Error', cancelado: 'Cancelado' };
function processDate(value: string | null) { return value ? new Date(value).toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Bogota' }) : '—'; }
function processDuration(value: number | null) {
  if (value == null) return '—';
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`;
  if (value < 3_600_000) return `${(value / 60_000).toFixed(1)} min`;
  return `${(value / 3_600_000).toFixed(1)} h`;
}
function ProcessStateBadge({ state }: { state: string }) {
  const tone = state === 'completado' ? 'ok' : state === 'error' || state === 'cancelado' ? 'err' : state === 'advertencia' ? 'warn' : 'info';
  return <span className={`badge ${tone}`}><span className="d" aria-hidden="true" />{processStateLabels[state] || 'Desconocido'}</span>;
}
function ProcessesPage({ yo }: { yo: Yo | null }) {
  const [measurementState, setMeasurementState] = useState('');
  const [measurementType, setMeasurementType] = useState('');
  const [measurementMode, setMeasurementMode] = useState('');
  const [measurementId, setMeasurementId] = useState('');
  const [queues, setQueues] = useState<QueueStatus[]>([]);
  const [workers, setWorkers] = useState<WorkerStatus[]>([]);
  const [processPages, setProcessPages] = useState<MonitoredProcess[][]>([]);
  const [processCursors, setProcessCursors] = useState<(string | null)[]>([]);
  const processCursorsRef = useRef<(string | null)[]>([]);
  const [pageIndex, setPageIndex] = useState(0);
  const pageIndexRef = useRef(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const monitorRequestGeneration = useRef(0);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [tasks, setTasks] = useState<Record<number, MonitoredTask[]>>({});
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const canViewProcesses = Boolean(yo?.permisos.procesos?.includes('ver'));
  const canViewAudit = Boolean(yo?.permisos.auditoria?.includes('ver'));
  async function refresh(targetPage = pageIndex) {
    if (!canViewProcesses) { setLoading(false); return; }
    try {
      const [queuesResponse, workersResponse] = await Promise.all([api('/ops/colas'), api('/ops/workers')]);
      setQueues(await queuesResponse.json() as QueueStatus[]);
      const currentWorkers = await workersResponse.json() as WorkerStatus[];
      setWorkers(currentWorkers);
      const pageSize = targetPage === 0 ? Math.max(1, 25 - currentWorkers.length) : 25;
      const cursor = targetPage > 0 ? processCursorsRef.current[targetPage - 1] ?? null : null;
      const params = new URLSearchParams({ limite: String(pageSize) });
      if (cursor) params.set('cursor', cursor);
      const processesResponse = await api(`/procesos?${params}`);
      const currentProcesses = await processesResponse.json() as MonitoredProcess[];
      const nextCursor = processesResponse.headers.get('X-Next-Cursor');
      processCursorsRef.current[targetPage] = nextCursor;
      setProcessCursors(current => { const updated = [...current]; updated[targetPage] = nextCursor; return updated; });
      setProcessPages(current => { const updated = [...current]; updated[targetPage] = currentProcesses; return updated; });
      setNotice(''); setLastUpdated(new Date().toISOString());
    } catch (error) { setNotice(clientError(error, 'No se pudo consultar el estado del monitor.')); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    setLoading(true);
    monitorRequestGeneration.current += 1;
    processCursorsRef.current = [];
    setProcessCursors([]);
    setProcessPages([]);
    pageIndexRef.current = 0;
    setPageIndex(0);
    if (!canViewProcesses) return;
    void refresh(0);
    const timer = window.setInterval(() => void refresh(pageIndexRef.current), 5000);
    return () => window.clearInterval(timer);
  }, [canViewProcesses]);
  function goToPage(targetPage: number) {
    pageIndexRef.current = targetPage;
    setPageIndex(targetPage);
  }
  async function loadMore() {
    if (loadingMore) return;
    if (processPages[pageIndex + 1]) { goToPage(pageIndex + 1); return; }
    const cursor = processCursorsRef.current[pageIndex];
    if (!cursor) return;
    const generation = monitorRequestGeneration.current;
    setLoadingMore(true);
    try {
      const params = new URLSearchParams({ limite: '25', cursor });
      const response = await api(`/procesos?${params}`);
      const nextRows = await response.json() as MonitoredProcess[];
      if (generation === monitorRequestGeneration.current) {
        setProcessPages(current => [...current.slice(0, pageIndex + 1), nextRows]);
        const nextCursor = response.headers.get('X-Next-Cursor');
        processCursorsRef.current[pageIndex + 1] = nextCursor;
        setProcessCursors(current => { const updated = [...current]; updated[pageIndex + 1] = nextCursor; return updated; });
        goToPage(pageIndex + 1);
      }
    } catch (error) { setNotice(clientError(error, 'No se pudieron cargar más procesos.')); }
    finally { setLoadingMore(false); }
  }
  async function toggleTasks(process: MonitoredProcess) {
    if (expanded === process.id) { setExpanded(null); return; }
    setExpanded(process.id);
    if (tasks[process.id]) return;
    try {
      const response = await api(`/procesos/${process.id}/tareas`);
      const rows = await response.json() as MonitoredTask[];
      setTasks(previous => ({ ...previous, [process.id]: rows }));
    } catch (error) { setNotice(clientError(error, 'No se pudieron consultar las tareas de este proceso.')); }
  }
  async function download(process: MonitoredProcess) {
    try { await downloadAuditExport(process.id); }
    catch (error) { toast('No se pudo descargar', clientError(error, 'El archivo no está disponible.'), 'err'); }
  }
  const toast = useToast();
  const queueLabel: Record<string, string> = { 'q.notificaciones': 'Envío de correos', 'q.reportes': 'Exportaciones de Auditoría', 'q.ingesta': 'Ingesta de archivos' };
  const processes = processPages[pageIndex] || [];
  const pageWorkers = pageIndex === 0 ? workers : [];
  const nextAvailable = Boolean(processPages[pageIndex + 1] || processCursors[pageIndex]);
  if (yo && !canViewProcesses) return <><PageHeading title="Monitor de procesos" description={PROCESS_DESCRIPTION} /><section className="panel"><EmptyState title="Sin permiso para consultar procesos" detail="Necesitas procesos:ver para acceder al monitor." /></section></>;
  return <>
    <PageHeading title="Monitor de procesos" description={PROCESS_DESCRIPTION} />
    {notice && <p className="form-notice error" role="alert">{notice}</p>}
    <section className="process-summary-grid" aria-label="Resumen de procesos de medición">
      <article className="panel process-summary hero"><div><span className="summary-title"><Icon name="cycle" size={14} /> En ejecución o en cola</span><strong>—</strong><small>Indicador de mediciones · aún sin datos</small></div><i><Icon name="cycle" size={18} /></i></article>
      <article className="panel process-summary green"><div><span className="summary-title">Completados (24 h)</span><strong>—</strong><small>Registros procesados: —</small></div><i><Icon name="check" size={18} /></i></article>
      <article className="panel process-summary red"><div><span className="summary-title">Con error o advertencia (7 d)</span><strong>—</strong><small>Indicador de mediciones · aún sin datos</small></div><i><Icon name="alert" size={18} /></i></article>
      <article className="panel process-summary violet"><div><span className="summary-title">Duración promedio</span><strong>—</strong><small>Máximo y SLA: —</small></div><i><Icon name="clock" size={18} /></i></article>
    </section>
    <section className="panel process-chart"><header className="panel-heading"><div><h2>Duración de las últimas ejecuciones</h2><span className="panel-sub">minutos · línea roja = SLA</span></div><div className="chart-legend"><span><i className="legend-dot" style={{ background: 'var(--syntra-blue)' }} />Cargas</span><span><i className="legend-dot" style={{ background: 'var(--syntra-violet)' }} />Fiscalización y procesamiento</span></div></header><div className="process-chart-body"><div className="process-duration-chart-wrap"><svg className="process-duration-chart" viewBox="0 0 900 210" role="img" aria-label="Gráfica de duración de ejecuciones de medición, sin datos todavía">{[20, 94, 168].map(y => <line key={y} x1="0" x2="900" y1={y} y2={y} className="process-chart-gridline" />)}<text x="0" y="16" className="process-chart-axis">15 min</text><text x="0" y="90" className="process-chart-axis">7,5 min</text><text x="0" y="164" className="process-chart-axis">0 min</text><line x1="0" x2="900" y1="20" y2="20" className="process-chart-sla" /></svg><p className="process-chart-empty">Sin mediciones disponibles. La gráfica mostrará ejecuciones reales cuando exista información del módulo de mediciones.</p></div></div></section>
    <section className="panel process-table-panel"><div className="module-toolbar process-filters" aria-label="Filtros de procesos de medición"><select aria-label="Estado" value={measurementState} onChange={event => setMeasurementState(event.target.value)}><option value="">Estado: todos</option>{MEASUREMENT_PROCESS_STATES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label="Tipo" value={measurementType} onChange={event => setMeasurementType(event.target.value)}><option value="">Tipo: todos</option>{MEASUREMENT_PROCESS_TYPES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label="Modo" value={measurementMode} onChange={event => setMeasurementMode(event.target.value)}><option value="">Modo: todos</option><option value="manual">Manual</option><option value="automatico">Automático</option></select><select aria-label="Medición" value={measurementId} onChange={event => setMeasurementId(event.target.value)}><option value="">Medición: todas</option></select><span className="filter-count">0 procesos</span></div>
      <div className="table-wrap"><table className="data-table process-data-table"><thead><tr>{['ID', 'Medición', 'Tipo', 'Modo', 'Estado', 'Progreso', 'Inicio', 'Duración / SLA', 'Registros'].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody><tr><td colSpan={9} className="empty-cell"><EmptyState title="Sin procesos" detail="Las cargas, fiscalizaciones y procesamientos aparecerán aquí cuando el módulo de mediciones tenga datos disponibles." /></td></tr></tbody></table></div>
      <div className="table-pager"><span>Página 1 de 1</span><div><button type="button" aria-label="Anterior" disabled><Icon name="chevron_left" size={16} /></button><button type="button" aria-label="Siguiente" disabled><Icon name="chevron" size={16} /></button></div></div>
    </section>
    <section className="panel process-workers-panel"><header className="panel-heading"><div><h2>Estado de workers y colas</h2><span className="panel-sub">Correo, exportaciones de Auditoría e ingesta de archivos</span></div><span className="panel-sub">{lastUpdated ? `Actualizado ${processDate(lastUpdated)}` : 'Sin actualización'}</span></header>
      {loading && !lastUpdated ? <div className="process-live-state" role="status">Consultando estado…</div> : !queues.length && !workers.length ? <div className="process-live-state"><EmptyState title="Sin información disponible" detail="No hay registros de workers para las colas incluidas en este monitor." /></div> : <div className="process-queue-grid">{queues.map(queue => <article className="process-queue-card" key={queue.cola}><div className="process-queue-title"><h3>{queueLabel[queue.cola] || queue.cola}</h3><span className={`badge ${queue.workers ? 'ok' : 'warn'}`}><span className="d" aria-hidden="true" />{queue.workers ? `${queue.workers} worker${queue.workers === 1 ? '' : 's'} con latido reciente` : 'Sin worker con latido reciente'}</span></div><dl><div><dt>En cola</dt><dd>{queue.en_cola}</dd></div><div><dt>En ejecución</dt><dd>{queue.en_ejecucion}</dd></div><div><dt>Con error</dt><dd>{queue.con_error}</dd></div><div><dt>Antigüedad de cola lista</dt><dd>{queue.mas_antigua_s}s</dd></div></dl></article>)}</div>}
      <div className="table-wrap process-workers-table-wrap"><table className="data-table process-workers-table"><thead><tr><th>ID</th><th>Worker o proceso</th><th>Cola</th><th>Estado</th><th>Última actividad</th><th>Tareas / avance</th><th>Acciones</th></tr></thead><tbody>
        {pageWorkers.map(worker => <tr key={`worker-${worker.id}`}><td className="process-id-cell">{worker.id}</td><td><strong>{worker.servidor}</strong><small className="process-row-kind">Worker</small></td><td>{worker.colas.map(queue => queueLabel[queue] || queue).join(', ')}</td><td><span className={`badge ${worker.vivo ? 'ok' : 'warn'}`}><span className="d" aria-hidden="true" />{worker.vivo ? 'Reciente' : 'Vencido'}</span></td><td>{processDate(worker.latido)}</td><td>{worker.tareas_en_curso} en curso</td><td>—</td></tr>)}
        {processes.map(process => <Fragment key={`process-${process.id}`}><tr><td className="process-id-cell">Proceso #{process.id}</td><td><strong>{processLabels[process.tipo] || process.tipo}</strong><small className="process-row-kind">Proceso operativo</small></td><td>{process.tipo === 'correo_acceso' ? queueLabel['q.notificaciones'] : queueLabel['q.reportes']}</td><td><ProcessStateBadge state={process.estado} /></td><td>{processDate(process.finalizado_en || process.iniciado_en || process.creado_en)}</td><td>{process.tipo === 'exportacion' ? `${process.errores} error${process.errores === 1 ? '' : 'es'} · ${processDuration(process.duracion_ms)}` : `${process.progreso}% · ${process.errores} errores`}</td><td><div className="process-row-actions"><button className="icon-button process-action-button" type="button" aria-label={`Ver tarea del proceso #${process.id}`} title={`Ver tarea del proceso #${process.id}`} aria-expanded={expanded === process.id} onClick={() => void toggleTasks(process)}><Icon name="eye" size={17} /></button>{process.tipo === 'exportacion' && <button className="icon-button process-action-button" type="button" aria-label={`Descargar XLSX de exportación #${process.id}`} title={process.estado === 'completado' && canViewAudit ? `Descargar XLSX de exportación #${process.id}` : 'Descarga no disponible: exportación no completada o sin permiso'} disabled={process.estado !== 'completado' || !canViewAudit} onClick={() => void download(process)}><Icon name="download" size={16} /></button>}</div></td></tr>{expanded === process.id && <tr className="process-task-detail"><td colSpan={7}><div className="process-task-context">Tareas del proceso #{process.id} · El identificador del proceso no es el identificador de cada tarea.</div>{tasks[process.id] ? tasks[process.id].length ? <div className="process-task-list">{tasks[process.id].map(task => <article key={task.id}><div><strong>Tarea #{task.id} · {task.clave}</strong><ProcessStateBadge state={task.estado} /></div><span>{task.intentos} intento{task.intentos === 1 ? '' : 's'} · {task.errores} error{task.errores === 1 ? '' : 'es'}</span>{task.error_codigo && <p role="status"><strong>{task.error_codigo}:</strong> {task.error_mensaje}</p>}</article>)}</div> : <p className="process-task-empty">No hay tareas registradas para este proceso.</p> : <span className="process-task-loading" role="status">Cargando tareas…</span>}</td></tr>}</Fragment>)}
        {!pageWorkers.length && !processes.length && <tr><td colSpan={7} className="empty-cell"><EmptyState title="Sin información disponible" detail="No hay registros de workers ni procesos operativos en los últimos 7 días." /></td></tr>}
      </tbody></table><div className="table-pager"><span>{pageWorkers.length + processes.length} registros</span><div className="table-pager-actions"><button type="button" title="Página anterior" aria-label="Página anterior" disabled={loading || loadingMore || pageIndex === 0} onClick={() => goToPage(pageIndex - 1)}><Icon name="chevron_left" size={16} /></button><span className="table-pager-current">{pageIndex + 1}</span><button type="button" title="Página siguiente" aria-label="Página siguiente" disabled={loading || loadingMore || !nextAvailable} onClick={() => void loadMore()}><Icon name="chevron" size={16} /></button></div></div></div>
      <p className="process-monitor-note">El estado se deriva del último latido (umbral contractual: 45 s). No confirma por sí solo que el proceso del sistema operativo siga activo.</p>
    </section>
  </>;
}

const measurementSteps = [
  ['General', 'Cuenta y nombre'], ['Fuentes de datos', 'Archivos, Meltwater y manual'], ['Scrapers', 'Redes sociales y Google News'], ['Prompts', 'General y por red'], ['Clusters', 'Parámetros y cruces'], ['Bots y X', 'Detección y parámetros'], ['Regex y ventana', 'Orden y preclustering'], ['Revisión', 'Confirmar'],
];
const defaultMeasurementDescription = 'Configura en 8 pasos qué escuchar, cómo se incorporan los datos, cómo analizarlos y desde cuándo. Puedes guardar como borrador en cualquier momento.';
const promptKinds = ['Clusters', 'Temas finales', 'Relevancia', 'Sentimiento'];
const promptTypeByLabel: Record<string, string> = { 'Clusters': 'cluster', 'Temas finales': 'temas', 'Relevancia': 'relevancia', 'Sentimiento': 'sentimiento' };
const modulesForPermissions = [['dashboard', 'Inicio'], ['clientes', 'Clientes'], ['cuentas', 'Cuentas'], ['usuarios', 'Usuarios'], ['roles', 'Roles y accesos'], ['grupos', 'Grupos de usuarios'], ['prompts', 'Prompts por defecto'], ['regex', 'Regex'], ['paises', 'Países (Google News)'], ['mediciones', 'Mediciones'], ['fiscalizacion', 'Fiscalización'], ['registros', 'Registros'], ['procesos', 'Procesos'], ['informes', 'Informes'], ['auditoria', 'Auditoría']];
const permissionActions = [['ver', 'Ver'], ['crear', 'Crear'], ['editar', 'Editar'], ['eliminar', 'Eliminar'], ['ejecutar', 'Ejecutar'], ['exportar', 'Exportar']];

const defaultLoadOptions = { incorporar: true, relevancia: false, sentimiento: true, clusters: false, bots: false };

function NewMeasurementPage({ yo }: { yo: Yo | null }) {
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [catalogs, setCatalogs] = useState<Record<string, any[]>>({ accounts: [], countries: [], prompts: [], regex: [], actors: [], crosses: [], formats: [] });
  const [catalogNotice, setCatalogNotice] = useState('');
  const [promptVersions, setPromptVersions] = useState<Record<string, any[]>>({});
  const [saving, setSaving] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<PendingMeasurementFile[]>([]);
  const [createdMeasurementId, setCreatedMeasurementId] = useState<number | null>(null);
  const uploadedFileIds = useRef(new Map<File, number>());
  const uploadIdempotencyKey = useRef(crypto.randomUUID());
  const [draft, setDraft] = useState<Record<string, any>>({
    account: '', name: '', coyuntura: '', status: 1, sources: { files: false, meltwater: false, manual: false }, sourceOptions: { archivo: { ...defaultLoadOptions }, meltwater: { ...defaultLoadOptions }, manual: { ...defaultLoadOptions } }, meltwaterId: '', meltwaterSchedule: { active: false, start: '', end: '', frequency: 60, unit: 'h' }, autoPublish: false, scraperOpen: false, scraper: { name: '', start: '', end: '', frequency: 60, networks: {}, google: false, countries: [], googleKeywords: '' }, promptKind: 'Clusters', promptSelections: {}, prompts: {}, clusters: 15, subclusters: 3, analysis: 'temas_sentimiento', crossName: '', crossTerms: '', selectedCrosses: [], bots: true, botOptions: { identify: true, negativeReposts: true, positiveNegative: true }, xAccounts: 50, xMentions: 0, regexSelected: [], precluster: false, window: 'historia', startDate: '',
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState('');
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    let active = true;
    const readItems = async (path: string) => {
      const response = await api(path);
      const body = await response.json();
      return Array.isArray(body) ? body : (body.items || []);
    };
    Promise.allSettled([
      readItems('/cuentas?estado=activos&limite=200'), readItems('/paises?estado=activos&limite=200'),
      readItems('/prompts?estado=activos&limite=200'), readItems('/regex?estado=activos&limite=200'),
      readItems('/actores'), readItems('/cruces'), readItems('/formatos'),
    ]).then(results => {
      if (!active) return;
      const keys = ['accounts', 'countries', 'prompts', 'regex', 'actors', 'crosses', 'formats'];
      const next: Record<string, any[]> = {};
      const failed: string[] = [];
      results.forEach((result, index) => {
        next[keys[index]] = result.status === 'fulfilled' ? result.value : [];
        if (result.status === 'rejected') failed.push(keys[index]);
      });
      setCatalogs(current => ({ ...current, ...next }));
      if (failed.length) setCatalogNotice(`Algunos catálogos no están disponibles (${failed.join(', ')}). No se enviarán valores inventados.`);
    });
    return () => { active = false; };
  }, []);
  const choosePrompt = async (kind: string, rawId: string) => {
    const promptId = Number(rawId);
    set('promptSelections', { ...draft.promptSelections, [kind]: { origin: 'defecto', promptId: rawId, version: '' } });
    if (!promptId) return;
    try {
      const response = await api(`/prompts/${promptId}/versiones`);
      const versions = await response.json();
      setPromptVersions(current => ({ ...current, [String(promptId)]: versions }));
    } catch (error) { setNotice(clientError(error, 'No se pudieron cargar las versiones del prompt.')); }
  };
  const choosePromptVersion = async (kind: string, value: string) => {
    const current = draft.promptSelections[kind] || {};
    set('promptSelections', { ...draft.promptSelections, [kind]: { ...current, version: value } });
    const version = (promptVersions[String(current.promptId)] || []).find((item: any) => String(item.version) === value);
    if (version) set('prompts', { ...draft.prompts, [kind]: version.contenido });
  };
  const selectRegex = (id: number, checked: boolean) => {
    const current: number[] = draft.regexSelected;
    set('regexSelected', checked ? [...current, id] : current.filter(value => value !== id));
  };
  const set = (key: string, value: unknown) => { setDirty(true); setDraft((current) => ({ ...current, [key]: value })); setErrors(current => ({ ...current, [key]: '' })); setNotice(''); };
  const setSource = (key: string, value: boolean) => { setDirty(true); setDraft((current) => {
    const meltwaterSchedule = key === 'meltwater' && value && !current.meltwaterSchedule.start
      ? { ...current.meltwaterSchedule, ...defaultMeltwaterWindow() } : current.meltwaterSchedule;
    return { ...current, sources: { ...current.sources, [key]: value }, meltwaterSchedule };
  }); setErrors(current => ({ ...current, sources: '' })); setNotice(''); };
  const stepErrors = (index: number) => {
    const next: Record<string, string> = {};
    if (index === 0) { if (!draft.account) next.account = 'Selecciona la cuenta'; if (!draft.name.trim()) next.name = 'El nombre es obligatorio'; }
    if (index === 1) { if (!Object.values(draft.sources).some(Boolean)) next.sources = 'Activa al menos una fuente de datos o configura un proceso de scraping'; if (selectedFiles.length && !draft.sources.files) next.files = 'Activa la fuente Archivos para cargar los archivos seleccionados'; if (selectedFiles.length && !yo?.permisos.mediciones?.includes('ejecutar')) next.files = 'Se requiere mediciones:ejecutar para cargar archivos'; if (draft.sources.meltwater && !draft.meltwaterId.trim()) next.meltwaterId = 'Ingresa el ID de búsqueda de Meltwater'; if (draft.sources.meltwater && draft.meltwaterSchedule.active) { const start = new Date(draft.meltwaterSchedule.start); const end = new Date(draft.meltwaterSchedule.end); if (!draft.meltwaterSchedule.start || !draft.meltwaterSchedule.end || Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf()) || end <= start) next.meltwaterSchedule = 'La programación requiere fechas válidas y una fecha final posterior'; if (!(Number(draft.meltwaterSchedule.frequency) >= 15)) next.meltwaterFrequency = 'La frecuencia mínima es de 15 minutos'; if (!yo?.permisos.mediciones?.includes('editar')) next.meltwaterPermission = 'Se requiere mediciones:editar para programar consultas Meltwater'; } }
    if (index === 2 && draft.scraperOpen) {
      if (!draft.scraper.name.trim()) next.scraper = 'Indica un nombre para el proceso de scraping';
      if (!draft.scraper.start || !draft.scraper.end || Number.isNaN(new Date(draft.scraper.start).valueOf()) || Number.isNaN(new Date(draft.scraper.end).valueOf()) || new Date(draft.scraper.end) <= new Date(draft.scraper.start)) next.scraperDates = 'Indica fechas válidas y una fecha final posterior';
      if (!Object.values(draft.scraper.networks).some((item: any) => item?.active) && !draft.scraper.google) next.scraperSource = 'Selecciona una red social o Google News';
      for (const [network, config] of Object.entries(draft.scraper.networks) as [string, any][]) if (config?.active && !String(config.keywords || '').trim()) next[`scraper-${network}`] = `Agrega palabras de búsqueda para ${network}`;
      if (draft.scraper.google && (!draft.scraper.countries.length || !String(draft.scraper.googleKeywords || '').trim())) next.scraperGoogle = 'Google News requiere países activos y palabras de búsqueda';
      if (draft.scraper.frequency < 15) next.scraperFrequency = 'La frecuencia mínima es de 15 minutos';
    }
    if (index === 3) { for (const kind of promptKinds) { const chosen = draft.promptSelections[kind] || {}; if (chosen.origin === 'propio') { if (String(draft.prompts[kind] || '').trim().length < 20) next[`prompt-${kind}`] = `Define el prompt propio de ${kind.toLowerCase()}`; } else if (chosen.origin !== 'cuenta' && (!chosen.promptId || !chosen.version)) next[`prompt-${kind}`] = `Selecciona el prompt y la versión activa de ${kind.toLowerCase()}`; } }
    if (index === 4) { if (!(draft.clusters >= 2 && draft.clusters <= 30)) next.clusters = 'Entre 2 y 30 clusters'; if (!(draft.subclusters >= 1 && draft.subclusters <= 10)) next.subclusters = 'Entre 1 y 10 subclusters'; }
    if (index === 4 && Boolean(draft.crossName.trim()) !== Boolean(String(draft.crossTerms).trim())) next.cross = 'Completa el nombre y al menos una cuenta o hashtag de la lista.';
    if (index === 5) { if (draft.xAccounts < 0) next.xAccounts = 'Indica un número (0 o más)'; if (draft.xMentions < 0) next.xMentions = 'Indica un número (0 = calculado)'; }
    if (index === 6 && draft.precluster && !draft.regexSelected.length) next.regex = 'Selecciona al menos una regex para preclustering';
    if (index === 6 && draft.window === 'desde' && !draft.startDate) next.startDate = 'Selecciona la fecha y hora de inicio';
    return next;
  };
  const goStep = (next: number) => { setStep(Math.max(0, Math.min(measurementSteps.length - 1, next))); setNotice(''); };
  const nextStep = () => { const nextErrors = stepErrors(step); setErrors(current => ({ ...current, ...nextErrors })); if (Object.keys(nextErrors).length) return; goStep(step + 1); };
  const cancel = () => { if (dirty) setConfirmDiscard(true); else navigate(`/mediciones${previewMode ? '?preview=1' : ''}`); };
  const save = async () => {
    const allErrors = measurementSteps.slice(0, 7).flatMap((_, i) => Object.entries(stepErrors(i)).map(([key, value]) => [key, value]));
    setErrors(Object.fromEntries(allErrors));
    if (allErrors.length) { setNotice('Revisa los pasos marcados antes de guardar.'); return; }
    const sources = Object.entries(draft.sources).map(([key, active]) => {
      const origen = ({ files: 'archivo', meltwater: 'meltwater', manual: 'manual' } as Record<string, string>)[key];
      return { origen, activo: active, config: key === 'meltwater' ? { busqueda_id: draft.meltwaterId.trim() } : {},
        al_cargar: draft.sourceOptions[origen] || defaultLoadOptions };
    });
    const prompts = promptKinds.map(kind => {
      const choice = draft.promptSelections[kind] || {};
      if (choice.origin === 'propio') return { tipo: promptTypeByLabel[kind], origen: 'propio', contenido: draft.prompts[kind] };
      if (choice.origin === 'cuenta') return { tipo: promptTypeByLabel[kind], origen: 'cuenta' };
      return { tipo: promptTypeByLabel[kind], origen: choice.origin || 'defecto', prompt_id: Number(choice.promptId), version: Number(choice.version) };
    });
    const scrapers = draft.scraperOpen ? [{
      nombre: draft.scraper.name.trim(), ejecucion_auto: true,
      inicio: new Date(draft.scraper.start).toISOString(), fin: new Date(draft.scraper.end).toISOString(), frecuencia_min: Number(draft.scraper.frequency),
      redes: Object.entries(draft.scraper.networks).filter(([, config]: any) => config?.active).map(([red, config]: any) => ({ red, activo: true, registros: Number(config.records || 100), actor_id: config.actorId ? Number(config.actorId) : null })),
      google_news: { activo: draft.scraper.google, registros: 50, periodo: 'ultimo_dia', pais_ids: draft.scraper.countries.map(Number) },
      palabras: Object.fromEntries(Object.entries(draft.scraper.networks).filter(([, config]: any) => config?.active).map(([red, config]: any) => [red, String(config.keywords || '').split(',').map((word: string) => word.trim()).filter(Boolean)]).concat(draft.scraper.google ? [['googlenews', String(draft.scraper.googleKeywords || '').split(',').map((word: string) => word.trim()).filter(Boolean)]] : [])),
    }] : [];
    const crossItems = String(draft.crossTerms || '').split(',').map(item => item.trim()).filter(Boolean);
    const payload = {
      cuenta_id: Number(draft.account), nombre: draft.name.trim(), coyuntura: draft.coyuntura === 'si', estado_id: draft.status,
      fuentes: sources,
      programacion_meltwater: draft.sources.meltwater && draft.meltwaterSchedule.active ? {
        activa: true, inicio: new Date(draft.meltwaterSchedule.start).toISOString(), fin: new Date(draft.meltwaterSchedule.end).toISOString(), frecuencia_min: Number(draft.meltwaterSchedule.frequency),
      } : { activa: false },
      auto_publicar: draft.autoPublish,
      prompts, instrucciones: draft.instructions || '',
      clusters: { num_clusters: Number(draft.clusters), num_subclusters: Number(draft.subclusters), tipo_analisis: draft.analysis, cruce_ids: draft.selectedCrosses.map(Number) },
      cruces: draft.crossName.trim() && crossItems.length ? [{ nombre: draft.crossName.trim(), modo: 'texto_hashtags', incluye_autor: true, items: crossItems }] : [],
      scrapers,
      bots: { activo: draft.bots, identificar: draft.botOptions.identify, rt_negativos: draft.botOptions.negativeReposts, neg_pos: draft.botOptions.positiveNegative },
      parametros_x: { num_menciones: Number(draft.xMentions), num_cuentas: Number(draft.xAccounts) },
      regex: { regex_ids_ordenados: draft.regexSelected.map(Number), precluster_activo: draft.precluster },
      ventana_desde: draft.window === 'desde' ? new Date(draft.startDate).toISOString() : null,
    };
    setSaving(true); setNotice('');
    let savedId = createdMeasurementId;
    try {
      let measurementId = savedId;
      let preparationId: number | undefined;
      if (measurementId === null) {
        const response = await api('/mediciones', { method: 'POST', body: JSON.stringify(payload) });
        const result = await response.json();
        measurementId = result.id;
        savedId = measurementId;
        preparationId = result.proceso_preparacion_id;
        setCreatedMeasurementId(measurementId);
      }
      if (measurementId === null) throw new Error('La medición no devolvió un identificador');
      if (selectedFiles.length) {
        await uploadMeasurementFiles(measurementId, selectedFiles, draft.sourceOptions.archivo,
                                     uploadedFileIds.current, uploadIdempotencyKey.current);
      }
      setDirty(false);
      navigate(`/mediciones/${measurementId}`, { state: { creationProcessId: preparationId } });
    } catch (error) { setNotice(savedId ? `La medición #${savedId} se guardó. La carga de archivos quedó pendiente: ${clientError(error, 'Intenta nuevamente.')}` : clientError(error, 'No se pudo crear la medición.')); }
    finally { setSaving(false); }
  };
  const saveDraft = () => { const currentErrors = stepErrors(0); setErrors(currentErrors); setNotice(Object.keys(currentErrors).length ? `Completa los datos generales para guardar el borrador: ${Object.values(currentErrors)[0]}.` : 'El guardado de borradores aún no está disponible. La configuración permanece en este formulario.'); };
  const completedSteps = measurementSteps.slice(0, 7).filter((_, index) => Object.keys(stepErrors(index)).length === 0).length;
  const fieldError = (key: string) => errors[key] && <span className="field-error" role="alert">{errors[key]}</span>;
  const renderSourceStep = () => <div className="wizard-section-stack">
    <p className="form-intro">Activa las fuentes de la medición y define, con un clic, <b>qué pasa con los datos apenas llegan</b>: si se incorporan automáticamente o requieren fiscalización, y si se evalúan relevancia, sentimiento, clusters y bots. Las redes sociales y Google News se configuran en el paso <b>Scrapers</b>.</p>
    {([
      ['files', 'Archivos (Excel)', 'Varios archivos a la vez; la fuente define el formato.', 'database'],
      ['meltwater', 'API Meltwater', 'Resultados de una búsqueda configurada.', 'cloud'],
      ['manual', 'Manual', 'Captura individual de registros.', 'edit'],
    ] as const).map(([key, title, description, icon]) => <article className={`measurement-source-card${draft.sources[key] ? ' active' : ''}`} key={key}>
      <label className="measurement-source-heading"><span className="wizard-step-icon"><Icon name={icon} size={19} /></span><span><b>{title}</b><small>{description}</small></span><span className="measurement-source-toggle"><input type="checkbox" role="switch" checked={draft.sources[key]} onChange={event => setSource(key, event.target.checked)} /><span className="measurement-source-track" aria-hidden="true" /></span><span className="field-help">{draft.sources[key] ? 'Activa' : 'Inactiva'}</span></label>
      {draft.sources[key] && <>
        {key === 'files' && <MeasurementFilePicker formats={catalogs.formats} selected={selectedFiles} onChange={files => { setSelectedFiles(files); setDirty(true); }} disabled={!yo?.permisos.mediciones?.includes('ejecutar')} />}
        {key === 'meltwater' && <div className="measurement-source-settings"><div className="field"><label htmlFor="meltwater-id">ID de búsqueda en Meltwater <span className="required-mark">*</span></label><input id="meltwater-id" value={draft.meltwaterId} onChange={event => set('meltwaterId', event.target.value)} placeholder="MW-0000000" />{fieldError('meltwaterId')}</div><label className="source-option"><input type="checkbox" checked={draft.meltwaterSchedule.active} disabled={!yo?.permisos.mediciones?.includes('editar')} onChange={event => set('meltwaterSchedule', { ...draft.meltwaterSchedule, ...(event.target.checked && !draft.meltwaterSchedule.start ? defaultMeltwaterWindow() : {}), active: event.target.checked })} /><span><b>Consulta programada</b><small>Requiere mediciones:editar.</small></span></label>{draft.meltwaterSchedule.active && <div className="form-grid"><div className="field"><label htmlFor="meltwater-start">Inicio</label><input id="meltwater-start" type="datetime-local" value={draft.meltwaterSchedule.start} onChange={event => set('meltwaterSchedule', { ...draft.meltwaterSchedule, start: event.target.value })} /></div><div className="field"><label htmlFor="meltwater-end">Fin</label><input id="meltwater-end" type="datetime-local" value={draft.meltwaterSchedule.end} onChange={event => set('meltwaterSchedule', { ...draft.meltwaterSchedule, end: event.target.value })} /></div><div className="field"><label htmlFor="meltwater-frequency">¿Cada cuánto se consulta?</label><div className="frequency-control"><input id="meltwater-frequency" type="number" min="1" step="1" value={draft.meltwaterSchedule.unit === 'h' ? draft.meltwaterSchedule.frequency / 60 : draft.meltwaterSchedule.frequency} onChange={event => set('meltwaterSchedule', { ...draft.meltwaterSchedule, frequency: Number(event.target.value) * (draft.meltwaterSchedule.unit === 'h' ? 60 : 1) })} /><select aria-label="Unidad de frecuencia" value={draft.meltwaterSchedule.unit} onChange={event => set('meltwaterSchedule', { ...draft.meltwaterSchedule, unit: event.target.value })}><option value="min">minutos</option><option value="h">horas</option></select></div><span className="field-help">La API recibe la frecuencia en minutos.</span></div></div>}{fieldError('meltwaterSchedule')}{fieldError('meltwaterFrequency')}{fieldError('meltwaterPermission')}</div>}
        <LoadActionSelector caption="Al cargar estos datos" value={draft.sourceOptions[key === 'files' ? 'archivo' : key] || {}}
          onChange={(option, enabled) => set('sourceOptions', { ...draft.sourceOptions,
            [key === 'files' ? 'archivo' : key]: { ...draft.sourceOptions[key === 'files' ? 'archivo' : key], [option]: enabled } })} />
      </>}
    </article>)}
    <fieldset className="measurement-auto-publish"><legend><Icon name="chart" size={16} /> Tablero</legend>
      <label className="source-option"><input type="checkbox" checked={draft.autoPublish} onChange={event => set('autoPublish', event.target.checked)} /><span><b>Actualizar el tablero automáticamente cuando termine un análisis automático</b><small>Si está apagado, el tablero se actualiza manualmente desde Procesamiento o el Informe.</small></span></label>
    </fieldset>
    {fieldError('sources')}{fieldError('files')}
  </div>;
  const renderStep = () => {
    if (step === 1) return renderSourceStep();
    if (step === 0) return <div className="form-grid"><div className="field"><label htmlFor="measurement-account">Cuenta <span className="required-mark">*</span></label><select id="measurement-account" value={draft.account} onChange={event => set('account', event.target.value)}><option value="">Selecciona una cuenta</option>{catalogs.accounts.map((item: any) => <option key={item.id} value={item.id}>{item.nombre}</option>)}</select><span className="field-help">Solo se muestran cuentas activas visibles para tu usuario.</span>{fieldError('account')}</div><div className="field"><label htmlFor="measurement-name">Nombre de la medición <span className="required-mark">*</span></label><input id="measurement-name" value={draft.name} onChange={event => set('name', event.target.value)} placeholder="Ej. Crisis del agua en Monterrey" />{fieldError('name')}</div><fieldset className="form-choice-group"><legend>¿Corresponde a una coyuntura?</legend><button type="button" className={`option-card${draft.coyuntura === 'si' ? ' selected' : ''}`} aria-pressed={draft.coyuntura === 'si'} onClick={() => set('coyuntura', 'si')}><Icon name="zap" /><span><b>Sí, es coyuntura</b><small>Evento o crisis puntual.</small></span></button><button type="button" className={`option-card${draft.coyuntura === 'no' ? ' selected' : ''}`} aria-pressed={draft.coyuntura === 'no'} onClick={() => set('coyuntura', 'no')}><Icon name="pulse" /><span><b>No, seguimiento regular</b><small>Monitoreo continuo de un actor, gobierno o partido.</small></span></button></fieldset><div className="field"><label htmlFor="measurement-status">Estado</label><select id="measurement-status" value={draft.status} onChange={event => set('status', Number(event.target.value))}><option value={1}>Activa</option><option value={0}>Inactiva (borrador)</option></select></div></div>;
    if (step === 2) return <div className="wizard-section-stack"><p className="form-intro">Configura redes, países, actores y palabras de búsqueda. Estos valores se guardarán con la medición.</p>{!draft.scraperOpen ? <div className="wizard-empty"><span className="empty-icon"><Icon name="globe" /></span><b>Sin procesos de scraping</b><p>Los scrapers son opcionales y pertenecen a esta medición.</p><button type="button" className="button" onClick={() => set('scraperOpen', true)}><Icon name="plus" size={15} /> Nuevo proceso de scraping</button></div> : <div className="fieldset"><div className="fieldset-title">Nuevo proceso de scraping</div><div className="form-grid"><div className="field"><label>Nombre</label><input value={draft.scraper.name} onChange={event => set('scraper', { ...draft.scraper, name: event.target.value })} /></div><div className="field"><label>Frecuencia (minutos)</label><input type="number" min="15" value={draft.scraper.frequency} onChange={event => set('scraper', { ...draft.scraper, frequency: Number(event.target.value) })} /></div><div className="field"><label>Inicio</label><input type="datetime-local" value={draft.scraper.start} onChange={event => set('scraper', { ...draft.scraper, start: event.target.value })} /></div><div className="field"><label>Fin</label><input type="datetime-local" value={draft.scraper.end} onChange={event => set('scraper', { ...draft.scraper, end: event.target.value })} /></div></div><h3>Redes</h3>{['x', 'tiktok', 'youtube', 'facebook', 'instagram'].map(network => { const current = draft.scraper.networks[network] || {}; const actors = catalogs.actors.filter((actor: any) => actor.red === network); return <div className="fieldset" key={network}><label className="source-option"><input type="checkbox" checked={Boolean(current.active)} onChange={event => set('scraper', { ...draft.scraper, networks: { ...draft.scraper.networks, [network]: { ...current, active: event.target.checked } } })} /><span><b>{network}</b></span></label>{current.active && <div className="form-grid"><div className="field"><label>Actor</label><select value={current.actorId || ''} onChange={event => set('scraper', { ...draft.scraper, networks: { ...draft.scraper.networks, [network]: { ...current, actorId: event.target.value } } })}><option value="">Actor activo predeterminado</option>{actors.map((actor: any) => <option key={actor.id} value={actor.id}>{actor.nombre} · máximo {actor.max_registros}</option>)}</select></div><div className="field"><label>Máximo de registros</label><input type="number" min="1" value={current.records || 100} onChange={event => set('scraper', { ...draft.scraper, networks: { ...draft.scraper.networks, [network]: { ...current, records: Number(event.target.value) } } })} /></div><div className="field"><label>Palabras de búsqueda (separadas por coma)</label><input value={current.keywords || ''} onChange={event => set('scraper', { ...draft.scraper, networks: { ...draft.scraper.networks, [network]: { ...current, keywords: event.target.value } } })} />{fieldError(`scraper-${network}`)}</div></div>}</div>; })}<label className="source-option"><input type="checkbox" checked={draft.scraper.google} onChange={event => set('scraper', { ...draft.scraper, google: event.target.checked })} /><span><b>Google News</b></span></label>{draft.scraper.google && <div className="form-grid"><div className="field"><label>Países</label><select multiple value={draft.scraper.countries.map(String)} onChange={event => set('scraper', { ...draft.scraper, countries: Array.from(event.target.selectedOptions).map(option => option.value) })}>{catalogs.countries.map((country: any) => <option key={country.id} value={country.id}>{country.nombre} ({country.codigo})</option>)}</select></div><div className="field"><label>Palabras de búsqueda (separadas por coma)</label><input value={draft.scraper.googleKeywords || ''} onChange={event => set('scraper', { ...draft.scraper, googleKeywords: event.target.value })} />{fieldError('scraperGoogle')}</div></div>}{fieldError('scraper')}{fieldError('scraperDates')}{fieldError('scraperSource')}{fieldError('scraperFrequency')}<button type="button" className="button" onClick={() => set('scraperOpen', false)}>Quitar este proceso</button></div>}</div>;
    if (step === 3) { const selected = draft.promptSelections[draft.promptKind] || { origin: 'defecto', promptId: '', version: '' }; const kind = promptTypeByLabel[draft.promptKind]; const choices = catalogs.prompts.filter((prompt: any) => prompt.tipo === kind && prompt.estado_id === 1 && !prompt.red && (selected.origin !== 'defecto' || prompt.por_defecto)); const versions = promptVersions[String(selected.promptId)] || []; return <div className="wizard-section-stack"><p className="form-intro">Selecciona un prompt activo y una versión inmutable. El backend guardará exactamente esa versión.</p><div className="seg wizard-tabs" role="tablist" aria-label="Tipo de prompt">{promptKinds.map(label => <button type="button" role="tab" aria-selected={draft.promptKind === label} className={draft.promptKind === label ? 'on' : ''} key={label} onClick={() => set('promptKind', label)}>{label}</button>)}</div><div className="field"><label>Origen</label><select value={selected.origin || 'defecto'} onChange={event => set('promptSelections', { ...draft.promptSelections, [draft.promptKind]: { origin: event.target.value, promptId: '', version: '' } })}><option value="defecto">Prompt por defecto</option>{['Clusters', 'Temas finales'].includes(draft.promptKind) && <option value="cuenta">Prompt de la cuenta</option>}<option value="propio">Prompt propio</option></select></div>{selected.origin === 'propio' ? <div className="field"><label htmlFor="measurement-prompt">Prompt propio de {draft.promptKind}</label><textarea id="measurement-prompt" rows={8} value={draft.prompts[draft.promptKind] || ''} onChange={event => set('prompts', { ...draft.prompts, [draft.promptKind]: event.target.value })} />{fieldError(`prompt-${draft.promptKind}`)}</div> : selected.origin === 'cuenta' ? <p className="field-help">Se utilizará el prompt configurado actualmente en la cuenta seleccionada.</p> : <div className="form-grid"><div className="field"><label>Prompt activo</label><select value={selected.promptId || ''} onChange={event => void choosePrompt(draft.promptKind, event.target.value)}><option value="">Selecciona un prompt</option>{choices.map((prompt: any) => <option key={prompt.id} value={prompt.id}>{prompt.nombre}</option>)}</select></div><div className="field"><label>Versión</label><select value={selected.version || ''} disabled={!selected.promptId} onChange={event => void choosePromptVersion(draft.promptKind, event.target.value)}><option value="">Selecciona una versión</option>{versions.map((version: any) => <option key={version.version} value={version.version}>v{version.version}</option>)}</select></div>{fieldError(`prompt-${draft.promptKind}`)}</div>}</div>; }
    if (step === 4) return <div className="form-grid"><div className="field"><label htmlFor="clusters">Clusters <span className="required-mark">*</span></label><input id="clusters" type="number" min={2} max={30} value={draft.clusters} onChange={event => set('clusters', Number(event.target.value))} />{fieldError('clusters')}</div><div className="field"><label htmlFor="subclusters">Subclusters por cluster <span className="required-mark">*</span></label><input id="subclusters" type="number" min={1} max={10} value={draft.subclusters} onChange={event => set('subclusters', Number(event.target.value))} />{fieldError('subclusters')}</div><fieldset className="form-choice-group"><legend>Analizar</legend><button type="button" className={`option-card${draft.analysis === 'temas_sentimiento' ? ' selected' : ''}`} aria-pressed={draft.analysis === 'temas_sentimiento'} onClick={() => set('analysis', 'temas_sentimiento')}><Icon name="layers" /><span><b>Temas y sentimiento</b><small>Clusters, subclusters, temas finales y sentimiento por registro.</small></span></button><button type="button" className={`option-card${draft.analysis === 'sentimiento_medios' ? ' selected' : ''}`} aria-pressed={draft.analysis === 'sentimiento_medios'} onClick={() => set('analysis', 'sentimiento_medios')}><Icon name="globe" /><span><b>Sentimiento en medios</b><small>Tono editorial de la cobertura de prensa y portales.</small></span></button></fieldset><div className="field"><label htmlFor="cross-name">Cruces · nombre de lista (opcional)</label><input id="cross-name" value={draft.crossName} onChange={event => set('crossName', event.target.value)} placeholder="Ej. Gabinete estatal NL" /></div><div className="field"><label htmlFor="cross-terms">Cuentas y hashtags de la lista</label><input id="cross-terms" value={draft.crossTerms} onChange={event => set('crossTerms', event.target.value)} placeholder="@cuenta, #hashtag" /><span className="field-help">Los términos se guardarán como una lista propia de esta medición.</span></div><div className="field"><label>Listas existentes</label>{catalogs.crosses.map((cross: any) => <label className="source-option" key={cross.id}><input type="checkbox" checked={draft.selectedCrosses.includes(cross.id)} onChange={event => set('selectedCrosses', event.target.checked ? [...draft.selectedCrosses, cross.id] : draft.selectedCrosses.filter((id: number) => id !== cross.id))} /><span><b>{cross.nombre}</b><small>{(cross.items || []).join(', ')}</small></span></label>)}</div></div>;
    if (step === 5) return <div className="wizard-section-stack"><label className="source-option"><input type="checkbox" checked={draft.bots} onChange={event => set('bots', event.target.checked)} /><span><b>Análisis de bots</b><small>Opcional</small></span></label>{draft.bots && <div className="form-grid">{[['identify', 'Bots', 'Identifica y marca cada cuenta sospechosa.'], ['negativeReposts', 'RTs bots negativos', 'Cuantifica amplificación negativa automatizada.'], ['positiveNegative', 'Bots positivo y negativo', 'Separa bots que atacan de bots que defienden.']].map(([key, label, desc]) => <label className="source-option" key={key}><input type="checkbox" checked={draft.botOptions[key]} onChange={event => set('botOptions', { ...draft.botOptions, [key]: event.target.checked })} /><span><b>{label}</b><small>{desc}</small></span></label>)}</div>}<div className="fieldset"><div className="fieldset-title">Parámetros de X</div><div className="form-grid"><div className="field"><label htmlFor="x-accounts">N° de cuentas en X <span className="required-mark">*</span></label><input id="x-accounts" type="number" min={0} value={draft.xAccounts} onChange={event => set('xAccounts', Number(event.target.value))} /><span className="field-help">Top de cuentas de X a analizar.</span>{fieldError('xAccounts')}</div><div className="field"><label htmlFor="x-mentions">N° de menciones en X <span className="required-mark">*</span></label><input id="x-mentions" type="number" min={0} value={draft.xMentions} onChange={event => set('xMentions', Number(event.target.value))} /><span className="field-help">0 = se calcula desde los datos cargados.</span>{fieldError('xMentions')}</div></div></div></div>;
    if (step === 6) return <div className="wizard-section-stack"><div className="field"><label>Regex disponibles</label>{catalogs.regex.map((item: any) => <label className="source-option" key={item.id}><input type="checkbox" checked={draft.regexSelected.includes(item.id)} onChange={event => selectRegex(item.id, event.target.checked)} /><span><b>{item.nombre}</b><small>v{item.version} · {item.descripcion || item.condicion}</small></span></label>)}{!catalogs.regex.length && <div className="wizard-empty compact"><b>No hay regex activas disponibles</b></div>}</div>{draft.regexSelected.length > 0 && <div className="field"><label>Orden de aplicación</label>{draft.regexSelected.map((id: number, index: number) => { const item = catalogs.regex.find((regex: any) => regex.id === id); return <div className="source-option" key={id}><span><b>{index + 1}. {item?.nombre || `Regex ${id}`}</b></span><button type="button" className="icon-button" disabled={index === 0} aria-label="Mover hacia arriba" onClick={() => { const next = [...draft.regexSelected]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; set('regexSelected', next); }}>↑</button><button type="button" className="icon-button" disabled={index === draft.regexSelected.length - 1} aria-label="Mover hacia abajo" onClick={() => { const next = [...draft.regexSelected]; [next[index], next[index + 1]] = [next[index + 1], next[index]]; set('regexSelected', next); }}>↓</button></div>; })}</div>}<label className="source-option"><input type="checkbox" checked={draft.precluster} onChange={event => set('precluster', event.target.checked)} /><span><b>Preclasificar posts por regex (preclustering)</b><small>Cada post se asigna a la primera regex que coincida según el orden seleccionado.</small></span></label>{fieldError('regex')}<fieldset className="form-choice-group"><legend>Fecha y hora desde la cual inicia el análisis</legend><button type="button" className={`option-card${draft.window === 'historia' ? ' selected' : ''}`} onClick={() => set('window', 'historia')} aria-pressed={draft.window === 'historia'}><Icon name="clock" /><span><b>Calcular sobre toda la historia</b><small>Se analizan todos los registros disponibles.</small></span></button><button type="button" className={`option-card${draft.window === 'desde' ? ' selected' : ''}`} onClick={() => set('window', 'desde')} aria-pressed={draft.window === 'desde'}><Icon name="calendar" /><span><b>A partir de una fecha y hora</b><small>Solo registros desde ese instante.</small></span></button></fieldset>{draft.window === 'desde' && <div className="field"><label htmlFor="start-date">Fecha y hora de inicio <span className="required-mark">*</span></label><input id="start-date" type="datetime-local" value={draft.startDate} onChange={event => set('startDate', event.target.value)} />{fieldError('startDate')}</div>}</div>;
    const problems = measurementSteps.slice(0, 7).flatMap((item, index) => Object.values(stepErrors(index)).map(message => `${item[0]}: ${message}`));
    return <div className="wizard-section-stack"><div className="form-note"><Icon name="info" size={16} /> La configuración, el proceso de preparación y su tarea durable se guardarán en una transacción. El progreso se consulta en Procesos.</div>{catalogNotice && <p className="control-notice error" role="alert">{catalogNotice}</p>}{problems.length > 0 && <div className="form-errors" role="alert"><b>Pendientes antes de guardar:</b><ul>{problems.map(problem => <li key={problem}>{problem}</li>)}</ul></div>}<dl className="wizard-review"><dt>Cuenta</dt><dd>{catalogs.accounts.find((account: any) => String(account.id) === String(draft.account))?.nombre || '—'}</dd><dt>Nombre</dt><dd>{draft.name || '—'}</dd><dt>Estado funcional</dt><dd>{draft.status === 1 ? 'Activa' : 'Inactiva (borrador)'}</dd><dt>Fuentes activas</dt><dd>{Object.entries(draft.sources).filter(([, active]) => active).map(([key]) => ({ files: 'Archivos (Excel)', meltwater: 'Meltwater', manual: 'Manual' }[key])).join(', ') || '—'}</dd><dt>Scrapers</dt><dd>{draft.scraperOpen ? draft.scraper.name || 'Configuración sin nombre' : '—'}</dd><dt>Prompts seleccionados</dt><dd>{promptKinds.map(kind => { const selected = draft.promptSelections[kind] || {}; return selected.origin === 'propio' ? `${kind}: propio` : selected.origin === 'cuenta' ? `${kind}: cuenta` : selected.promptId ? `${kind}: ${catalogs.prompts.find((item: any) => item.id === Number(selected.promptId))?.nombre || 'prompt'} v${selected.version || '—'}` : `${kind}: —`; }).join(' · ')}</dd><dt>Clusters × subclusters</dt><dd>{draft.clusters} × {draft.subclusters}</dd><dt>Regex</dt><dd>{draft.regexSelected.length} seleccionadas</dd><dt>Ventana</dt><dd>{draft.window === 'historia' ? 'Toda la historia' : draft.startDate || '—'}</dd></dl></div>;
  };
  return <>
    <div className="page-heading wizard-page-heading"><div><h1>Nueva medición</h1><p>{defaultMeasurementDescription}</p></div><div className="wizard-heading-actions"><button type="button" className="button" onClick={cancel}>Cancelar</button><button type="button" className="button" onClick={saveDraft}><Icon name="download" size={15} /> Guardar borrador</button></div></div>
    <div className="wizard-layout">
      <nav className="panel wizard-steps" aria-label="Pasos de configuración">{measurementSteps.map(([name, description], index) => { const stepInvalid = Object.keys(stepErrors(index)).some(key => errors[key]); const done = index < step && !Object.keys(stepErrors(index)).length; return <button type="button" className={`wizard-step${step === index ? ' current' : ''}${done ? ' done' : ''}${stepInvalid ? ' invalid' : ''}`} key={name} aria-current={step === index ? 'step' : undefined} onClick={() => goStep(index)}><span>{done ? <Icon name="check" size={13} /> : String(index + 1).padStart(2, '0')}</span><span><b>{name}</b><small>{description}</small></span></button>; })}</nav>
      <section className="panel wizard-form"><div className="panel-heading"><span className="wizard-step-icon"><Icon name={['briefcase','database','cloud','sparkles','layers','bot','code','check'][step]} size={18} /></span><div><p className="eyebrow">PASO {step + 1} DE {measurementSteps.length}</p><h2>{measurementSteps[step][0]}</h2></div></div><div className="form-content">{renderStep()}{notice && <p className={`control-notice${notice.startsWith('Revisa') || notice.startsWith('Completa') ? ' error' : ''}`} role="status">{notice}</p>}<div className="form-actions">{step > 0 ? <button type="button" className="button" onClick={() => goStep(step - 1)}><Icon name="arrow" size={15} /> Anterior</button> : <span />}{step < measurementSteps.length - 1 ? <button type="button" className="button primary" onClick={nextStep}>Siguiente <Icon name="chevron" size={15} /></button> : <button type="button" className="button primary" disabled={saving} onClick={() => void save()}><Icon name="check" size={15} /> {saving ? 'Guardando…' : 'Guardar'}</button>}</div></div></section>
      <aside className="panel wizard-summary"><div className="panel-heading"><h2>Resumen</h2><span className="panel-sub">{completedSteps}/7 pasos revisados</span></div><dl className="wizard-review"><dt>Cuenta</dt><dd>{draft.account || '—'}</dd><dt>Nombre</dt><dd>{draft.name || '—'}</dd><dt>Coyuntura</dt><dd>{draft.coyuntura === 'si' ? 'Sí' : draft.coyuntura === 'no' ? 'No' : '—'}</dd><dt>Fuentes</dt><dd>{Object.entries(draft.sources).filter(([, active]) => active).map(([key]) => ({ files: 'Archivos', meltwater: 'Meltwater', manual: 'Manual' }[key])).join(', ') || '—'}</dd><dt>Scrapers</dt><dd>{draft.scraperOpen ? 'Configuración local sin guardar' : '—'}</dd><dt>Regex</dt><dd>{draft.regexSelected.length}</dd></dl></aside>
    </div>
    {confirmDiscard && <div className="command-scrim"><section className="command-panel discard-dialog" role="dialog" aria-modal="true" aria-labelledby="discard-title"><div className="panel-heading"><h2 id="discard-title">¿Descartar la configuración?</h2></div><p>Los datos escritos en este formulario se perderán y aún no se guardaron.</p><div className="form-actions"><button className="button" type="button" onClick={() => setConfirmDiscard(false)}>Conservar formulario</button><button className="button danger-button" type="button" onClick={() => navigate(`/mediciones${previewMode ? '?preview=1' : ''}`)}>Descartar y volver</button></div></section></div>}
  </>;
}

function MeasurementSourceConfigPage({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [measurement, setMeasurement] = useState<any | null>(null);
  const [etag, setEtag] = useState('');
  const [sources, setSources] = useState<Record<string, { activo: boolean; busquedaId: string; alCargar: Record<string, boolean> }>>({
    archivo: { activo: false, busquedaId: '', alCargar: { ...defaultLoadOptions } },
    meltwater: { activo: false, busquedaId: '', alCargar: { ...defaultLoadOptions } },
    manual: { activo: false, busquedaId: '', alCargar: { ...defaultLoadOptions } },
  });
  const [schedule, setSchedule] = useState({ activa: false, inicio: '', fin: '', frecuencia: 60 });
  const [autoPublish, setAutoPublish] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [formats, setFormats] = useState<any[]>([]);
  const canEdit = yo?.permisos.mediciones?.includes('editar') ?? false;
  const localDateTime = (value: string | null | undefined) => {
    if (!value) return '';
    const date = new Date(value);
    const pad = (part: number) => String(part).padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  };
  useEffect(() => {
    if (!canEdit) { setLoading(false); return; }
    let active = true;
    if (yo?.permisos.formatos?.includes('ver')) api('/formatos').then(response => response.json()).then(items => { if (active && Array.isArray(items)) setFormats(items); }).catch(() => {});
    api(`/mediciones/${id}`).then(async response => {
      const body = await response.json();
      if (!active) return;
      setMeasurement(body); setEtag(response.headers.get('ETag') || ''); setAutoPublish(Boolean(body.auto_publicar));
      const restored = { archivo: { activo: false, busquedaId: '', alCargar: { ...defaultLoadOptions } }, meltwater: { activo: false, busquedaId: '', alCargar: { ...defaultLoadOptions } }, manual: { activo: false, busquedaId: '', alCargar: { ...defaultLoadOptions } } };
      for (const source of body.fuentes || []) {
        if (!(source.origen in restored)) continue;
        restored[source.origen as keyof typeof restored] = { activo: Boolean(source.activo),
          busquedaId: String(source.config?.busqueda_id || ''), alCargar: { ...defaultLoadOptions, ...(source.al_cargar || {}) } };
      }
      setSources(restored);
      const configured = body.programacion_meltwater || {};
      setSchedule({ activa: Boolean(configured.activa), inicio: localDateTime(configured.inicio), fin: localDateTime(configured.fin), frecuencia: configured.frecuencia_min || 60 });
    }).catch(error => { if (active) setNotice(clientError(error, 'No se pudo recuperar la configuración de la medición.')); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, canEdit]);
  const save = async () => {
    if (!etag) { setNotice('No se recibió la versión de la medición; vuelve a cargar el detalle antes de guardar.'); return; }
    if (schedule.activa && (!sources.meltwater.activo || !sources.meltwater.busquedaId.trim() || !schedule.inicio || !schedule.fin || new Date(schedule.fin) <= new Date(schedule.inicio) || schedule.frecuencia < 15)) {
      setNotice('Revisa Meltwater: requiere fuente activa, ID de búsqueda, fechas ordenadas y frecuencia mínima de 15 minutos.'); return;
    }
    const requestSources = Object.entries(sources).map(([origen, value]) => ({ origen, activo: value.activo,
      config: origen === 'meltwater' ? { busqueda_id: value.busquedaId.trim() } : {}, al_cargar: value.alCargar }));
    setSaving(true); setNotice('');
    try {
      const updated = await api(`/mediciones/${id}`, { method: 'PATCH', headers: { 'If-Match': etag }, body: JSON.stringify({
        fuentes: requestSources,
        programacion_meltwater: schedule.activa ? { activa: true, inicio: new Date(schedule.inicio).toISOString(), fin: new Date(schedule.fin).toISOString(), frecuencia_min: Number(schedule.frecuencia) } : { activa: false },
        auto_publicar: autoPublish,
      }) });
      const body = await updated.json();
      setEtag(updated.headers.get('ETag') || ''); setMeasurement(body);
      setNotice('Configuración guardada.');
    } catch (error) { setNotice(clientError(error, 'No se pudo guardar la configuración.')); }
    finally { setSaving(false); }
  };
  if (!canEdit) return <><PageHeading title="Editar fuentes y opciones" description="La edición de la configuración requiere mediciones:editar." /><section className="panel"><EmptyState title="Sin permiso para editar" detail="Solicita mediciones:editar para modificar esta configuración." /></section></>;
  return <><PageHeading title={measurement ? `Editar fuentes · ${measurement.nombre}` : 'Editar fuentes'} description="Actualiza las fuentes, las opciones ‘Al cargar’, Meltwater y el tablero automático." action={{ label: 'Volver al detalle', path: `/mediciones/${id}` }} />
    <section className="panel"><div className="form-content">{loading ? <EmptyState title="Recuperando configuración…" /> : notice && !measurement ? <p className="control-notice error" role="alert">{notice}</p> : measurement && <div className="wizard-section-stack">
      <p className="form-intro">Cuenta: {measurement.cuenta_nombre}. Las opciones se recuperan del detalle y se guardan mediante PATCH con control de concurrencia.</p>
      {(['archivo', 'meltwater', 'manual'] as const).map(origin => { const value = sources[origin]; const titles = { archivo: 'Archivos (Excel)', meltwater: 'API Meltwater', manual: 'Manual' }; return <article className="fieldset" key={origin}>
        <label className="source-option"><input type="checkbox" checked={value.activo} onChange={event => setSources(current => ({ ...current, [origin]: { ...current[origin], activo: event.target.checked } }))} /><span><b>{titles[origin]}</b></span></label>
        {value.activo && <div className="wizard-section-stack">{origin === 'archivo' && <div className="field"><label>Formatos disponibles</label><div className="chips">{formats.map((format: any) => <span className="badge outline" key={format.id}>{format.nombre} · {format.extensiones}</span>)}</div><span className="field-help">La selección y validación de archivos pertenece al flujo Cargas.</span></div>}
          {origin === 'meltwater' && <><div className="field"><label htmlFor="edit-meltwater-id">ID de búsqueda en Meltwater</label><input id="edit-meltwater-id" value={value.busquedaId} onChange={event => setSources(current => ({ ...current, meltwater: { ...current.meltwater, busquedaId: event.target.value } }))} /></div><label className="source-option"><input type="checkbox" checked={schedule.activa} onChange={event => setSchedule(current => ({ ...current, activa: event.target.checked }))} /><span><b>Consulta programada</b><small>Requiere permiso mediciones:editar.</small></span></label>{schedule.activa && <div className="form-grid"><div className="field"><label>Inicio</label><input type="datetime-local" value={schedule.inicio} onChange={event => setSchedule(current => ({ ...current, inicio: event.target.value }))} /></div><div className="field"><label>Fin</label><input type="datetime-local" value={schedule.fin} onChange={event => setSchedule(current => ({ ...current, fin: event.target.value }))} /></div><div className="field"><label>Frecuencia (minutos)</label><input type="number" min="15" value={schedule.frecuencia} onChange={event => setSchedule(current => ({ ...current, frecuencia: Number(event.target.value) }))} /></div></div>}</>}
          <div className="wizard-section-stack"><div className="fieldset-title">Al cargar estos datos</div>{loadOptionDefinitions.map(([key, title, help]) => <label className="source-option" key={key}><input type="checkbox" checked={Boolean(value.alCargar[key])} onChange={event => setSources(current => ({ ...current, [origin]: { ...current[origin], alCargar: { ...current[origin].alCargar, [key]: event.target.checked } } }))} /><span><b>{title}</b><small>{help}</small></span></label>)}</div>
        </div>}
      </article>; })}
      <label className="source-option"><input type="checkbox" checked={autoPublish} onChange={event => setAutoPublish(event.target.checked)} /><span><b>Actualizar el tablero automáticamente</b><small>Al finalizar un análisis automático.</small></span></label>
      <div className="form-actions"><button className="button" type="button" onClick={() => navigate(`/mediciones/${id}`)}>Cancelar</button><button className="button primary" type="button" disabled={saving || loading} onClick={() => void save()}>{saving ? 'Guardando…' : 'Guardar cambios'}</button></div>
    </div>}{notice && measurement && <p className={`control-notice${notice.includes('guardada') ? '' : ' error'}`} role="status">{notice}</p>}</div></section>
  </>;
}

const MEASUREMENT_DETAIL_TABS = [
  ['resumen', 'Resumen', 'home'], ['cargas', 'Cargas', 'upload'], ['scraper', 'Scraper', 'cloud'],
  ['fiscalizacion', 'Fiscalización', 'scale'], ['registros', 'Registros', 'database'],
  ['procesamiento', 'Procesamiento', 'cycle'], ['informe', 'Informe', 'chart'], ['configuracion', 'Configuración', 'settings'],
] as const;
const MEASUREMENT_STATUS_COLUMNS = [
  'Cargados', 'Duplicados omitidos', 'Por fiscalizar', 'Cumplen sin incorporar', 'Descartados',
  'Incorporados', 'Metadata actualizada', 'Transcritos', 'Pendientes de análisis', 'Analizados', 'En tablero', 'Eliminados',
];
type MeasurementSourceStatus = { origen: string; cargados: number; duplicados: number;
  por_fiscalizar: number; cumplen_sin_incorporar: number; descartados: number;
  incorporados: number; con_metricas: number; transcritos: number; analizados: number;
  en_tablero: number; eliminados: number; con_error: number };
const MEASUREMENT_STATUS_FIELDS: Record<string, keyof MeasurementSourceStatus | null> = {
  Cargados: 'cargados', 'Duplicados omitidos': 'duplicados',
  'Por fiscalizar': 'por_fiscalizar', 'Cumplen sin incorporar': 'cumplen_sin_incorporar',
  Descartados: 'descartados', Incorporados: 'incorporados', Transcritos: 'transcritos',
  Analizados: 'analizados', 'En tablero': 'en_tablero', Eliminados: 'eliminados',
  'Metadata actualizada': null, 'Pendientes de análisis': null,
};
const loadOptionIcons: Record<string, string> = { incorporar: 'zap', relevancia: 'target', sentimiento: 'heart', clusters: 'layers', bots: 'bot' };

function MeasurementDetail({ yo }: { yo: Yo | null }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [measurement, setMeasurement] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const allowedTabs = MEASUREMENT_DETAIL_TABS.map(([key]) => key);
  const selectedTab = searchParams.get('tab') || 'resumen';
  const section = allowedTabs.includes(selectedTab as typeof allowedTabs[number]) ? selectedTab : 'resumen';
  const [recentProcesses, setRecentProcesses] = useState<MonitoredProcess[]>([]);
  const [processesNotice, setProcessesNotice] = useState('');
  const [sourceSummary, setSourceSummary] = useState<MeasurementSourceStatus[] | null>(null);
  const [sourceSummaryNotice, setSourceSummaryNotice] = useState('');
  const [uploadOpen, setUploadOpen] = useState(false);
  const [filesRefreshKey, setFilesRefreshKey] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setMeasurement(null); setRecentProcesses([]); setProcessesNotice('');
    api(`/mediciones/${id}`).then(response => response.json()).then(body => { if (active) setMeasurement(body); })
      .catch(cause => { if (active) setError(clientError(cause, 'No se pudo cargar la medición.')); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id]);
  const canEdit = yo?.permisos.mediciones?.includes('editar') ?? false;
  const canExecute = yo?.permisos.mediciones?.includes('ejecutar') ?? false;
  const canViewFormats = yo?.permisos.formatos?.includes('ver') ?? false;
  const canViewProcesses = Boolean(yo?.permisos.procesos?.includes('ver'));
  useEffect(() => {
    if (!id || section !== 'resumen') return;
    let active = true;
    setSourceSummary(null); setSourceSummaryNotice('');
    api(`/mediciones/${id}/resumen`).then(response => response.json()).then(body => {
      if (active) setSourceSummary(Array.isArray(body.por_fuente) ? body.por_fuente : []);
    }).catch(() => {
      if (active) setSourceSummaryNotice('No se pudo consultar el estado persistido por fuente.');
    });
    return () => { active = false; };
  }, [id, section, filesRefreshKey]);
  useEffect(() => {
    if (!id || !canViewProcesses) return;
    let active = true;
    api(`/procesos?medicion_id=${encodeURIComponent(id)}&limite=6`)
      .then(response => response.json())
      .then(body => { if (active) setRecentProcesses(Array.isArray(body) ? body : []); })
      .catch(() => { if (active) setProcessesNotice('No fue posible consultar los procesos disponibles.'); });
    return () => { active = false; };
  }, [id, canViewProcesses]);
  const sources = (measurement?.fuentes || []) as any[];
  const activeSources = sources.filter(source => source.activo);
  const fileSourceActive = activeSources.some(source => source.origen === 'archivo');
  const sourceOptionLabels: Record<string, string> = Object.fromEntries(loadOptionDefinitions.map(([key, label]) => [key, label]));
  const renderSourceDetails = () => activeSources.length
    ? <div className="measurement-source-details">{activeSources.map(source => {
      const loaded = Object.entries(source.al_cargar || {}).filter(([, enabled]) => enabled)
        .map(([key]) => sourceOptionLabels[key] || key);
      const title = SOURCE_LABELS[source.origen] || source.origen;
      const scheduled = source.origen === 'meltwater' && measurement.programacion_meltwater?.activa;
      return <article className="measurement-source-detail" key={source.origen}>
        <div className="measurement-source-detail-head"><strong>{title}</strong><span className="badge ok"><span className="d" aria-hidden="true" />Activa</span></div>
        {source.origen === 'meltwater' && <p>ID de búsqueda: {source.config?.busqueda_id || '—'} · {scheduled ? `Consulta programada cada ${measurement.programacion_meltwater.frecuencia_min} minutos` : 'Sin consulta programada'}</p>}
        <div><span className="measurement-card-label">Al cargar</span>
          <div className="measurement-source-detail-options">{loaded.length ? loaded.map(label => <span className="badge info" key={label}>{label}</span>) : <span className="muted">Sin opciones activas</span>}</div>
        </div>
      </article>;
    })}</div>
    : <EmptyState title="No hay fuentes activas" detail="La medición no tiene fuentes activas configuradas." />;
  const selectTab = (tab: string) => {
    const next = new URLSearchParams(searchParams);
    if (tab === 'resumen') next.delete('tab'); else next.set('tab', tab);
    setSearchParams(next);
  };
  const pipeStages = [
    ['upload', 'Cargados', 'Cargas', 'cargas'], ['scale', 'Por fiscalizar', 'Fiscalizar', 'fiscalizacion'],
    ['check', 'Incorporados', 'Registros', 'registros'], ['cycle', 'Enriquecidos', 'Procesamiento', 'procesamiento'],
    ['layers', 'Analizados', 'Procesamiento', 'procesamiento'], ['chart', 'En tablero', 'Informe', 'informe'],
  ] as const;
  const pipeFields: Record<string, keyof MeasurementSourceStatus | null> = {
    Cargados: 'cargados', 'Por fiscalizar': 'por_fiscalizar', Incorporados: 'incorporados',
    Enriquecidos: null, Analizados: 'analizados', 'En tablero': 'en_tablero',
  };
  const pipeMetric = (label: string): number | null => {
    const field = pipeFields[label];
    return sourceSummary && field
      ? sourceSummary.reduce((total, source) => total + (Number(source[field]) || 0), 0)
      : null;
  };
  const renderPipe = () => <div className="measurement-pipe" aria-label="Flujo de datos de la medición">
    {pipeStages.map(([icon, label, linkLabel, tab], index) => <Fragment key={label}>
      {index > 0 && <span className="measurement-pipe-arrow" aria-hidden="true"><Icon name="chevron" size={17} /></span>}
      <article className="measurement-pipe-box">
        <div className="measurement-pipe-heading"><span className="measurement-pipe-icon"><Icon name={icon} size={15} /></span><span>{label}</span></div>
        <strong className="measurement-pipe-value" aria-label={`${label}: ${pipeMetric(label) ?? 'dato no disponible'}`}>{pipeMetric(label) ?? '—'}</strong>
        <span className="measurement-pipe-note">{pipeMetric(label) === null ? 'Métrica no disponible en la API actual' : 'Registros persistidos'}</span>
        <button className="button xs" type="button" onClick={() => selectTab(tab)}>{linkLabel} <Icon name="arrow" size={12} /></button>
      </article>
    </Fragment>)}
  </div>;
  const sourceStatuses = new Map((sourceSummary || []).map(row => [row.origen, row]));
  const statusOrigins = [...new Set([...activeSources.map(source => source.origen), ...sourceStatuses.keys()])];
  const sourceMetric = (origin: string, column: string) => {
    const field = MEASUREMENT_STATUS_FIELDS[column];
    if (!sourceSummary || !field) return '—';
    return sourceStatuses.get(origin)?.[field] ?? 0;
  };
  const renderSourceStatus = () => <section className="panel measurement-detail-section">
    <div className="card-head"><h2>Estado por fuente</h2><span className="sub">Datos persistidos de esta medición</span></div>
    {sourceSummaryNotice && <p className="control-notice error" role="alert">{sourceSummaryNotice}</p>}
    <div className="table-scroll"><table className="measurement-static-table"><thead><tr><th>Fuente (quién incorporó)</th><th>Al cargar</th>{MEASUREMENT_STATUS_COLUMNS.map(column => <th key={column}>{column}</th>)}</tr></thead>
      <tbody>{statusOrigins.length ? statusOrigins.map(origin => {
        const configured = sources.find(source => source.origen === origin);
        return <tr key={origin}>
          <td><span className="badge outline">{SOURCE_LABELS[origin] || origin}</span>{configured && !configured.activo && <span className="muted"> · inactiva actualmente</span>}</td>
          <td>{configured?.activo ? <span className="measurement-load-icons" aria-label={`Opciones configuradas al cargar para ${SOURCE_LABELS[origin] || origin}`}>{loadOptionDefinitions.map(([key, label]) => <span key={key} className={`measurement-load-icon-state${configured.al_cargar?.[key] ? ' enabled' : ''}`} title={`${label}: ${configured.al_cargar?.[key] ? 'Sí' : 'No'}`} aria-label={`${label}: ${configured.al_cargar?.[key] ? 'Sí' : 'No'}`}><Icon name={loadOptionIcons[key] || 'info'} size={13} /></span>)}</span> : <span className="muted">—</span>}</td>
          {MEASUREMENT_STATUS_COLUMNS.map(column => <td className="num" key={column} title={MEASUREMENT_STATUS_FIELDS[column] ? undefined : 'Esta métrica aún no está expuesta por el contrato'}>{sourceMetric(origin, column)}</td>)}
        </tr>;
      }) : <tr><td colSpan={MEASUREMENT_STATUS_COLUMNS.length + 2} className="empty">No hay fuentes ni cargas registradas para esta medición.</td></tr>}</tbody>
    </table></div><div className="measurement-load-legend" aria-label="Leyenda de opciones al cargar">{loadOptionDefinitions.map(([key, label]) => <span key={key}><Icon name={loadOptionIcons[key] || 'info'} size={13} />{label}</span>)}</div>
  </section>;
  const renderLatestProcesses = () => <section className="panel measurement-detail-section">
    <div className="card-head measurement-process-heading"><h2>Últimos procesos</h2><Link className="button xs" to="/procesos">Ver monitor</Link></div>
    {!canViewProcesses ? <EmptyState title="Sin permiso para consultar procesos" detail="Se requiere procesos:ver para mostrar los procesos disponibles." />
      : processesNotice ? <p className="control-notice error" role="alert">{processesNotice}</p>
        : recentProcesses.length ? <div className="table-scroll"><table className="measurement-static-table"><thead><tr><th>Tipo</th><th>Estado</th><th>Creado</th><th>Duración</th><th className="num">Registros</th></tr></thead><tbody>
          {recentProcesses.map(process => <tr key={process.id}><td>{processLabels[process.tipo] || process.tipo} · #{process.id}</td><td><ProcessStateBadge state={process.estado} /></td>
            <td>{formatClientDateTime(process.creado_en)}</td><td>{processDuration(process.duracion_ms)}</td><td className="num">{process.procesados ?? '—'}</td></tr>)}
        </tbody></table></div>
        : <EmptyState title="Sin procesos disponibles" detail="No hay procesos de preparación visibles para esta medición. El endpoint actual no expone el historial completo de cargas y procesamiento." />}
  </section>;
  const renderSchedule = () => {
    const meltwater = activeSources.find(source => source.origen === 'meltwater');
    if (!meltwater) {
      const scraperConfigured = activeSources.some(source => ['scraper', 'scrapper', 'googlenews'].includes(source.origen));
      return <EmptyState title="Sin programación disponible" detail={scraperConfigured
        ? 'La programación de Scraper no está disponible en el contrato de detalle actual.'
        : 'Esta medición no tiene la fuente Meltwater activa.'} />;
    }
    const schedule = measurement.programacion_meltwater;
    return <dl className="measurement-detail-kv measurement-schedule-kv">
      <dt>Fuente</dt><dd>API Meltwater</dd><dt>Estado</dt><dd><span className={`badge ${schedule?.activa ? 'ok' : 'warn'}`}><span className="d" />{schedule?.activa ? 'Activa' : 'Sin programación activa'}</span></dd>
      <dt>ID de búsqueda</dt><dd>{meltwater.config?.busqueda_id || '—'}</dd>
      {schedule?.activa && <><dt>Frecuencia</dt><dd>{schedule.frecuencia_min} minutos</dd><dt>Inicio</dt><dd>{schedule.inicio ? formatClientDateTime(schedule.inicio) : '—'}</dd><dt>Fin</dt><dd>{schedule.fin ? formatClientDateTime(schedule.fin) : '—'}</dd></>}
    </dl>;
  };
  const renderSummary = () => <div className="measurement-summary-stack">
    {renderPipe()}
    {renderSourceStatus()}
    <div className="measurement-detail-grid">
      <section className="panel measurement-detail-section">
        <div className="card-head"><h2>Registros por fecha de publicación</h2><span className="sub">No hay datos agregados disponibles para graficar.</span></div>
        <EmptyState title="Gráfica pendiente de datos" detail="La API actual no expone registros ni agregados por fecha de publicación. No se muestran cifras simuladas." />
      </section>
      <section className="panel measurement-detail-section"><div className="card-head"><h2>Programación</h2><button className="button small" type="button" onClick={() => selectTab('scraper')}>Scraper</button></div>{renderSchedule()}</section>
    </div>
    {renderLatestProcesses()}
  </div>;
  const renderConfiguration = () => <div className="measurement-detail-grid">
    <section className="panel measurement-detail-section"><div className="card-head"><h2>Resumen</h2></div><dl className="measurement-detail-kv">
      <dt>Cuenta</dt><dd>{measurement.cuenta_nombre || '—'}</dd><dt>Estado</dt><dd><StateBadge state={measurement.estado_id} /></dd>
      <dt>Coyuntura</dt><dd>{measurement.coyuntura ? 'Sí' : 'No'}</dd><dt>Fuentes activas</dt><dd><MeasurementSources sources={activeSources.map(source => source.origen)} /></dd>
      <dt>Creada</dt><dd>{measurement.creado_en ? formatClientDateTime(measurement.creado_en) : '—'}</dd><dt>Actualizada</dt><dd>{measurement.actualizado_en ? formatClientDateTime(measurement.actualizado_en) : '—'}</dd>
    </dl></section>
    <section className="panel measurement-detail-section"><h2>Configuración de análisis</h2><dl className="measurement-detail-kv">
      <dt>Coyuntura</dt><dd>{measurement.coyuntura ? 'Sí' : 'No'}</dd><dt>Clusters × subclusters</dt><dd>{measurement.num_clusters} × {measurement.num_subclusters}</dd>
      <dt>Tipo de análisis</dt><dd>{measurement.tipo_analisis || '—'}</dd><dt>Ventana temporal</dt><dd>{measurement.ventana_desde ? `Desde ${formatClientDateTime(measurement.ventana_desde)}` : 'Toda la historia'}</dd>
      <dt>Publicación automática</dt><dd>{measurement.auto_publicar ? 'Sí' : 'No'}</dd><dt>Preclustering</dt><dd>{measurement.precluster_activo ? 'Activo' : 'No'}</dd>
      <dt>Parámetros X</dt><dd>{measurement.x_num_menciones ?? 0} menciones · {measurement.x_num_cuentas ?? 0} cuentas</dd>
      </dl></section>
    <section className="panel measurement-detail-section"><h2>Fuentes configuradas</h2>{renderSourceDetails()}</section>
  </div>;
  const renderPending = (title: string, detail: string) => <section className="panel measurement-detail-section"><h2>{title}</h2><EmptyState title={`${title} pendiente`} detail={detail} /></section>;
  return <>
    {loading && <><PageHeading title="Cargando medición…" description="Recuperando información de PostgreSQL." /><section className="panel"><EmptyState title="Cargando medición…" /></section></>}
    {error && <><PageHeading title="Detalle de medición" description="No se pudo recuperar la información." /><section className="panel"><p className="control-notice error" role="alert">{error}</p></section></>}
    {!loading && !error && !measurement && <><PageHeading title="Medición no encontrada" description="No hay una medición disponible para este identificador." /><section className="panel"><EmptyState title="Medición no encontrada" /></section></>}
    {measurement && <>
      <section className="measurement-hero">
        <div className="measurement-hero-meta"><StateBadge state={measurement.estado_id} /><span className="badge outline">{measurement.coyuntura ? 'Coyuntura' : 'Seguimiento regular'}</span></div>
        <div className="measurement-hero-main"><div><h1>{measurement.nombre}</h1><p>{measurement.cuenta_nombre || 'Cuenta no disponible'} · creada {measurement.creado_en ? formatClientDateTime(measurement.creado_en) : '—'}</p></div>
          <div className="measurement-hero-actions">
            {canEdit && measurement.estado_id !== -1 && <button className="button primary" type="button" onClick={() => navigate(`/mediciones/${id}/editar`)}><Icon name="edit" size={15} /> Editar</button>}
             <button className="button primary" type="button" disabled={!canExecute || !fileSourceActive}
              title={!canExecute ? 'Requiere mediciones:ejecutar' : fileSourceActive ? 'Cargar archivos en esta medición' : 'La fuente Archivos está inactiva en esta medición'}
              onClick={() => setUploadOpen(true)}><Icon name="upload" size={15} /> Nueva carga</button>
            <button className="button" type="button" disabled title="Pendiente: la API no ofrece eliminación lógica de mediciones"><Icon name="trash" size={15} /> Eliminar</button>
            <button className="button" type="button" disabled title="Pendiente: la API no ofrece un informe para esta medición"><Icon name="chart" size={15} /> Ver informe</button>
          </div>
        </div>
      </section>
      <div className="tabs" role="tablist" aria-label="Secciones de la medición">
        {MEASUREMENT_DETAIL_TABS.map(([key, label, icon], index) => <button key={key} id={`measurement-tab-${key}`} type="button" className={`tab${section === key ? ' active' : ''}`} role="tab" aria-selected={section === key} aria-controls="measurement-tab-panel" tabIndex={section === key ? 0 : -1}
          onClick={() => selectTab(key)} onKeyDown={event => {
            if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? MEASUREMENT_DETAIL_TABS.length - 1
              : (index + (event.key === 'ArrowRight' ? 1 : MEASUREMENT_DETAIL_TABS.length - 1)) % MEASUREMENT_DETAIL_TABS.length;
            const nextTab = MEASUREMENT_DETAIL_TABS[nextIndex];
            document.getElementById(`measurement-tab-${nextTab[0]}`)?.focus();
            selectTab(nextTab[0]);
          }}><Icon name={icon} size={15} /> {label}</button>)}
      </div>
      <div id="measurement-tab-panel" role="tabpanel" aria-labelledby={`measurement-tab-${section}`}>
        {section === 'resumen' && renderSummary()}
        {section === 'cargas' && <MeasurementFileHistory measurementId={measurement.id} formatDate={formatClientDateTime} sources={measurement.fuentes || []} refreshKey={filesRefreshKey} />}
        {section === 'scraper' && renderPending('Scraper', 'La configuración e historial real de scrapers no está disponible en el contrato de detalle actual.')}
        {section === 'fiscalizacion' && renderPending('Fiscalización', 'La API actual no expone los registros ni el flujo de fiscalización de esta medición.')}
        {section === 'registros' && renderPending('Registros', 'La API actual no expone la consulta de registros de la medición.')}
        {section === 'procesamiento' && renderPending('Procesamiento', 'El endpoint disponible solo muestra procesos operativos seleccionados; no expone el historial completo de análisis y procesamiento.')}
        {section === 'informe' && renderPending('Informe', 'No hay un endpoint de informe de esta medición disponible en el contrato actual.')}
        {section === 'configuracion' && renderConfiguration()}
      </div>
      {uploadOpen && <MeasurementUploadDialog measurementId={measurement.id} sources={measurement.fuentes || []}
        canExecute={canExecute} canViewFormats={canViewFormats} onClose={() => setUploadOpen(false)}
        onViewPrevious={() => { setFilesRefreshKey(value => value + 1); selectTab('cargas'); }}
        onQueued={() => { setFilesRefreshKey(value => value + 1); selectTab('cargas'); }} />}
    </>}
  </>;
}

type EntityFilter = { label: string; options: string[] };
type EntitySpec = { heading: string; description: string; create?: string; filters?: EntityFilter[]; columns: string[] };
const ENTITY_SPECS: Record<string, EntitySpec> = {
  '/clientes': { heading: 'Clientes', description: 'Organizaciones para las que Syntra realiza escucha social. Cada cliente agrupa sus cuentas de monitoreo.', create: 'Nuevo cliente', filters: [{ label: 'Sector', options: [] }], columns: ['Cliente', 'Sector', 'Cuentas', 'Contacto'] },
  '/cuentas': { heading: 'Cuentas', description: 'Unidad de monitoreo de un cliente (marca, producto o tema). Define los prompts base de clusters y temas finales.', create: 'Nueva cuenta', filters: [{ label: 'Cliente', options: [] }], columns: ['Cuenta', 'Cliente', 'Grupos con acceso', 'Mediciones'] },
  '/prompts': { heading: 'Prompts por defecto', description: 'Plantillas base para clusters, temas finales, relevancia y sentimiento. Los de relevancia y sentimiento pueden ser específicos de una red social; en cada medición se ajustan por red.', create: 'Nuevo prompt', filters: [{ label: 'Tipo', options: ['Clusters', 'Temas finales', 'Relevancia', 'Sentimiento'] }, { label: 'Red', options: ['General (todas)', 'X', 'TikTok', 'YouTube', 'Facebook', 'Instagram', 'Medios y web'] }], columns: ['Prompt', 'Tipo', 'Red', 'Versión', 'Por defecto'] },
  '/regex': { heading: 'Regex', description: 'Condiciones para etiquetar registros, filtrarlos en fiscalización y registros, y preclasificarlos (preclustering) según el orden definido en cada medición. Al guardar se valida contra un texto de prueba.', create: 'Nueva regex', columns: ['Regex', 'Texto de prueba', 'Versión'] },
  '/paises': { heading: 'Países (Google News)', description: 'Países disponibles para las búsquedas de Google News en los procesos de scraping. El país define el portal (edición local) de Google News y el idioma de los resultados.', create: 'Nuevo país', columns: ['País', 'Idioma', 'Edición de Google News', 'Procesos que lo usan'] },
  '/usuarios': { heading: 'Usuarios', description: 'Personas con acceso a la plataforma. El rol define qué pueden hacer; los grupos definen qué cuentas pueden ver.', create: 'Nuevo usuario', filters: [{ label: 'Rol', options: [] }], columns: ['Usuario', 'Rol', 'Grupos', 'Cuentas visibles', 'Último acceso'] },
  '/roles': { heading: 'Roles y accesos', description: 'Matriz de permisos por módulo y acción. Los roles con acceso global ven todas las cuentas; los demás, solo las de sus grupos.', create: 'Nuevo rol', columns: ['Rol', 'Alcance', 'Permisos', 'Usuarios'] },
  '/grupos': { heading: 'Grupos de usuarios', description: 'Asocia usuarios con cuentas. Un usuario sin rol global solo verá las cuentas (y sus mediciones e informes) de sus grupos.', create: 'Nuevo grupo', columns: ['Grupo', 'Usuarios', 'Cuentas asociadas'] },
};
const ENTITY_STATES = [['vig', 'Vigentes'], ['act', 'Activos'], ['ina', 'Inactivos'], ['del', 'Eliminados']];
const CREATION_ROUTES: Record<string, string> = { '/clientes': '/clientes/nuevo', '/cuentas': '/cuentas/nueva', '/prompts': '/prompts/nuevo', '/regex': '/regex/nueva', '/paises': '/paises/nuevo', '/usuarios': '/usuarios/nuevo', '/roles': '/roles/nuevo', '/grupos': '/grupos/nuevo' };
type CreationField = { name: string; label: string; type: 'text' | 'email' | 'number' | 'textarea' | 'select' | 'checkbox' | 'catalog'; required?: boolean; placeholder?: string; help?: string; options?: Array<[string, string]>; min?: number; max?: number; rows?: number; wide?: boolean; minLength?: number };
type CreationSpec = { title: string; description: string; fields: CreationField[]; special?: 'permissions' | 'group-pickers' };
const SECTOR_OPTIONS: Array<[string, string]> = ['Consultoría política', 'Gobierno estatal', 'Gobierno municipal', 'Partido político', 'Campaña electoral', 'Poder legislativo', 'Sociedad civil', 'Medios de comunicación', 'Otro'].map(value => [value, value]);
const STATE_OPTIONS: Array<[string, string]> = ['Aguascalientes', 'Baja California', 'Baja California Sur', 'Campeche', 'Chiapas', 'Chihuahua', 'Ciudad de México', 'Coahuila', 'Colima', 'Durango', 'Estado de México', 'Guanajuato', 'Guerrero', 'Hidalgo', 'Jalisco', 'Michoacán', 'Morelos', 'Nayarit', 'Nuevo León', 'Oaxaca', 'Puebla', 'Querétaro', 'Quintana Roo', 'San Luis Potosí', 'Sinaloa', 'Sonora', 'Tabasco', 'Tamaulipas', 'Tlaxcala', 'Veracruz', 'Yucatán', 'Zacatecas', 'México'].map(value => [value, value]);
const NETWORK_OPTIONS: Array<[string, string]> = [['x', 'X'], ['tiktok', 'TikTok'], ['youtube', 'YouTube'], ['facebook', 'Facebook'], ['instagram', 'Instagram'], ['medios', 'Medios y web']];
const CREATION_SPECS: Record<string, CreationSpec> = {
  '/clientes': { title: 'Nuevo cliente', description: ENTITY_SPECS['/clientes'].description, fields: [
    { name: 'nombre', label: 'Nombre del cliente', type: 'text', required: true, placeholder: 'Ej. Ágora Consultores Políticos' }, { name: 'nit', label: 'RFC', type: 'text', placeholder: 'ABC123456XY0' }, { name: 'sector', label: 'Sector', type: 'select', options: SECTOR_OPTIONS }, { name: 'contacto', label: 'Correo de contacto', type: 'email', placeholder: 'contacto@cliente.mx' }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] },
  ] },
  '/cuentas': { title: 'Nueva cuenta', description: ENTITY_SPECS['/cuentas'].description, fields: [
    { name: 'nombre', label: 'Nombre de la cuenta', type: 'text', required: true, placeholder: 'Ej. Gob. Nuevo León · Nombre del gobernador' }, { name: 'cliente', label: 'Cliente asociado', type: 'catalog', required: true, help: 'Selecciona un cliente cuando exista el catálogo.' }, { name: 'marca', label: 'Actor o término principal', type: 'text', placeholder: 'Ej. el gobernador Salazar', help: 'Persona, institución o partido de referencia en el análisis.' }, { name: 'estadoFederal', label: 'Entidad federativa', type: 'select', options: STATE_OPTIONS }, { name: 'taxonomia', label: 'Taxonomía base', type: 'select', options: [['gobierno', 'Gobierno estatal'], ['comparativo', 'Comparativo de gobernadores'], ['electoral', 'Electoral / partidos']] }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'promptClusters', label: 'Prompt de clusters', type: 'textarea', required: true, minLength: 20, rows: 5, wide: true, help: 'Prompt personalizado de esta cuenta.' }, { name: 'promptTemas', label: 'Prompt de temas finales', type: 'textarea', required: true, minLength: 20, rows: 5, wide: true, help: 'Prompt personalizado de esta cuenta.' },
  ] },
  '/prompts': { title: 'Nuevo prompt', description: ENTITY_SPECS['/prompts'].description, fields: [
    { name: 'nombre', label: 'Nombre', type: 'text', required: true }, { name: 'tipo', label: 'Tipo', type: 'select', required: true, options: [['cluster', 'Clusters'], ['temas', 'Temas finales'], ['relevancia', 'Relevancia'], ['sentimiento', 'Sentimiento']] }, { name: 'red', label: 'Red social', type: 'select', options: [['', 'General (todas las redes)'], ...NETWORK_OPTIONS], help: 'Los prompts de relevancia y sentimiento pueden tener un ajuste por red.' }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'porDefecto', label: 'Usar como prompt por defecto de su tipo y red', type: 'checkbox', wide: true }, { name: 'contenido', label: 'Contenido del prompt', type: 'textarea', required: true, minLength: 20, rows: 12, wide: true, help: 'Mínimo 20 caracteres. Variables disponibles en el mockup: {{cuenta}}, {{num_clusters}}, {{num_subclusters}}, {{fecha_inicio}}, {{tipo_analisis}}, {{red}}.' },
  ] },
  '/regex': { title: 'Nueva regex', description: ENTITY_SPECS['/regex'].description, fields: [
    { name: 'nombre', label: 'Nombre', type: 'text', required: true, placeholder: 'Ej. Crisis del agua' }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'condicion', label: 'Condición (expresión regular)', type: 'text', required: true, placeholder: String.raw`\b(agua|sequía|pipas?)\b`, help: 'La expresión se valida en este navegador y no se ejecuta sobre registros.' }, { name: 'ignorarMayusculas', label: 'Ignorar mayúsculas', type: 'checkbox' }, { name: 'prueba', label: 'Texto de prueba', type: 'textarea', required: true, rows: 3, wide: true, placeholder: 'Pega aquí un texto que la regex debe encontrar.' }, { name: 'descripcion', label: 'Descripción', type: 'text', wide: true, placeholder: 'Para qué sirve esta regex' },
  ] },
  '/paises': { title: 'Nuevo país', description: ENTITY_SPECS['/paises'].description, fields: [
    { name: 'nombre', label: 'Nombre del país', type: 'text', required: true, placeholder: 'Ej. México' }, { name: 'codigo', label: 'Código ISO (2 letras)', type: 'text', required: true, placeholder: 'MX', max: 2, help: 'ISO 3166-1 alfa-2. Define el portal de Google News.' }, { name: 'idioma', label: 'Idioma de los resultados', type: 'select', options: [['es-419', 'Español (Latinoamérica)'], ['es', 'Español (España)'], ['en-US', 'Inglés (EE. UU.)'], ['pt-BR', 'Portugués (Brasil)'], ['fr', 'Francés']] }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] },
  ] },
  '/usuarios': { title: 'Nuevo usuario', description: ENTITY_SPECS['/usuarios'].description, fields: [
    { name: 'nombre', label: 'Nombre completo', type: 'text', required: true }, { name: 'email', label: 'Correo corporativo', type: 'email', required: true }, { name: 'telefono', label: 'Teléfono', type: 'text', placeholder: '+57 300 000 0000' }, { name: 'rol', label: 'Rol', type: 'catalog', required: true, help: 'Los roles aparecerán cuando exista el catálogo correspondiente.' }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'grupos', label: 'Grupos de usuarios', type: 'catalog', wide: true, help: 'Los grupos disponibles aparecerán cuando exista el catálogo correspondiente.' },
  ] },
  '/roles': { title: 'Nuevo rol', description: ENTITY_SPECS['/roles'].description, special: 'permissions', fields: [
    { name: 'nombre', label: 'Nombre del rol', type: 'text', required: true }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'descripcion', label: 'Descripción', type: 'textarea', rows: 3, wide: true }, { name: 'verTodas', label: 'Acceso a todas las cuentas — ignora la restricción por grupos de usuarios', type: 'checkbox', wide: true }, { name: 'configCompleta', label: 'Configuración completa de mediciones — programación automática, prompts personalizados y criterios de bots', type: 'checkbox', wide: true },
  ] },
  '/grupos': { title: 'Nuevo grupo', description: ENTITY_SPECS['/grupos'].description, special: 'group-pickers', fields: [
    { name: 'nombre', label: 'Nombre del grupo', type: 'text', required: true }, { name: 'estado', label: 'Estado', type: 'select', options: [['1', 'Activo'], ['0', 'Inactivo (borrador)']] }, { name: 'descripcion', label: 'Descripción', type: 'textarea', rows: 3, wide: true },
  ] },
};

export function CreationFormPage({ path, editId }: { path: string; editId?: number }) {
  const navigate = useNavigate();
  const toast = useToast();
  const spec = CREATION_SPECS[path];
  const [values, setValues] = useState<Record<string, any>>({ estado: '1', estadoFederal: 'México', taxonomia: 'gobierno', idioma: 'es-419', tipo: 'cluster', red: '', sources: {}, permissions: {} });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState('');
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [etag, setEtag] = useState('');
  const [saving, setSaving] = useState(false);
  const clientLive = path === '/clientes' && !previewMode;
  const formTitle = editId ? 'Editar cliente' : spec?.title || 'Formulario';
  useEffect(() => {
    if (!clientLive || !editId) return;
    let live = true;
    api(`/clientes/${editId}`).then(async response => {
      const data: Cliente = await response.json();
      if (live) {
        setEtag(response.headers.get('ETag') || '');
        setValues({ nombre: data.nombre, nit: data.rfc || '', sector: data.sector || '', contacto: data.contacto || '', estado: String(data.estado_id) });
      }
    }).catch(error => { if (live) setNotice(error instanceof Error ? error.message : 'No se pudo cargar el cliente.'); });
    return () => { live = false; };
  }, [clientLive, editId]);
  if (!spec) return <PageHeading title="Formulario no disponible" />;
  const baseRoute = path;
  const update = (name: string, value: unknown) => { setDirty(true); setValues(current => ({ ...current, [name]: value })); setErrors(current => ({ ...current, [name]: '' })); setNotice(''); };
  const validate = () => {
    const next: Record<string, string> = {};
    for (const field of spec.fields) {
      const value = values[field.name];
      if (field.required && (typeof value !== 'string' || !value.trim())) next[field.name] = field.name === 'cliente' ? 'Selecciona el cliente' : field.name === 'rol' ? 'Selecciona un rol' : `${field.label} es obligatorio`;
      else if (field.type === 'email' && value && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) next[field.name] = 'Correo no válido';
      else if (field.minLength && value && value.trim().length < field.minLength) next[field.name] = `Debe tener al menos ${field.minLength} caracteres`;
      else if (field.name === 'codigo' && value && !/^[a-z]{2}$/i.test(value)) next[field.name] = 'Ingresa un código ISO de dos letras';
    }
    if (path === '/regex' && values.condicion) {
      try { const regex = new RegExp(values.condicion, values.ignorarMayusculas ? 'i' : ''); if (values.prueba && !regex.test(values.prueba)) next.prueba = 'La expresión no coincide con el texto de prueba'; }
      catch (error) { next.condicion = `Expresión inválida: ${error instanceof Error ? error.message : 'revisa la sintaxis'}`; }
    }
    if (path === '/prompts' && values.porDefecto && values.estado === '0') next.estado = 'Un prompt por defecto debe estar activo';
    return next;
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (saving) return;
    const next = validate(); setErrors(next);
    if (Object.keys(next).length) { setNotice('Revisa los campos marcados. No se ha guardado información.'); if (clientLive) toast('Revisa los campos marcados', Object.values(next)[0], 'err'); return; }
    if (!clientLive) { setNotice('El guardado aún no está disponible. Tus datos siguen en este formulario y no se ha creado ningún registro.'); return; }
    const body = { nombre: String(values.nombre || '').trim(), rfc: String(values.nit || '').trim() || null, sector: String(values.sector || '').trim() || null, contacto: String(values.contacto || '').trim() || null, ...(!editId ? { estado_id: Number(values.estado || '1') } : {}) };
    setSaving(true);
    try {
      await api(editId ? `/clientes/${editId}` : '/clientes', { method: editId ? 'PATCH' : 'POST', headers: editId ? { 'If-Match': etag } : undefined, body: JSON.stringify(body) });
      toast(editId ? 'Cambios guardados' : 'Cliente creado', body.nombre);
      navigate(editId ? `/clientes/${editId}` : '/clientes');
    } catch (error) { toast('No se pudo guardar el cliente', clientError(error, 'Revisa los datos e inténtalo de nuevo.'), 'err'); }
    finally { setSaving(false); }
  };
  const cancel = () => { if (dirty) setConfirmDiscard(true); else navigate(`${baseRoute}${previewMode ? '?preview=1' : ''}`); };
  const renderField = (field: CreationField) => {
    const invalid = Boolean(errors[field.name]);
    const common = { id: `create-${field.name}`, name: field.name, value: values[field.name] ?? '', onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => update(field.name, event.target.value), 'aria-invalid': invalid, 'aria-describedby': invalid ? `create-${field.name}-error` : undefined };
    if (field.type === 'checkbox') return <label className={`create-check${field.wide ? ' span2' : ''}`} key={field.name}><input type="checkbox" checked={Boolean(values[field.name])} onChange={event => update(field.name, event.target.checked)} /><span>{field.label}</span></label>;
    if (field.type === 'catalog') return <div className={`field${field.wide ? ' span2' : ''}`} key={field.name}><label htmlFor={common.id}>{field.label}{field.required && <span className="required-mark"> *</span>}</label><select {...common} disabled><option value="">{field.name === 'cliente' ? 'Selecciona un cliente' : field.name === 'rol' ? 'Selecciona un rol' : 'No hay opciones disponibles'}</option></select>{field.help && <span className="field-help">{field.help}</span>}{invalid && <span id={`create-${field.name}-error`} className="field-error" role="alert">{errors[field.name]}</span>}</div>;
    return <div className={`field${field.wide ? ' span2' : ''}${invalid ? ' invalid' : ''}`} key={field.name}><label htmlFor={common.id}>{field.label}{field.required && <span className="required-mark"> *</span>}</label>{clientLive && field.name === 'sector' ? <input {...common} type="text" placeholder="Sector" /> : field.type === 'select' ? <select {...common}>{(field.options || []).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select> : field.type === 'textarea' ? <textarea {...common} rows={field.rows || 4} placeholder={field.placeholder} /> : <input {...common} type={field.type} placeholder={field.placeholder} min={field.min} max={field.max} maxLength={field.max} />}{field.help && <span className="field-help">{field.help}</span>}{invalid && <span id={`create-${field.name}-error`} className="field-error" role="alert">{errors[field.name]}</span>}</div>;
  };
  const setPermission = (module: string, action: string, enabled: boolean) => { setDirty(true); setValues(current => ({ ...current, permissions: { ...current.permissions, [`${module}:${action}`]: enabled } })); };
  return <>
    <PageHeading title={formTitle} description={spec.description} />
    <form className="panel creation-form" onSubmit={submit} noValidate>
      <div className="panel-heading"><h2>{formTitle}</h2><span className="panel-sub">Los campos con * son obligatorios</span></div>
      <div className="creation-form-body"><div className="form-grid">{spec.fields.filter(field => !(editId && field.name === 'estado') && !(path === '/prompts' && field.name === 'red' && !['relevancia', 'sentimiento'].includes(values.tipo))).map(renderField)}</div>
        {spec.special === 'permissions' && <section className="field span2 permission-section"><label>Permisos por módulo</label><p className="field-help">Selecciona los permisos que tendrá este rol. No se aplicarán hasta que exista persistencia.</p><div className="table-wrap permission-wrap"><table className="permission-table"><thead><tr><th>Módulo</th>{permissionActions.map(actionItem => <th key={actionItem[1]}>{actionItem[1]}</th>)}</tr></thead><tbody>{modulesForPermissions.map(moduleItem => <tr key={moduleItem[0]}><th scope="row">{moduleItem[1]}</th>{permissionActions.map(actionItem => <td key={actionItem[0]}><input type="checkbox" aria-label={`${moduleItem[1]}: ${actionItem[1]}`} checked={Boolean(values.permissions[`${moduleItem[0]}:${actionItem[0]}`])} onChange={event => setPermission(moduleItem[0], actionItem[0], event.target.checked)} /></td>)}</tr>)}</tbody></table></div></section>}
        {spec.special === 'group-pickers' && <div className="dual-picker span2"><section className="picklist"><div className="panel-heading"><h3>Usuarios</h3></div><EmptyState title="Sin usuarios disponibles" detail="Los usuarios aparecerán aquí cuando exista el catálogo correspondiente." /></section><section className="picklist"><div className="panel-heading"><h3>Cuentas</h3></div><EmptyState title="Sin cuentas disponibles" detail="Las cuentas aparecerán aquí cuando exista el catálogo correspondiente." /></section></div>}
        {path === '/usuarios' && <div className="form-note span2"><Icon name="info" size={16} /> El mockup contempla una invitación al usuario al guardar; no se enviará ningún correo en esta etapa.</div>}
        {path === '/regex' && values.condicion && values.prueba && !errors.condicion && !errors.prueba && <div className="regex-result span2" role="status">{(() => { try { return new RegExp(values.condicion, values.ignorarMayusculas ? 'i' : '').test(values.prueba) ? 'La expresión coincide con el texto de prueba.' : 'La expresión no coincide con el texto de prueba.'; } catch { return 'Expresión inválida.'; } })()}</div>}
        {notice && <p className={`control-notice span2${Object.keys(errors).length ? ' error' : ''}`} role="status">{notice}</p>}
      </div>
      <div className="form-actions creation-actions"><button type="button" className="button" onClick={cancel}><Icon name="arrow" size={15} /> Cancelar</button><button type="submit" className="button primary" disabled={saving}><Icon name="check" size={15} /> {saving ? 'Guardando…' : 'Guardar'}</button></div>
    </form>
    {confirmDiscard && <div className="command-scrim"><section className="command-panel discard-dialog" role="dialog" aria-modal="true" aria-labelledby="discard-form-title"><div className="panel-heading"><h2 id="discard-form-title">¿Descartar los cambios?</h2></div><p>Los datos escritos en este formulario se perderán y aún no se guardaron.</p><div className="form-actions"><button className="button" type="button" onClick={() => setConfirmDiscard(false)}>Conservar formulario</button><button className="button danger-button" type="button" onClick={() => navigate(`${baseRoute}${previewMode ? '?preview=1' : ''}`)}>Descartar y volver</button></div></section></div>}
  </>;
}

function GenericModule({ path, title }: { path: string; title: string }) {
  const spec = ENTITY_SPECS[path];
  const [query, setQuery] = useState('');
  const [state, setState] = useState('vig');
  const [filters, setFilters] = useState<Record<string, string>>({});
  if (!spec) return <PageHeading title={title} />;
  const hasFilters = Boolean(query.trim() || Object.values(filters).some(Boolean) || state !== 'vig');
  return <>
    <PageHeading title={spec.heading} description={spec.description} action={spec.create ? { label: spec.create, icon: 'plus', path: CREATION_ROUTES[path] } : undefined} />
    <section className="panel entity-list-panel">
      <div className="module-toolbar entity-toolbar" aria-label={`Filtros de ${spec.heading}`}>
        <label className="search-field"><Icon name="search" size={16} /><input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={`Buscar ${spec.heading.toLowerCase()}…`} aria-label={`Buscar ${spec.heading.toLowerCase()}`} /></label>
        {spec.filters?.map(filter => <select key={filter.label} aria-label={filter.label} value={filters[filter.label] ?? ''} onChange={event => setFilters(previous => ({ ...previous, [filter.label]: event.target.value }))}><option value="">{filter.label}: todos</option>{filter.options.map(option => <option key={option} value={option}>{option}</option>)}</select>)}
        <div className="seg status-segment" role="group" aria-label={`Filtrar ${spec.heading.toLowerCase()} por estado`}>{ENTITY_STATES.map(([key, label]) => <button type="button" key={key} className={state === key ? 'on' : ''} aria-pressed={state === key} onClick={() => setState(key)}>{label}<span className="n">—</span></button>)}</div>
      </div>
      <div className="table-wrap"><table className="data-table"><thead><tr>{[...spec.columns, 'Estado', 'Actualizado', 'Acciones'].map(column => <th key={column}>{column}</th>)}</tr></thead><tbody><tr><td colSpan={spec.columns.length + 3} className="empty-cell"><EmptyState title={hasFilters ? 'Sin resultados para los filtros' : `Aún no hay ${spec.heading.toLowerCase()}`} detail={query || Object.values(filters).some(Boolean) ? 'Prueba con otros criterios de búsqueda.' : 'El contenido aparecerá cuando haya información disponible.'} /></td></tr></tbody></table></div>
    </section>
  </>;
}

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

function ClientEditRoute() {
  const { id } = useParams();
  return <CreationFormPage path="/clientes" editId={Number(id)} />;
}

const AUDIT_MODULES = ['Cliente', 'Cuenta', 'Usuario', 'Rol', 'Grupo', 'Prompt', 'Cruce', 'Regex', 'País', 'Actor', 'Formato', 'Medición', 'Scraper', 'Fiscalización', 'Registro', 'Configuración de tarjetas', 'Proceso', 'Informe'];
const AUDIT_ACTIONS = ['Creación', 'Actualización', 'Actualización masiva', 'Eliminación lógica', 'Restauración', 'Cambio de estado', 'Ejecución', 'Exportación'];
function AuditPage() {
  const [query, setQuery] = useState('');
  const [module, setModule] = useState('');
  const [user, setUser] = useState('');
  const [action, setAction] = useState('');
  const [period, setPeriod] = useState('30');
  const [notice, setNotice] = useState('');
  return <>
    <PageHeading title="Log de auditoría" description="Trazabilidad de todo lo que se hace en la plataforma: clientes, cuentas, usuarios, roles, configuración de tarjetas, mediciones y procesos." action={{ label: 'Exportar log', icon: 'download', onClick: () => setNotice('No hay eventos de auditoría para exportar.') }} />
    <div className="dashboard-grid audit-charts"><section className="panel"><header className="panel-heading"><div><h2>Actividad diaria</h2><span className="panel-sub">últimos 30 días</span></div></header><div className="chart-placeholder"><EmptyState title="Sin datos para el periodo" detail="La gráfica aparecerá cuando haya eventos registrados." /></div></section><section className="panel"><header className="panel-heading"><h2>Eventos por módulo</h2></header><EmptyState title="Sin datos para mostrar" detail="Los módulos aparecerán cuando haya eventos registrados." /></section></div>
    <section className="panel entity-list-panel">
      <div className="module-toolbar audit-toolbar" aria-label="Filtros del log de auditoría"><label className="search-field"><Icon name="search" size={16} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar en el log…" aria-label="Buscar en el log" /></label><select aria-label="Módulo" value={module} onChange={event => setModule(event.target.value)}><option value="">Módulo: todos</option>{AUDIT_MODULES.map(item => <option key={item}>{item}</option>)}</select><select aria-label="Usuario" value={user} onChange={event => setUser(event.target.value)}><option value="">Usuario: todos</option></select><select aria-label="Acción" value={action} onChange={event => setAction(event.target.value)}><option value="">Acción: todas</option>{AUDIT_ACTIONS.map(item => <option key={item}>{item}</option>)}</select><select aria-label="Periodo" value={period} onChange={event => setPeriod(event.target.value)}><option value="1">Últimas 24 h</option><option value="7">Últimos 7 días</option><option value="30">Últimos 30 días</option><option value="365">Último año</option></select></div>
      {notice && <p className="control-notice" role="status">{notice}</p>}
      <div className="table-wrap"><table className="data-table audit-table"><thead><tr>{['Fecha', 'Usuario', 'Módulo', 'Acción', 'Entidad', 'Cambios', ''].map((column, index) => <th key={`${column}-${index}`}>{column}</th>)}</tr></thead><tbody><tr><td colSpan={7} className="empty-cell"><EmptyState title={query || module || user || action ? 'Sin eventos para los filtros' : 'Sin eventos de auditoría'} detail="Amplía el rango de fechas o limpia los filtros." /></td></tr></tbody></table></div>
      <div className="table-pager"><span>— eventos</span><div><button type="button" disabled aria-label="Página anterior"><Icon name="chevron" size={16} /></button><span>— / —</span><button type="button" disabled aria-label="Página siguiente"><Icon name="chevron" size={16} /></button></div></div>
    </section>
  </>;
}

function GlobalSearch({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);
  if (!open) return null;
  const items = navigation.flatMap(group => group.items).filter(item => item.label.toLowerCase().includes(query.trim().toLowerCase()));
  const to = (path: string) => `${path}${previewMode ? '?preview=1' : ''}`;
  return <div className="command-scrim command-search-scrim" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="command-panel command-search-panel" role="dialog" aria-modal="true" aria-label="Búsqueda global">
      <div className="command-search-field"><Icon name="search" size={18} /><input ref={inputRef} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Busca secciones de Syntra…" aria-label="Buscar secciones" /><button type="button" className="icon-button" onClick={onClose} aria-label="Cerrar búsqueda"><Icon name="close" size={16} /></button></div>
      <div className="command-results" aria-live="polite">{items.length ? items.map(item => <Link key={item.path} to={to(item.path)} onClick={onClose}><Icon name={item.icon} size={17} />{item.label}<Icon name="chevron" size={15} /></Link>) : <EmptyState title="Sin resultados" detail="Prueba con otro término." />}</div>
      <p className="command-hint"><kbd>Esc</kbd> Cerrar · Selecciona una sección</p>
    </section>
  </div>;
}

function HeaderPopover({ id, anchorRef, panelRef, role, labelledBy, children, onKeyDown }: {
  id: string;
  anchorRef: RefObject<HTMLButtonElement | null>;
  panelRef: RefObject<HTMLDivElement | null>;
  role: 'dialog' | 'menu';
  labelledBy: string;
  children: React.ReactNode;
  onKeyDown?: (event: React.KeyboardEvent<HTMLDivElement>) => void;
}) {
  const [position, setPosition] = useState<CSSProperties>({ visibility: 'hidden' });
  useLayoutEffect(() => {
    const updatePosition = () => {
      const anchor = anchorRef.current;
      const panel = panelRef.current;
      if (!anchor || !panel) return;
      const anchorRect = anchor.getBoundingClientRect();
      const panelRect = panel.getBoundingClientRect();
      const left = Math.min(Math.max(12, anchorRect.right - panelRect.width), window.innerWidth - panelRect.width - 12);
      const below = anchorRect.bottom + 8;
      const top = below + panelRect.height <= window.innerHeight - 12 ? below : Math.max(12, anchorRect.top - panelRect.height - 8);
      setPosition({ top, left, visibility: 'visible' });
    };
    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [anchorRef, panelRef]);
  useLayoutEffect(() => {
    if (role === 'menu' && position.visibility === 'visible') panelRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
  }, [panelRef, position.visibility, role]);
  return <div id={id} ref={panelRef} className="header-popover" role={role} aria-labelledby={labelledBy} style={position} onKeyDown={onKeyDown}>{children}</div>;
}

function PreviewBanner() {
  return <div className="preview-banner"><Icon name="info" size={16} /> Vista previa de desarrollo · no autenticada <span>Este acceso solo existe durante el servidor de desarrollo.</span></div>;
}

function AppShell({ yo, onLogout }: { yo?: Yo | null; onLogout?: () => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeHeaderPanel, setActiveHeaderPanel] = useState<'notifications' | 'user' | null>(null);
  const [auditExports, setAuditExports] = useState<TrackedExport[]>([]);
  const [notifications, setNotifications] = useState<Array<{ id: number; titulo: string; cuerpo: string | null;
    enlace: string | null; tipo: 'ok' | 'warn' | 'err' | 'info'; leida: boolean; creado_en: string }>>([]);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [theme, setTheme] = useState<'light' | 'dark'>(() => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
  const searchTriggerRef = useRef<HTMLButtonElement>(null);
  const notificationTriggerRef = useRef<HTMLButtonElement>(null);
  const userTriggerRef = useRef<HTMLButtonElement>(null);
  const headerPanelRef = useRef<HTMLDivElement>(null);
  const canTrackExports = Boolean(yo?.permisos.auditoria?.includes('ver') && yo?.permisos.procesos?.includes('ver'));
  useEffect(() => {
    if (!yo || !canTrackExports) { setAuditExports([]); return; }
    let live = true;
    const userId = yo.usuario.id;
    async function refresh() {
      const rows = await Promise.allSettled(trackedExportIds(userId).map(async id => {
        const process = await (await api(`/procesos/${id}`)).json() as TrackedExport;
        return { id, estado: process.estado };
      }));
      if (live) setAuditExports(rows.filter((row): row is PromiseFulfilledResult<TrackedExport> => row.status === 'fulfilled').map(row => row.value));
    }
    void refresh();
    window.addEventListener('syntra:audit-export', refresh);
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => { live = false; window.clearInterval(timer); window.removeEventListener('syntra:audit-export', refresh); };
  }, [yo?.usuario.id, canTrackExports]);
  const readyExports = auditExports.filter(item => item.estado === 'completado').length;
  useEffect(() => {
    if (!yo || previewMode) { setNotifications([]); setUnreadNotifications(0); return; }
    let live = true;
    async function refresh() {
      try {
        const result = await (await api('/notificaciones?limite=8')).json() as {
          no_leidas: number; items: typeof notifications };
        if (live && Array.isArray(result.items)) {
          setNotifications(result.items);
          setUnreadNotifications(Number.isSafeInteger(result.no_leidas) ? result.no_leidas : 0);
        }
      } catch { /* La campana conserva el último estado; la próxima consulta reintenta. */ }
    }
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => { live = false; window.clearInterval(timer); };
  }, [yo?.usuario.id]);
  async function openNotification(item: typeof notifications[number]) {
    try {
      if (!item.leida) await api(`/notificaciones/${item.id}/leer`, { method: 'POST' });
      setNotifications(current => current.map(row => row.id === item.id ? { ...row, leida: true } : row));
      setUnreadNotifications(current => Math.max(0, current - (item.leida ? 0 : 1)));
      setActiveHeaderPanel(null);
      if (item.enlace && /^\/mediciones\/[1-9]\d*\?tab=cargas$/.test(item.enlace)) navigate(item.enlace);
    } catch { toast('No se pudo abrir la notificación', 'Inténtalo de nuevo.', 'err'); }
  }
  async function markAllNotifications() {
    try {
      await api('/notificaciones/leer-todas', { method: 'POST' });
      setNotifications(current => current.map(row => ({ ...row, leida: true })));
      setUnreadNotifications(0);
    } catch { toast('No se pudieron marcar las notificaciones', 'Inténtalo de nuevo.', 'err'); }
  }
  const bellCount = unreadNotifications + readyExports;
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => {
    function handleGlobalKeys(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (searchOpen) {
          setSearchOpen(false);
          searchTriggerRef.current?.focus();
        } else if (activeHeaderPanel) {
          setActiveHeaderPanel(null);
          (activeHeaderPanel === 'notifications' ? notificationTriggerRef : userTriggerRef).current?.focus();
        }
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setActiveHeaderPanel(null);
        setSearchOpen(open => !open);
      }
    }
    window.addEventListener('keydown', handleGlobalKeys);
    return () => window.removeEventListener('keydown', handleGlobalKeys);
  }, [activeHeaderPanel, searchOpen]);
  useEffect(() => {
    if (!activeHeaderPanel) return;
    const triggerRef = activeHeaderPanel === 'notifications' ? notificationTriggerRef : userTriggerRef;
    function handleOutsidePointer(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node) || headerPanelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setActiveHeaderPanel(null);
    }
    document.addEventListener('pointerdown', handleOutsidePointer, true);
    return () => document.removeEventListener('pointerdown', handleOutsidePointer, true);
  }, [activeHeaderPanel]);
  function openSearch() {
    setActiveHeaderPanel(null);
    setSearchOpen(true);
  }
  function toggleHeaderPanel(panel: 'notifications' | 'user') {
    setSearchOpen(false);
    setActiveHeaderPanel(current => current === panel ? null : panel);
  }
  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    setTheme(next);
    setActiveHeaderPanel(null);
  }
  function handleUserMenuKeys(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const items = Array.from(headerPanelRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? []);
    if (!items.length) return;
    event.preventDefault();
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : event.key === 'ArrowDown' ? (index + 1) % items.length : index <= 0 ? items.length - 1 : index - 1;
    items[nextIndex]?.focus();
  }
  const createTitles: Record<string, string> = { '/clientes/nuevo': 'Nuevo cliente', '/cuentas/nueva': 'Nueva cuenta', '/prompts/nuevo': 'Nuevo prompt', '/regex/nueva': 'Nueva regex', '/paises/nuevo': 'Nuevo país', '/usuarios/nuevo': 'Nuevo usuario', '/roles/nuevo': 'Nuevo rol', '/grupos/nuevo': 'Nuevo grupo' };
  const current = location.pathname === '/' ? 'Inicio' : location.pathname === '/mediciones/nueva' ? 'Nueva medición' : location.pathname.match(/^\/clientes\/\d+\/editar$/) ? 'Editar cliente' : location.pathname.match(/^\/clientes\/\d+$/) ? 'Detalle de cliente' : location.pathname.match(/^\/roles\/\d+\/editar$/) ? 'Editar rol' : location.pathname.match(/^\/roles\/\d+$/) ? 'Detalle de rol' : location.pathname.match(/^\/paises\/\d+\/editar$/) ? 'Editar país' : location.pathname.match(/^\/paises\/\d+$/) ? 'Detalle de país' : location.pathname.match(/^\/prompts\/\d+\/editar$/) ? 'Editar prompt' : location.pathname.match(/^\/prompts\/\d+$/) ? 'Detalle de prompt' : location.pathname.match(/^\/regex\/\d+\/editar$/) ? 'Editar regex' : location.pathname.match(/^\/regex\/\d+$/) ? 'Detalle de regex' : location.pathname.match(/^\/cuentas\/\d+\/editar$/) ? 'Editar cuenta' : location.pathname.match(/^\/cuentas\/\d+$/) ? 'Detalle de cuenta' : location.pathname.match(/^\/grupos\/\d+\/editar$/) ? 'Editar grupo' : location.pathname.match(/^\/grupos\/\d+$/) ? 'Detalle de grupo' : location.pathname.match(/^\/usuarios\/\d+\/editar$/) ? 'Editar usuario' : location.pathname.match(/^\/usuarios\/\d+$/) ? 'Detalle de usuario' : location.pathname.match(/^\/auditoria\/\d+$/) ? 'Detalle del evento' : createTitles[location.pathname] ?? routeLabels[location.pathname] ?? (location.pathname.startsWith('/mediciones/') ? 'Detalle de medición' : 'No encontrado');
  return <div className={`app-shell${sidebarOpen ? '' : ' sidebar-collapsed'}`}>
    {previewMode && <PreviewBanner />}
    <aside className="sidebar" aria-label="Navegación principal">
      <Link className="sidebar-brand" to={`/${previewMode ? '?preview=1' : ''}`}><img src="/brand/symbol.png" alt="" /><img src="/brand/word-light.png" alt="Syntra" /></Link>
      <nav className="side-nav">{navigation.map(({ group, items }) => <section className="nav-group" key={group}><h2>{group}</h2>{items.map(item => <NavLink key={item.path} to={`${item.path}${previewMode ? '?preview=1' : ''}`} end={item.path === '/'} onClick={() => { if (window.innerWidth <= 860) setSidebarOpen(true); }} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}><Icon name={item.icon} /><span>{item.label}</span></NavLink>)}</section>)}</nav>
      <div className="sidebar-footer"><span className="avatar">S</span><span><strong>{yo?.usuario.nombre || 'Syntra'}</strong><small>{yo?.rol.nombre || 'Vista sin sesión'}</small></span></div>
    </aside>
    <div className="main-column">
      <header className="topbar"><button className="icon-button menu-toggle" aria-label="Mostrar u ocultar menú" onClick={() => setSidebarOpen(value => !value)}><Icon name="menu" /></button><nav className="breadcrumbs" aria-label="Ruta"><Link to={`/${previewMode ? '?preview=1' : ''}`}>Syntra</Link><Icon name="chevron" size={14} /><strong>{current}</strong></nav><div className="top-actions"><button ref={searchTriggerRef} className="search-pill" type="button" aria-label="Buscar en Syntra" aria-keyshortcuts="Control+K Meta+K" onClick={openSearch}><Icon name="search" /><span>Buscar en Syntra…</span><kbd>Ctrl K</kbd></button><button className="icon-button" type="button" aria-label={theme === 'dark' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'} onClick={toggleTheme}><Icon name={theme === 'dark' ? 'sun' : 'moon'} /></button><button ref={notificationTriggerRef} className="icon-button notification-trigger" type="button" aria-label={unreadNotifications ? `Notificaciones: ${unreadNotifications} sin leer · ${readyExports} exportaciones completadas` : readyExports ? `Notificaciones: ${readyExports} exportaciones completadas` : 'Notificaciones'} aria-haspopup="dialog" aria-expanded={activeHeaderPanel === 'notifications'} aria-controls={activeHeaderPanel === 'notifications' ? 'notifications-popover' : undefined} onClick={() => toggleHeaderPanel('notifications')}><Icon name="bell" />{bellCount > 0 && <span className="notification-count" aria-hidden="true">{bellCount > 99 ? "99+" : bellCount}</span>}</button><button ref={userTriggerRef} className="user-chip" type="button" aria-label="Menú de usuario" aria-haspopup="menu" aria-expanded={activeHeaderPanel === 'user'} aria-controls={activeHeaderPanel === 'user' ? 'user-menu-popover' : undefined} onClick={() => toggleHeaderPanel('user')}><span className="avatar small">S</span><span className="user-chip-label"><strong>{yo?.usuario.nombre || 'Syntra'}</strong><small>{yo?.rol.nombre || 'Vista previa'}</small></span><Icon name="chevron" size={14} /></button></div></header>
      {activeHeaderPanel === 'notifications' && <HeaderPopover id="notifications-popover" anchorRef={notificationTriggerRef} panelRef={headerPanelRef} role="dialog" labelledBy="notifications-title">
        <div className="header-popover-heading"><h2 id="notifications-title">Notificaciones</h2>{unreadNotifications > 0 && <button className="button small" type="button" onClick={() => void markAllNotifications()}>Marcar leídas</button>}</div>
        {notifications.length > 0 && <div className="audit-notifications">{notifications.map(item => <button className={`audit-notification app-notification${item.leida ? '' : ' unread'}`} type="button" key={item.id} onClick={() => void openNotification(item)}><span className={`app-notification-icon ${item.tipo}`}><Icon name={item.tipo === 'err' ? 'alert' : item.tipo === 'warn' ? 'info' : 'check'} size={14} /></span><span><strong>{item.titulo}</strong><small>{item.cuerpo}</small></span></button>)}</div>}
        {auditExports.length > 0 && <div className="audit-notifications">{auditExports.slice().reverse().map(item => <div className="audit-notification" key={item.id}><div><strong>Exportación de Auditoría #{item.id}</strong><small>{item.estado === 'completado' ? 'Completada' : item.estado === 'error' ? 'Fallida' : item.estado === 'en_cola' ? 'En cola' : 'En proceso'}</small></div>{item.estado === 'completado' && <button className="button small" type="button" aria-label={`Descargar exportación de Auditoría ${item.id}`} onClick={() => void downloadAuditExport(item.id).catch(error => toast('No se pudo descargar', clientError(error, 'El archivo no está disponible.'), 'err'))}><Icon name="download" size={14} />Descargar</button>}</div>)}</div>}
        {!notifications.length && !auditExports.length && <div className="notification-empty" role="status">Sin notificaciones</div>}
      </HeaderPopover>}
      {activeHeaderPanel === 'user' && <HeaderPopover id="user-menu-popover" anchorRef={userTriggerRef} panelRef={headerPanelRef} role="menu" labelledBy="user-menu-title" onKeyDown={handleUserMenuKeys}><div className="user-menu-profile"><span className="avatar">S</span><div><strong id="user-menu-title">{yo?.usuario.nombre || 'Syntra'}</strong><small>{yo?.rol.nombre || 'Vista previa · sin sesión'}</small></div></div><button className="user-menu-action" type="button" role="menuitem" onClick={toggleTheme}><Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} />Cambiar tema claro / oscuro</button>{onLogout && <button className="user-menu-action" type="button" role="menuitem" onClick={onLogout}>Cerrar sesión</button>}</HeaderPopover>}
      <main id="page" className="page-content" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<HomePage onOpenSearch={openSearch} />} />
          <Route path="/mediciones" element={<MeasurementsPage />} />
          <Route path="/mediciones/nueva" element={<NewMeasurementPage yo={yo || null} />} />
          <Route path="/mediciones/:id/editar" element={<MeasurementSourceConfigPage yo={yo || null} />} />
          {Object.entries(CREATION_ROUTES).filter(([path]) => previewMode || !['/roles', '/paises', '/prompts', '/regex', '/cuentas', '/grupos', '/usuarios'].includes(path)).map(([path, route]) => <Route key={route} path={route} element={<CreationFormPage path={path} />} />)}
          <Route path="/mediciones/:id/*" element={<MeasurementDetail yo={yo || null} />} />
          <Route path="/procesos" element={<ProcessesPage yo={yo || null} />} />
          <Route path="/auditoria" element={previewMode ? <AuditPage /> : <AuditList yo={yo || null} />} />
          {!previewMode && <Route path="/auditoria/:id" element={<AuditDetail />} />}
          {!previewMode && <><Route path="/clientes" element={<ClientsPage yo={yo || null} />} /><Route path="/clientes/:id" element={<ClientDetail yo={yo || null} />} /><Route path="/clientes/:id/editar" element={<ClientEditRoute />} /></>}
          {!previewMode && <><Route path="/roles" element={<RolesList yo={yo || null} />} /><Route path="/roles/nuevo" element={<RoleForm yo={yo || null} />} /><Route path="/roles/:id/editar" element={<RoleForm yo={yo || null} />} /><Route path="/roles/:id" element={<RoleDetail yo={yo || null} />} /></>}
          {!previewMode && <><Route path="/paises" element={<CountriesList yo={yo || null} />} /><Route path="/paises/nuevo" element={<CountryForm />} /><Route path="/paises/:id/editar" element={<CountryForm />} /><Route path="/paises/:id" element={<CountryDetail yo={yo || null} />} /></>}
          {!previewMode && <><Route path="/prompts" element={<PromptsList yo={yo || null} />} /><Route path="/prompts/nuevo" element={<PromptForm />} /><Route path="/prompts/:id/editar" element={<PromptForm />} /><Route path="/prompts/:id" element={<PromptDetail yo={yo || null} />} /></>}
          {!previewMode && <><Route path="/regex" element={<RegexList yo={yo || null} />} /><Route path="/regex/nueva" element={<RegexForm />} /><Route path="/regex/:id/editar" element={<RegexForm />} /><Route path="/regex/:id" element={<RegexDetail yo={yo || null} />} /></>}
          {!previewMode && <><Route path="/cuentas" element={<AccountsList yo={yo || null} />} /><Route path="/cuentas/nueva" element={<AccountForm />} /><Route path="/cuentas/:id/editar" element={<AccountForm />} /><Route path="/cuentas/:id" element={<AccountDetail yo={yo || null} />} /></>}
          {!previewMode && <><Route path="/grupos" element={<GroupsList yo={yo || null} />} /><Route path="/grupos/nuevo" element={<GroupForm />} /><Route path="/grupos/:id/editar" element={<GroupForm />} /><Route path="/grupos/:id" element={<GroupDetail yo={yo || null} />} /></>}
          {!previewMode && <><Route path="/usuarios" element={<UsersList yo={yo || null} />} /><Route path="/usuarios/nuevo" element={<UserForm yo={yo || null} />} /><Route path="/usuarios/:id/editar" element={<UserForm yo={yo || null} />} /><Route path="/usuarios/:id" element={<UserDetail yo={yo || null} />} /></>}
          {navigation.flatMap(group => group.items).filter(item => !['/', '/mediciones', '/procesos', '/auditoria'].includes(item.path) && (previewMode || !['/clientes', '/roles', '/paises', '/prompts', '/regex', '/cuentas', '/grupos', '/usuarios'].includes(item.path))).map(item => <Route key={item.path} path={item.path} element={<GenericModule path={item.path} title={item.label} />} />)}
          <Route path="*" element={<section className="panel"><EmptyState title="Página no encontrada" detail="La ruta solicitada no forma parte de las vistas visuales incluidas." /></section>} />
        </Routes>
      </main>
    </div>
    <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
  </div>;
}

function DocumentTitle({ authenticated = false }: { authenticated?: boolean }) {
  const location = useLocation();
  useEffect(() => {
    if (!previewMode && !authenticated && location.pathname !== '/acceso') {
      document.title = 'Acceso — Syntra';
      return;
    }
    const path = location.pathname;
    const creationPath = Object.entries(CREATION_ROUTES).find(([, route]) => route === path)?.[0];
    const title = path === '/acceso' ? 'Acceso'
      : path.match(/^\/clientes\/\d+\/editar$/) ? 'Editar cliente'
        : path.match(/^\/clientes\/\d+$/) ? 'Detalle de cliente'
      : path.match(/^\/roles\/\d+\/editar$/) ? 'Editar rol'
        : path.match(/^\/roles\/\d+$/) ? 'Detalle de rol'
      : path.match(/^\/paises\/\d+\/editar$/) ? 'Editar país'
        : path.match(/^\/paises\/\d+$/) ? 'Detalle de país'
      : path.match(/^\/prompts\/\d+\/editar$/) ? 'Editar prompt'
        : path.match(/^\/prompts\/\d+$/) ? 'Detalle de prompt'
      : path.match(/^\/regex\/\d+\/editar$/) ? 'Editar regex'
        : path.match(/^\/regex\/\d+$/) ? 'Detalle de regex'
      : path.match(/^\/cuentas\/\d+\/editar$/) ? 'Editar cuenta'
        : path.match(/^\/cuentas\/\d+$/) ? 'Detalle de cuenta'
      : path.match(/^\/grupos\/\d+\/editar$/) ? 'Editar grupo'
        : path.match(/^\/grupos\/\d+$/) ? 'Detalle de grupo'
      : path.match(/^\/usuarios\/\d+\/editar$/) ? 'Editar usuario'
        : path.match(/^\/usuarios\/\d+$/) ? 'Detalle de usuario'
      : path.match(/^\/auditoria\/\d+$/) ? 'Detalle del evento'
      : path === '/mediciones/nueva' ? 'Nueva medición'
        : path.startsWith('/mediciones/') ? 'Detalle de medición'
          : creationPath ? CREATION_SPECS[creationPath]?.title ?? 'Formulario'
            : routeLabels[path] ?? 'No encontrado';
    document.title = `${title} — Syntra`;
  }, [location.pathname, authenticated]);
  return null;
}

export default function App() {
  const location = useLocation();
  const [authenticated, setAuthenticated] = useState(hasToken());
  const [checkingSession, setCheckingSession] = useState(!previewMode && !hasToken() && location.pathname !== '/acceso');
  const [yo, setYo] = useState<Yo | null>(null);
  const navigate = useNavigate();
  useEffect(() => watchToken(token => setAuthenticated(Boolean(token))), []);
  useEffect(() => {
    if (previewMode || hasToken()) return;
    let live = true;
    void refreshAccess().finally(() => { if (live) setCheckingSession(false); });
    return () => { live = false; };
  }, []);
  useEffect(() => {
    if (!authenticated || previewMode) { setYo(null); return; }
    api('/auth/yo').then(response => response.json()).then(setYo).catch(() => setYo(null));
  }, [authenticated]);
  if (previewMode) return <ToastProvider><DocumentTitle /><AppShell /></ToastProvider>;
  if (checkingSession) return <main className="session-check" role="status">Comprobando sesión…</main>;
  if (authenticated && location.pathname === '/acceso') return <Navigate to={postLoginPath(location.state)} replace />;
  if (authenticated) return <ToastProvider><DocumentTitle authenticated /><AppShell yo={yo} onLogout={() => { void logoutApi().finally(() => navigate('/acceso')); }} /></ToastProvider>;
  return <ToastProvider><DocumentTitle /><Routes><Route path="/acceso" element={<AccessPage />} /><Route path="*" element={<Navigate to="/acceso" replace state={{ from: `${location.pathname}${location.search}${location.hash}` }} />} /></Routes></ToastProvider>;
}
