import { useEffect, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import { Icon } from '../shared/Icon';
import { ApiError, api } from '../shared/api';
import { useToast } from '../shared/Toast';
import { LoadActionSelector, loadOptionDefinitions } from './LoadActionSelector';
import type { LoadAction } from './LoadActionSelector';

export type PendingMeasurementFile = { file: File; formatId: string };
type FormatColumn = { campo_destino: string; columnas_origen: string[]; transformacion: string; requerido: boolean };
type Format = { id: string; nombre: string; extensiones: string[]; mapeado?: boolean; columnas?: FormatColumn[] };
type StoredFile = { id: number; nombre: string; formato_id: string; formato_nombre: string | null; tamano_bytes: number | null;
  filas_leidas: number | null; filas_validas: number | null; filas_rechazadas: number | null;
  estado: 'subido' | 'procesando' | 'procesado' | 'error'; subido_por: number | null;
  subido_por_nombre: string | null; subido_en: string; proceso_id: number | null };
type StoredLot = { id: number; origen: string; archivo_id: number | null; proceso_id: number | null;
  estado: string | null; creado_en: string; iniciado_en: string | null; finalizado_en: string | null;
  duracion_ms: number | null; n_leidos: number; n_nuevos: number; n_duplicados: number; n_rechazados: number;
  red: string | null; detalle: string | null; al_incorporar: Record<string, boolean> | null };
type DuplicateDetail = { codigo: 'archivo_duplicado'; archivo_id: number; proceso_id: number | null;
  estado_archivo: string; estado_proceso: string | null };
function duplicateDetail(value: unknown): DuplicateDetail | null {
  if (!value || typeof value !== 'object') return null;
  const detail = value as Record<string, unknown>;
  return detail.codigo === 'archivo_duplicado' && typeof detail.archivo_id === 'number'
    ? detail as DuplicateDetail : null;
}

const DB_FORMAT_REQUIRED_HEADERS = ['url', 'published'];
const LOAD_OPTIONS = [
  ['incorporar', 'Incorporar automáticamente', 'zap'], ['relevancia', 'Evaluar relevancia', 'target'],
  ['sentimiento', 'Evaluar sentimiento', 'heart'], ['clusters', 'Generar clusters', 'layers'], ['bots', 'Análisis de bots', 'bot'],
] as const;
const SOURCE_NAMES: Record<string, string> = { archivo: 'Archivos (Excel)', meltwater: 'API Meltwater', manual: 'Manual', scraper: 'Scraper', googlenews: 'Google News' };
function isSupportedDbFormat(format: Format) {
  if (!format.mapeado || format.id !== 'talkwalker_simple') return false;
  const columns = format.columnas || [];
  const originHeaders = new Set(columns.flatMap(column => column.columnas_origen.map(name => name.trim().toLowerCase())));
  if (!DB_FORMAT_REQUIRED_HEADERS.every(header => originHeaders.has(header))) return false;
  return columns.filter(column => column.requerido).every(column =>
    column.columnas_origen.some(name => DB_FORMAT_REQUIRED_HEADERS.includes(name.trim().toLowerCase())));
}

export function MeasurementFileHistory({ measurementId, formatDate, sources = [], refreshKey = 0 }:
  { measurementId: number; formatDate: (value: string) => string;
    sources?: Array<{ origen: string; activo: boolean; al_cargar?: Record<string, boolean> }>;
    refreshKey?: number }) {
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [lots, setLots] = useState<StoredLot[]>([]);
  const [nextLotCursor, setNextLotCursor] = useState<string | null>(null);
  const [lotOrigin, setLotOrigin] = useState('');
  const lotRequest = useRef(0);
  const [loadingLots, setLoadingLots] = useState(true);
  const [lotNotice, setLotNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState('');
  const [downloading, setDownloading] = useState<number | null>(null);
  const toast = useToast();

  async function load(cursor?: string) {
    setLoading(true); setNotice('');
    try {
      const response = await api(`/mediciones/${measurementId}/archivos?limite=25${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`);
      const items: StoredFile[] = await response.json();
      setFiles(previous => cursor ? [...previous, ...items.filter(item => !previous.some(old => old.id === item.id))] : items);
      setNextCursor(response.headers.get('X-Next-Cursor'));
    } catch (error) {
      const status = error instanceof ApiError ? error.status : null;
      const message = status === 403 ? 'No tienes permiso para consultar el historial de archivos.'
        : status === 404 ? 'La medición no está disponible.'
          : status ? `No se pudo cargar el historial de archivos (HTTP ${status}). Inténtalo de nuevo.`
            : 'No se pudo conectar para cargar el historial de archivos. Inténtalo de nuevo.';
      setNotice(message); toast('No se pudo cargar Cargas', message, 'err');
    }
    finally { setLoading(false); }
  }
  async function loadLots(cursor?: string, origin = lotOrigin) {
    const request = ++lotRequest.current;
    setLoadingLots(true); setLotNotice('');
    try {
      const response = await api(`/mediciones/${measurementId}/lotes?limite=25${origin ? `&origen=${encodeURIComponent(origin)}` : ''}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`);
      const items: StoredLot[] = await response.json();
      if (request !== lotRequest.current) return;
      setLots(previous => cursor ? [...previous, ...items.filter(item => !previous.some(old => old.id === item.id))] : items);
      setNextLotCursor(response.headers.get('X-Next-Cursor'));
    } catch (error) {
      if (request !== lotRequest.current) return;
      const status = error instanceof ApiError ? error.status : null;
      setLotNotice(status === 403 ? 'No tienes permiso para consultar los lotes de esta medición.'
        : status === 404 ? 'La medición no está disponible.'
          : 'No se pudieron consultar los lotes de esta medición.' + (status ? ` (HTTP ${status})` : ''));
    } finally { if (request === lotRequest.current) setLoadingLots(false); }
  }
  useEffect(() => {
    setFiles([]); setNextCursor(null); setLots([]); setNextLotCursor(null); setLotOrigin('');
    void load(); void loadLots(undefined, '');
  }, [measurementId, refreshKey]);

  async function download(file: StoredFile) {
    setDownloading(file.id); setNotice('');
    try {
      const issued = await (await api(`/archivos/${file.id}/descargar`)).json();
      const path = String(issued.url || '').replace(/^\/api\/v1/, '');
      const response = await api(path);
      const address = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = address; anchor.download = file.nombre; anchor.click();
      setTimeout(() => URL.revokeObjectURL(address), 60_000);
    } catch (error) {
      const message = error instanceof ApiError && error.status < 500
        ? `No se pudo descargar el archivo (${error.status}): ${error.message}`
        : 'No se pudo descargar el archivo. Inténtalo de nuevo.';
      setNotice(message); toast('No se pudo descargar el archivo', message, 'err');
    }
    finally { setDownloading(null); }
  }
  const status = {
    subido: ['info', 'Subido'], procesando: ['info', 'Procesando'],
    procesado: ['ok', 'Procesado'], error: ['err', 'Error de carga'],
  } as const;
  const activeSources = sources.filter(source => source.activo);
  return <div className="measurement-cargas-stack">
    <section className="panel measurement-file-history" aria-label="Al cargar por tipo de dato">
    <div className="measurement-file-load-settings">
      <div className="card-head"><h3>Al cargar · por tipo de dato</h3><span className="sub">Configuración vigente para las próximas cargas</span></div>
      {activeSources.length ? <div className="table-wrap"><table className="data-table measurement-load-table"><thead><tr><th>Fuente</th><th>Estado</th><th>Al cargar</th></tr></thead><tbody>
        {activeSources.map(source => <tr key={source.origen}><td>{SOURCE_NAMES[source.origen] || source.origen}</td><td><span className="badge ok"><span className="d" aria-hidden="true" />Activa</span></td>
          <td><span className="measurement-load-icons" aria-label={`Opciones de ${SOURCE_NAMES[source.origen] || source.origen}`}>
            {LOAD_OPTIONS.map(([key, label, icon]) => <span key={key} className={`measurement-load-icon-state${source.al_cargar?.[key] ? ' enabled' : ''}`} title={`${label}: ${source.al_cargar?.[key] ? 'Sí' : 'No'}`} aria-label={`${label}: ${source.al_cargar?.[key] ? 'Sí' : 'No'}`}><Icon name={icon} size={13} /></span>)}
          </span></td></tr>)}
      </tbody></table></div> : <p className="empty">No hay fuentes activas para próximas cargas.</p>}
      <div className="measurement-load-legend" aria-label="Leyenda de opciones al cargar">{LOAD_OPTIONS.map(([key, label, icon]) => <span key={key}><Icon name={icon} size={13} />{label}</span>)}</div>
    </div>
    </section>
    <section className="panel measurement-file-history" aria-label="Historial de archivos cargados">
    <div className="card-head"><div><h3>Historial de archivos cargados</h3><span className="sub">{files.length === 1 ? '1 archivo visible' : `${files.length} archivos visibles`} · disponibles para descarga</span></div></div>
    {notice && <div className="control-notice error" role="alert">{notice} <button className="button small" type="button" disabled={loading} onClick={() => void load()}>Reintentar</button></div>}
    {files.length ? <div className="table-wrap"><table className="tbl"><thead><tr>
      <th>Archivo</th><th>Fuente / formato</th><th className="num">Tamaño</th><th className="num">Registros</th>
      <th>Cargado por</th><th>Fecha de carga</th><th>Estado</th><th>Acción</th>
    </tr></thead><tbody>{files.map(file => <tr key={file.id}>
      <td><strong>{file.nombre}</strong></td><td>{file.formato_nombre || file.formato_id}</td>
      <td className="num">{file.tamano_bytes === null ? '—' : `${(file.tamano_bytes / 1024).toFixed(1)} KB`}</td>
      <td className="num">{file.filas_leidas ?? '—'}</td>
      <td>{file.subido_por_nombre || (file.subido_por ? `Usuario #${file.subido_por}` : '—')}</td>
      <td>{formatDate(file.subido_en)}</td>
      <td><span className={`badge ${status[file.estado]?.[0] || 'warn'}`}>
        <span className="d" aria-hidden="true" />{status[file.estado]?.[1] || file.estado}</span>
        {file.proceso_id && <small className="process-row-kind">Proceso #{file.proceso_id}</small>}</td>
      <td><button type="button" className="button small" aria-label={`Descargar ${file.nombre}`}
        title={`Descargar ${file.nombre}`} disabled={downloading !== null}
        onClick={() => void download(file)}><Icon name="download" size={14} /> Descargar</button></td>
    </tr>)}</tbody></table></div> : !loading && <p className="empty">Aún no hay archivos.</p>}
    {loading && <p role="status">Cargando archivos…</p>}
    {nextCursor && <button className="button small" type="button" disabled={loading}
      onClick={() => void load(nextCursor)}>Cargar más</button>}
    </section>
    <section className="panel measurement-file-history" aria-label="Lotes de carga">
    <div className="card-head"><div><h3>Lotes de carga</h3><span className="sub">Resultados persistidos de las ejecuciones</span></div>
      <div className="right"><select aria-label="Filtrar por fuente" value={lotOrigin}
        onChange={event => { setLotOrigin(event.target.value); setLots([]); setNextLotCursor(null); void loadLots(undefined, event.target.value); }}>
        <option value="">Todas las fuentes</option>
        {Object.entries(SOURCE_NAMES).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
      </select><button className="button small" type="button" disabled={loadingLots} onClick={() => void loadLots()}>Actualizar</button></div></div>
    {lotNotice && <p className="control-notice error" role="alert">{lotNotice}</p>}
    {lots.length ? <div className="table-wrap"><table className="tbl measurement-lots-table"><thead><tr>
      <th>Lote</th><th>Fuente</th><th>Detalle</th><th>Fecha</th><th>Al cargar</th><th>Estado</th><th>Inicio</th><th>Fin</th><th>Duración</th>
      <th className="num">Leídos</th><th className="num">Nuevos</th><th className="num">Duplicados</th>
      <th className="num">Rechazados</th><th>Proceso</th>
    </tr></thead><tbody>{lots.map(lot => <tr key={lot.id}>
      <td>#{lot.id}</td><td>{SOURCE_NAMES[lot.origen] || lot.origen}{lot.red ? ` · ${lot.red}` : ''}</td>
      <td title={lot.detalle || undefined}>{lot.detalle || '—'}</td><td>{formatDate(lot.creado_en)}</td>
      <td>{lot.al_incorporar ? <span className="measurement-load-icons" aria-label="Opciones al cargar del lote">
        {LOAD_OPTIONS.map(([key, label, icon]) => <span key={key} className={`measurement-load-icon-state${lot.al_incorporar?.[key] ? ' enabled' : ''}`}
          title={`${label}: ${lot.al_incorporar?.[key] ? 'Sí' : 'No'}`} aria-label={`${label}: ${lot.al_incorporar?.[key] ? 'Sí' : 'No'}`}><Icon name={icon} size={13} /></span>)}
      </span> : '—'}</td>
      <td><span className={`badge ${lot.estado === 'completado' ? 'ok' : lot.estado === 'error' ? 'err' : 'info'}`}>
        <span className="d" aria-hidden="true" />{lot.estado || '—'}</span></td>
      <td>{lot.iniciado_en ? formatDate(lot.iniciado_en) : '—'}</td>
      <td>{lot.finalizado_en ? formatDate(lot.finalizado_en) : '—'}</td>
      <td>{lot.duracion_ms === null ? '—' : `${(lot.duracion_ms / 1000).toFixed(1)} s`}</td>
      <td className="num">{lot.n_leidos}</td><td className="num">{lot.n_nuevos}</td>
      <td className="num">{lot.n_duplicados}</td><td className="num">{lot.n_rechazados}</td>
      <td>{lot.proceso_id ? `#${lot.proceso_id}` : '—'}</td>
    </tr>)}</tbody></table></div> : !loadingLots && !lotNotice && <p className="empty">Aún no hay lotes.</p>}
    {loadingLots && <p role="status">Cargando lotes…</p>}
    {nextLotCursor && <button className="button small" type="button" disabled={loadingLots}
      onClick={() => void loadLots(nextLotCursor)}>Cargar más lotes</button>}
    </section>
  </div>;
}

export async function uploadMeasurementFiles(measurementId: number, files: PendingMeasurementFile[],
                                             options: Record<string, boolean>,
                                             completed = new Map<File, number>(),
                                             idempotencyKey: string = crypto.randomUUID()): Promise<number | null> {
  if (!files.length) return null;
  const ids: number[] = [];
  for (const { file, formatId } of files) {
    const previouslyUploaded = completed.get(file);
    if (previouslyUploaded) { ids.push(previouslyUploaded); continue; }
    // La huella opcional del contrato permite detectar un duplicado antes de
    // crear una reserva que todavía no tiene contenido ni proceso.
    let sha256: string | undefined;
    if (globalThis.crypto?.subtle && typeof file.arrayBuffer === 'function') {
      const digest = await globalThis.crypto.subtle.digest('SHA-256', await file.arrayBuffer());
      sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
    }
    const reserved = await (await api(`/mediciones/${measurementId}/archivos/presignar`, {
      method: 'POST', body: JSON.stringify({ nombre: file.name, tamano_bytes: file.size, formato_id: formatId, ...(sha256 ? { sha256 } : {}) }),
    })).json();
    await api(`/archivos/${reserved.archivo_id}/contenido`, {
      method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
    });
    ids.push(reserved.archivo_id);
    completed.set(file, reserved.archivo_id);
  }
  const queued = await (await api(`/mediciones/${measurementId}/cargas/archivos`, {
    method: 'POST', headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ archivo_ids: ids, al_incorporar: options }),
  })).json();
  return queued.proceso_id;
}

export function MeasurementFilePicker({ formats, selected, onChange, disabled = false }:
  { formats: Format[]; selected: PendingMeasurementFile[];
    onChange: (files: PendingMeasurementFile[]) => void; disabled?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [formatId, setFormatId] = useState('talkwalker_simple');
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState('');
  const [downloadingTemplate, setDownloadingTemplate] = useState(false);
  const toast = useToast();
  const usable = formats.filter(isSupportedDbFormat);
  const format = usable.find(item => item.id === formatId) ?? usable[0];
  const sourceColumns = [...new Set((format?.columnas || []).flatMap(column => column.columnas_origen))];

  function addFiles(incoming: FileList | File[]) {
    if (!format) { const message = 'No hay un mapeo de DBFormatoSimple validado con las columnas obligatorias url y published.'; setError(message); toast('Formato pendiente', message, 'err'); return; }
    const additions: PendingMeasurementFile[] = [];
    for (const file of Array.from(incoming)) {
      const extension = file.name.split('.').pop()?.toLowerCase() || '';
      if (!file.size || file.size > 50 * 1024 * 1024 || !format.extensiones.includes(extension)) {
        const message = `El archivo ${file.name} debe corresponder al formato y pesar entre 1 byte y 50 MB.`; setError(message); toast('Archivo no válido', message, 'err');
        return;
      }
      additions.push({ file, formatId: format.id });
    }
    onChange([...selected, ...additions]);
    setError('');
  }
  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (!disabled) addFiles(event.dataTransfer.files);
  }

  async function downloadTemplate() {
    if (!format || disabled) return;
    setDownloadingTemplate(true); setError('');
    try {
      const issued = await (await api(`/formatos/${encodeURIComponent(format.id)}/plantilla`)).json();
      const path = String(issued.url || '').replace(/^\/api\/v1/, '');
      if (!path) throw new Error('La API no devolvió una URL de descarga.');
      const response = await api(path);
      const address = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = address; anchor.download = issued.nombre || `plantilla_${format.id}.xlsx`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(address), 60_000);
    } catch (cause) {
      const message = cause instanceof ApiError && cause.status < 500
        ? `No se pudo descargar la planilla (${cause.status}): ${cause.message}`
        : 'No se pudo descargar la planilla. Inténtalo de nuevo.';
      setError(message); toast('No se pudo descargar la planilla', message, 'err');
    } finally { setDownloadingTemplate(false); }
  }

  return <div className="measurement-file-picker">
    <div className="field"><label>Formatos admitidos</label><div className="chips">
      {formats.map(item => { const supported = isSupportedDbFormat(item); return <span className={`badge outline${supported ? '' : ' disabled'}`} key={item.id}
        title={supported ? item.nombre : 'Pendiente: el mapeo no confirma las columnas obligatorias url y published'}>
        {item.nombre}{supported ? '' : ' · pendiente de validación'}
      </span>; })}
      {!formats.length && <span className="field-help">No hay formatos disponibles.</span>}
    </div></div>
    <div className="field"><label htmlFor="measurement-file-format">Fuente / formato de los archivos</label>
      <select id="measurement-file-format" value={format?.id || ''} disabled={disabled || !usable.length}
        onChange={event => setFormatId(event.target.value)}>
        {usable.length ? usable.map(item => <option key={item.id} value={item.id}>{item.nombre}</option>)
          : <option value="">Sin formato de ingesta disponible</option>}
      </select>
      <span className="field-help">Solo se habilita talkwalker_simple (DBFormatoSimple) cuando el catálogo confirma url y published como únicas columnas obligatorias. Los demás formatos permanecen pendientes.</span>
      <div className="measurement-format-preview">
        <div className="measurement-format-preview-heading"><strong>{format?.nombre || 'Sin formato disponible'}</strong>
          <button type="button" className="button small" disabled={disabled || !format || !sourceColumns.length || downloadingTemplate}
            onClick={() => void downloadTemplate()}><Icon name="download" size={14} />
            {downloadingTemplate ? 'Preparando…' : 'Descargar planilla'}</button>
        </div>
        {sourceColumns.length
          ? <p className="measurement-format-columns" aria-label="Columnas de la planilla">{sourceColumns.join(' · ')}</p>
          : <p className="measurement-format-columns muted">Este formato no tiene columnas configuradas para una planilla.</p>}
      </div>
    </div>
    <div className={`measurement-dropzone${dragging ? ' dragging' : ''}`}
      role="button" tabIndex={disabled || !format ? -1 : 0}
      aria-label="Seleccionar archivos para la medición" aria-disabled={disabled || !format}
      onClick={event => {
        if (disabled || !format || (event.target as HTMLElement).closest('button')) return;
        input.current?.click();
      }}
      onKeyDown={event => {
        if (!disabled && format && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault(); input.current?.click();
        }
      }}
      onDragOver={event => { event.preventDefault(); if (!disabled) setDragging(true); }}
      onDragLeave={() => setDragging(false)} onDrop={drop}>
      <span className="wizard-step-icon"><Icon name="upload" size={21} /></span>
      <b>Arrastra aquí tus archivos o haz clic para seleccionarlos</b>
      <span className="field-help">Varios archivos a la vez · {format?.extensiones.join(', ') || 'sin formato'} · hasta 50 MB cada uno</span>
      <span className="button measurement-dropzone-action" aria-hidden="true"><Icon name="upload" size={15} /> Seleccionar archivos</span>
      <input ref={input} className="visually-hidden" type="file" multiple tabIndex={-1} aria-hidden="true"
        accept={format?.extensiones.map(ext => `.${ext}`).join(',') || undefined}
        onChange={event => { if (event.target.files) addFiles(event.target.files); event.target.value = ''; }} />
    </div>
    {error && <p className="field-error" role="alert">{error}</p>}
    {!!selected.length && <ul className="measurement-selected-files" aria-label="Archivos seleccionados">
      {selected.map((item, index) => <li key={`${item.file.name}-${index}`}>
        <span><b>{item.file.name}</b><small>{item.formatId} · {(item.file.size / 1024).toFixed(1)} KB</small></span>
        <button type="button" className="icon-button" aria-label={`Quitar ${item.file.name}`}
          onClick={() => onChange(selected.filter((_, position) => position !== index))}><Icon name="close" size={15} /></button>
      </li>)}
    </ul>}
  </div>;
}

export function MeasurementUploadDialog({ measurementId, sources, canExecute, canViewFormats,
  onClose, onQueued, onViewPrevious }: {
  measurementId: number;
  sources: Array<{ origen: string; activo: boolean; al_cargar?: Record<string, boolean> }>;
  canExecute: boolean;
  canViewFormats: boolean;
  onClose: () => void;
  onQueued: (processId: number) => void;
  onViewPrevious: () => void;
}) {
  const [formats, setFormats] = useState<Format[]>([]);
  const [selected, setSelected] = useState<PendingMeasurementFile[]>([]);
  const [loadingFormats, setLoadingFormats] = useState(canViewFormats);
  const [formatsError, setFormatsError] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [duplicate, setDuplicate] = useState<DuplicateDetail | null>(null);
  const [options, setOptions] = useState<Record<string, boolean>>(() => {
    const configured = sources.find(source => source.origen === 'archivo')?.al_cargar;
    return Object.fromEntries(loadOptionDefinitions.map(([key]) => [key, Boolean(configured?.[key])]));
  });
  const toast = useToast();
  const batch = useRef({ key: crypto.randomUUID(), completed: new Map<File, number>() });
  const fileSource = sources.find(source => source.origen === 'archivo');
  const filesActive = Boolean(fileSource?.activo);

  useEffect(() => {
    if (!canViewFormats) return;
    let active = true;
    api('/formatos').then(response => response.json()).then(items => {
      if (active && Array.isArray(items)) setFormats(items);
    }).catch(error => {
      if (!active) return;
      const message = error instanceof ApiError && error.status < 500
        ? `No se pudieron consultar los formatos (${error.status}): ${error.message}`
        : 'No se pudieron consultar los formatos disponibles.';
      setFormatsError(message); toast('No se pudieron cargar los formatos', message, 'err');
    }).finally(() => { if (active) setLoadingFormats(false); });
    return () => { active = false; };
  }, [canViewFormats]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !saving) onClose(); };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [onClose, saving]);

  const changeSelected = (next: PendingMeasurementFile[]) => {
    batch.current.key = crypto.randomUUID();
    setSelected(next);
    setNotice('');
    setDuplicate(null);
  };
  const changeOption = (key: LoadAction, enabled: boolean) => {
    batch.current.key = crypto.randomUUID();
    setOptions(current => ({ ...current, [key]: enabled }));
    setNotice('');
    setDuplicate(null);
  };
  const submit = async () => {
    if (!canExecute || !filesActive || !selected.length || saving) return;
    setSaving(true); setNotice(''); setDuplicate(null);
    try {
      const processId = await uploadMeasurementFiles(measurementId, selected,
        options, batch.current.completed, batch.current.key);
      if (!processId) throw new Error('La API no devolvió el proceso de la carga.');
      toast('Carga encolada', `Proceso #${processId}. El procesamiento continúa en segundo plano.`);
      onQueued(processId);
      onClose();
    } catch (error) {
      const duplicate = error instanceof ApiError ? duplicateDetail(error.detail) : null;
      setDuplicate(duplicate);
      const message = duplicate
        ? `El archivo ya existe en esta medición (archivo #${duplicate.archivo_id}${duplicate.proceso_id ? `, proceso #${duplicate.proceso_id}` : ''}). Estado: ${duplicate.estado_proceso || duplicate.estado_archivo}. Consulta el historial de cargas.`
        : error instanceof ApiError && error.status < 500
        ? `No se pudo iniciar la carga (${error.status}): ${error.message}`
        : 'No se pudo iniciar la carga. Inténtalo de nuevo.';
      setNotice(message); toast('No se pudo iniciar la carga', message, 'err');
    } finally { setSaving(false); }
  };

  return <div className="command-scrim measurement-upload-scrim" onMouseDown={event => {
    if (event.target === event.currentTarget && !saving) onClose();
  }}>
    <section className="command-panel measurement-upload-dialog" role="dialog" aria-modal="true"
      aria-labelledby="measurement-upload-title" onMouseDown={event => event.stopPropagation()}>
      <div className="panel-heading"><div><h2 id="measurement-upload-title">Nueva carga</h2>
        <span className="panel-sub">Medición #{measurementId}</span></div>
        <button className="icon-button" type="button" aria-label="Cerrar nueva carga" disabled={saving}
          onClick={onClose}><Icon name="close" size={16} /></button>
      </div>
      {!canExecute && <p className="control-notice error">Se requiere mediciones:ejecutar para cargar archivos.</p>}
      {canExecute && !filesActive && <p className="control-notice error">La fuente Archivos no está activa en esta medición. Actívala en Editar antes de cargar.</p>}
      {!canViewFormats && <p className="control-notice error">Se requiere formatos:ver para consultar los formatos compatibles.</p>}
      {loadingFormats ? <p role="status">Consultando formatos…</p>
        : formatsError ? <p className="control-notice error" role="alert">No se pudo determinar qué formatos pueden utilizarse.</p>
          : <MeasurementFilePicker formats={formats} selected={selected} onChange={changeSelected}
            disabled={!canExecute || !filesActive || saving || !canViewFormats} />}
      <LoadActionSelector caption="Al cargar estos archivos" value={options} onChange={changeOption}
        disabled={saving || !canExecute || !filesActive} />
      <p className="field-help measurement-upload-options-note">{options.incorporar
        ? 'Los registros nuevos válidos se incorporan automáticamente, incluso si seleccionas relevancia. '
        : 'Los registros nuevos válidos quedan sin incorporar para fiscalización. '}
        Las opciones de relevancia, sentimiento, clusters y bots se guardan con la carga, pero esta ingesta todavía no ejecuta esos análisis.</p>
      {notice && <div className="control-notice error" role="alert"><p>{notice}</p>
        {duplicate && <button className="button small" type="button" onClick={() => { onViewPrevious(); onClose(); }}>
          Ver carga anterior</button>}</div>}
      <div className="form-actions"><button className="button" type="button" disabled={saving} onClick={onClose}>Cancelar</button>
        <button className="button primary" type="button" disabled={saving || !canExecute || !filesActive || !canViewFormats || !selected.length || !formats.some(isSupportedDbFormat)}
          onClick={() => void submit()}><Icon name="upload" size={15} /> {saving ? 'Enviando…' : 'Iniciar carga'}</button></div>
    </section>
  </div>;
}
