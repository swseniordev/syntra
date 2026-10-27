import { Fragment } from 'react';
import { useEffect, useRef, useState } from 'react';
import { Icon } from '../../shared/Icon';
import { EmptyState } from '../../shared/EmptyState';
import { api } from '../../shared/api';
import type { Yo } from '../../shared/api';
import { useToast } from '../../shared/Toast';
import { downloadAuditExport } from '../../shared/auditExports';
import { PageHeading } from '../../shared/PageHeading';
import { clientError } from '../../shared/httpErrors';
const PROCESS_DESCRIPTION = 'Los indicadores y la tabla superiores están reservados al módulo de mediciones. El seguimiento operativo disponible al final corresponde al envío de correos y a las exportaciones de Auditoría.';
const MEASUREMENT_PROCESS_TYPES = [['preparar_medicion', 'Preparación de medición'], ['carga', 'Carga de datos'], ['fiscalizacion_ia', 'Fiscalización con IA'], ['incorporacion', 'Incorporación'], ['actualizacion_masiva', 'Actualización masiva (Excel)'], ['metadata', 'Actualización de metadata'], ['transcripcion', 'Transcripción audio/video'], ['analisis', 'Análisis IA'], ['reaplicar_regex', 'Reaplicación de regex y cruces'], ['publicacion', 'Actualización del tablero']];
const MEASUREMENT_PROCESS_STATES = [['en_cola', 'En cola'], ['en_ejecucion', 'En ejecución'], ['completado', 'Completado'], ['advertencia', 'Con advertencias'], ['error', 'Error'], ['cancelado', 'Cancelado']];
type QueueStatus = { cola: string; en_cola: number; en_ejecucion: number; con_error: number; mas_antigua_s: number; workers: number };
type WorkerStatus = { id: string; servidor: string; colas: string[]; iniciado_en: string; latido: string; tareas_en_curso: number; vivo: boolean };
export type MonitoredProcess = { id: number; tipo: string; estado: string; progreso: number; total: number; procesados: number; ok: number; errores: number; creado_en: string; iniciado_en: string | null; finalizado_en: string | null; duracion_ms: number | null; sla_ms: number | null };
type MonitoredTask = { id: number; clave: string; tipo: string; estado: string; intentos: number; ok: number; errores: number; error_codigo: string | null; error_mensaje: string; iniciado_en: string | null; finalizado_en: string | null };
export const processLabels: Record<string, string> = { correo_acceso: 'Envío de correo', exportacion: 'Exportación de Auditoría', preparar_medicion: 'Preparación de medición' };
const processStateLabels: Record<string, string> = { en_cola: 'En cola', en_ejecucion: 'En ejecución', completado: 'Completado', advertencia: 'Con advertencias', error: 'Error', cancelado: 'Cancelado' };
function processDate(value: string | null) { return value ? new Date(value).toLocaleString('es-CO', { dateStyle: 'short', timeStyle: 'short', timeZone: 'America/Bogota' }) : '—'; }
export function processDuration(value: number | null) {
  if (value == null) return '—';
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`;
  if (value < 3_600_000) return `${(value / 60_000).toFixed(1)} min`;
  return `${(value / 3_600_000).toFixed(1)} h`;
}
export function ProcessStateBadge({ state }: { state: string }) {
  const tone = state === 'completado' ? 'ok' : state === 'error' || state === 'cancelado' ? 'err' : state === 'advertencia' ? 'warn' : 'info';
  return <span className={`badge ${tone}`}><span className="d" aria-hidden="true" />{processStateLabels[state] || 'Desconocido'}</span>;
}
export function ProcessesPage({ yo }: { yo: Yo | null }) {
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
