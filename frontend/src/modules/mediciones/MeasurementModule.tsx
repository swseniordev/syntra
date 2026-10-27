import { Fragment, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Icon } from '../../shared/Icon';
import { StateBadge } from '../../shared/StateBadge';
import { EmptyState } from '../../shared/EmptyState';
import { api } from '../../shared/api';
import type { Yo } from '../../shared/api';
import { MeasurementFileHistory, MeasurementFilePicker, MeasurementUploadDialog, uploadMeasurementFiles } from './components/MeasurementFiles';
import type { PendingMeasurementFile } from './components/MeasurementFiles';
import { LoadActionSelector, loadOptionDefinitions } from './components/LoadActionSelector';
import { PageHeading } from '../../shared/PageHeading';
import { clientError } from '../../shared/httpErrors';
import { processDuration, processLabels, ProcessStateBadge } from '../procesos/ProcessesPage';
import type { MonitoredProcess } from '../procesos/ProcessesPage';

import { defaultMeltwaterWindow, formatClientDateTime, previewMode } from '../../app/runtime';
const measurementSteps = [
  ['General', 'Cuenta y nombre'], ['Fuentes de datos', 'Archivos, Meltwater y manual'], ['Scrapers', 'Redes sociales y Google News'], ['Prompts', 'General y por red'], ['Clusters', 'Parámetros y cruces'], ['Bots y X', 'Detección y parámetros'], ['Regex y ventana', 'Orden y preclustering'], ['Revisión', 'Confirmar'],
];
const defaultMeasurementDescription = 'Configura en 8 pasos qué escuchar, cómo se incorporan los datos, cómo analizarlos y desde cuándo. Puedes guardar como borrador en cualquier momento.';
const promptKinds = ['Clusters', 'Temas finales', 'Relevancia', 'Sentimiento'];
const promptTypeByLabel: Record<string, string> = { 'Clusters': 'cluster', 'Temas finales': 'temas', 'Relevancia': 'relevancia', 'Sentimiento': 'sentimiento' };

const defaultLoadOptions = { incorporar: true, relevancia: false, sentimiento: true, clusters: false, bots: false };

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

export function MeasurementsPage() {
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
    <PageHeading preview={previewMode} title="Mediciones" description={MEASUREMENT_DESCRIPTION} action={{ label: 'Nueva medición', path: '/mediciones/nueva', icon: 'plus' }} />
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

export function NewMeasurementPage({ yo }: { yo: Yo | null }) {
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

export function MeasurementSourceConfigPage({ yo }: { yo: Yo | null }) {
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
  if (!canEdit) return <><PageHeading preview={previewMode} title="Editar fuentes y opciones" description="La edición de la configuración requiere mediciones:editar." /><section className="panel"><EmptyState title="Sin permiso para editar" detail="Solicita mediciones:editar para modificar esta configuración." /></section></>;
  return <><PageHeading preview={previewMode} title={measurement ? `Editar fuentes · ${measurement.nombre}` : 'Editar fuentes'} description="Actualiza las fuentes, las opciones ‘Al cargar’, Meltwater y el tablero automático." action={{ label: 'Volver al detalle', path: `/mediciones/${id}` }} />
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

export function MeasurementDetail({ yo }: { yo: Yo | null }) {
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
    {loading && <><PageHeading preview={previewMode} title="Cargando medición…" description="Recuperando información de PostgreSQL." /><section className="panel"><EmptyState title="Cargando medición…" /></section></>}
    {error && <><PageHeading preview={previewMode} title="Detalle de medición" description="No se pudo recuperar la información." /><section className="panel"><p className="control-notice error" role="alert">{error}</p></section></>}
    {!loading && !error && !measurement && <><PageHeading preview={previewMode} title="Medición no encontrada" description="No hay una medición disponible para este identificador." /><section className="panel"><EmptyState title="Medición no encontrada" /></section></>}
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
