import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MeasurementFileHistory, MeasurementFilePicker, MeasurementUploadDialog, uploadMeasurementFiles } from './MeasurementFiles';
import type { PendingMeasurementFile } from './MeasurementFiles';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const formats = [
  { id: 'talkwalker_simple', nombre: 'Formato simple (DBFormatoSimple)', extensiones: ['csv', 'xlsx'], mapeado: true, columnas: [
    { campo_destino: 'url', columnas_origen: ['url'], transformacion: 'directo', requerido: true },
    { campo_destino: 'fecha_publicacion', columnas_origen: ['published'], transformacion: 'fecha', requerido: true },
    { campo_destino: 'titulo', columnas_origen: ['titulo'], transformacion: 'directo', requerido: false },
  ] },
  { id: 'meltwater', nombre: 'Meltwater (export)', extensiones: ['xlsx'], mapeado: true,
    columnas: [{ campo_destino: 'texto', columnas_origen: ['content'], transformacion: 'directo', requerido: true }] },
  { id: 'plantilla_syntra', nombre: 'Plantilla Syntra', extensiones: ['xlsx'], mapeado: false },
];

describe('Archivos de Mediciones', () => {
  it('habilita solo talkwalker_simple con url y published obligatorias; deja Meltwater pendiente', () => {
    const selected: PendingMeasurementFile[] = [];
    const onChange = vi.fn();
    const { container } = render(<MeasurementFilePicker formats={formats} selected={selected} onChange={onChange} />);
    expect(screen.getByText('Meltwater (export) · pendiente de validación')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveValue('talkwalker_simple');
    expect(screen.queryByRole('option', { name: 'Meltwater (export)' })).not.toBeInTheDocument();
    const input = container.querySelector('input[type=file]') as HTMLInputElement;
    const file = new File(['published,url,content,source_type'], 'medios.csv', { type: 'text/csv' });
    fireEvent.change(input, { target: { files: [file] } });
    expect(onChange).toHaveBeenCalledWith([{ file, formatId: 'talkwalker_simple' }]);
  });

  it('rechaza extensión incompatible antes de reservar en la API', () => {
    const onChange = vi.fn();
    const { container } = render(<MeasurementFilePicker formats={formats} selected={[]} onChange={onChange} />);
    fireEvent.change(container.querySelector('input[type=file]') as HTMLInputElement,
                     { target: { files: [new File(['x'], 'otro.txt')] } });
    expect(screen.getByRole('alert')).toHaveTextContent('debe corresponder al formato');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('no habilita formatos cuyo mapeo no confirma el mínimo de DBFormatoSimple', () => {
    render(<MeasurementFilePicker formats={[formats[1]]} selected={[]} onChange={vi.fn()} />);
    expect(screen.getByText('Meltwater (export) · pendiente de validación')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Descargar planilla' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Seleccionar archivos para la medición' })).toHaveAttribute('aria-disabled', 'true');
  });

  it('presenta solo columnas mapeadas y descarga la plantilla entregada por la API', async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
      calls.push(url);
      return calls.length === 1
        ? new Response(JSON.stringify({ url: '/api/v1/formatos/talkwalker_simple/plantilla?token=capability',
            nombre: 'plantilla_talkwalker_simple.xlsx' }), { status: 200 })
        : new Response(new Blob(['xlsx']), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    const NativeURL = globalThis.URL;
    vi.stubGlobal('URL', class TestURL extends NativeURL {
      static createObjectURL = vi.fn(() => 'blob:template');
      static revokeObjectURL = vi.fn();
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<MeasurementFilePicker formats={[{ ...formats[0], columnas: [
      { campo_destino: 'url', columnas_origen: ['url'], transformacion: 'directo', requerido: true },
      { campo_destino: 'fecha_publicacion', columnas_origen: ['published'], transformacion: 'fecha', requerido: true },
      { campo_destino: 'titulo', columnas_origen: ['titulo'], transformacion: 'directo', requerido: false },
    ] }]} selected={[]} onChange={vi.fn()} />);
    expect(screen.getByLabelText('Columnas de la planilla')).toHaveTextContent('url · published · titulo');
    fireEvent.click(screen.getByRole('button', { name: 'Descargar planilla' }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(calls).toEqual(['/api/v1/formatos/talkwalker_simple/plantilla',
      '/api/v1/formatos/talkwalker_simple/plantilla?token=capability']);
    expect(click).toHaveBeenCalledOnce();
  });

  it('reserva, sube y encola los archivos reales en ese orden', async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      calls.push(url);
      if (url.endsWith('/presignar')) return new Response(JSON.stringify({ archivo_id: 9 }), { status: 201 });
      if (url.endsWith('/contenido')) return new Response(null, { status: 204 });
      return new Response(JSON.stringify({ proceso_id: 17 }), { status: 202 });
    });
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['a,b\n1,2'], 'test.csv');
    const completed = new Map<File, number>();
    const upload = () => uploadMeasurementFiles(4, [{ file, formatId: 'talkwalker_simple' }],
                                                { incorporar: false }, completed, 'idempotencia-123456789');
    expect(await upload()).toBe(17);
    expect(calls).toEqual(['/api/v1/mediciones/4/archivos/presignar',
                           '/api/v1/archivos/9/contenido', '/api/v1/mediciones/4/cargas/archivos']);
    expect(completed.get(file)).toBe(9);
    calls.length = 0;
    expect(await upload()).toBe(17);
    expect(calls).toEqual(['/api/v1/mediciones/4/cargas/archivos']);
  });

  it('detecta un archivo idéntico en la reserva por huella sin crear otra carga', async () => {
    const file = new File(['url,published\nhttps://example.test,26/10/26 10:00:00'], 'repetido.csv');
    Object.defineProperty(file, 'arrayBuffer', { value: async () => new ArrayBuffer(4) });
    vi.stubGlobal('crypto', {
      randomUUID: () => 'test-idempotency-key-123456789',
      subtle: { digest: vi.fn(async () => new Uint8Array(32).fill(7).buffer) },
    });
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ detail: {
      codigo: 'archivo_duplicado', archivo_id: 8, proceso_id: 44,
      estado_archivo: 'procesado', estado_proceso: 'completado',
    } }), { status: 409, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(uploadMeasurementFiles(4, [{ file, formatId: 'talkwalker_simple' }],
      { incorporar: true })).rejects.toMatchObject({ status: 409 });
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, request] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(request.body));
    expect(body.sha256).toBe('07'.repeat(32));
    expect(url).toBe('/api/v1/mediciones/4/archivos/presignar');
  });

  it('abre el flujo Nueva carga en el contexto existente y comunica el proceso real encolado', async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
      calls.push(url);
      if (url.endsWith('/formatos')) return new Response(JSON.stringify([formats[0]]), { status: 200 });
      if (url.endsWith('/presignar')) return new Response(JSON.stringify({ archivo_id: 21 }), { status: 201 });
      if (url.endsWith('/contenido')) return new Response(null, { status: 204 });
      return new Response(JSON.stringify({ proceso_id: 71, estado: 'en_cola' }), { status: 202 });
    });
    vi.stubGlobal('fetch', fetchMock);
    const onQueued = vi.fn();
    const onClose = vi.fn();
    const { container } = render(<MeasurementUploadDialog measurementId={12}
      sources={[{ origen: 'archivo', activo: true, al_cargar: { incorporar: true, relevancia: false, sentimiento: false, clusters: false, bots: false } }]}
      canExecute canViewFormats onClose={onClose} onQueued={onQueued} onViewPrevious={vi.fn()} />);
    expect(await screen.findByRole('dialog', { name: 'Nueva carga' })).toHaveTextContent('Medición #12');
    const actions = ['Incorporar automáticamente', 'Evaluar relevancia', 'Evaluar sentimiento', 'Generar clusters', 'Análisis de bots'];
    for (const action of actions) expect(screen.getByRole('group', { name: action })).toBeInTheDocument();
    expect(container.querySelectorAll('.measurement-on-load-grid .measurement-load-card')).toHaveLength(5);
    fireEvent.click(within(screen.getByRole('group', { name: 'Evaluar relevancia' })).getByRole('button', { name: 'Sí' }));
    fireEvent.click(within(screen.getByRole('group', { name: 'Generar clusters' })).getByRole('button', { name: 'Sí' }));
    expect(screen.getByText(/se incorporan automáticamente, incluso si seleccionas relevancia/)).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('group', { name: 'Incorporar automáticamente' })).getByRole('button', { name: 'No' }));
    expect(within(screen.getByRole('group', { name: 'Evaluar relevancia' })).getByRole('button', { name: 'Sí' })).toHaveAttribute('aria-pressed', 'true');
    const file = new File(['url,published\nhttps://example.test,26/10/26 10:00:00'], 'carga.csv', { type: 'text/csv' });
    fireEvent.change(container.querySelector('input[type=file]') as HTMLInputElement, { target: { files: [file] } });
    fireEvent.click(screen.getByRole('button', { name: 'Iniciar carga' }));
    await vi.waitFor(() => expect(onQueued).toHaveBeenCalledWith(71));
    expect(onClose).toHaveBeenCalledOnce();
    expect(calls).toEqual(['/api/v1/formatos', '/api/v1/mediciones/12/archivos/presignar',
      '/api/v1/archivos/21/contenido', '/api/v1/mediciones/12/cargas/archivos']);
    const enqueue = fetchMock.mock.calls.find(([url]) => url.endsWith('/cargas/archivos'));
    expect(JSON.parse(String(enqueue?.[1]?.body)).al_incorporar).toEqual({
      incorporar: false, relevancia: true, sentimiento: false, clusters: true, bots: false,
    });
  });

  it('mantiene deshabilitada Nueva carga si el catálogo no confirma DBFormatoSimple compatible', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify([formats[1]]), { status: 200 })));
    render(<MeasurementUploadDialog measurementId={12} sources={[{ origen: 'archivo', activo: true }]}
      canExecute canViewFormats onClose={vi.fn()} onQueued={vi.fn()} onViewPrevious={vi.fn()} />);
    expect(await screen.findByRole('button', { name: 'Iniciar carga' })).toBeDisabled();
    expect(screen.getByText(/Solo se habilita talkwalker_simple \(DBFormatoSimple\) cuando el catálogo confirma/)).toBeInTheDocument();
  });

  it('muestra el archivo y proceso existentes cuando la API rechaza contenido duplicado', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/formatos')) return new Response(JSON.stringify([formats[0]]), { status: 200 });
      if (url.endsWith('/presignar')) return new Response(JSON.stringify({ archivo_id: 21 }), { status: 201 });
      return new Response(JSON.stringify({ detail: { codigo: 'archivo_duplicado', archivo_id: 8,
        proceso_id: 44, estado_archivo: 'procesado', estado_proceso: 'completado' } }), { status: 409 });
    }));
    const onQueued = vi.fn();
    const onViewPrevious = vi.fn();
    const onClose = vi.fn();
    const { container } = render(<MeasurementUploadDialog measurementId={12}
      sources={[{ origen: 'archivo', activo: true }]} canExecute canViewFormats
      onClose={onClose} onQueued={onQueued} onViewPrevious={onViewPrevious} />);
    await screen.findByRole('combobox');
    fireEvent.change(container.querySelector('input[type=file]') as HTMLInputElement,
                     { target: { files: [new File(['url,published'], 'copia.csv')] } });
    fireEvent.click(screen.getByRole('button', { name: 'Iniciar carga' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('archivo #8, proceso #44');
    expect(onQueued).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Ver carga anterior' }));
    expect(onViewPrevious).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('muestra el historial real y carga el siguiente grupo con el cursor del backend', async () => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url);
      if (url.includes('/lotes')) return new Response(JSON.stringify([{ id: 3, origen: 'archivo',
        estado: 'completado', creado_en: '2026-10-23T12:00:00Z', iniciado_en: '2026-10-23T12:00:00Z',
        finalizado_en: '2026-10-23T12:00:03Z', duracion_ms: 3000, n_leidos: 5, n_nuevos: 4,
        n_duplicados: 1, n_rechazados: 0, proceso_id: 19, red: 'x',
        detalle: 'Archivo de octubre', al_incorporar: { incorporar: true } }]));
      const next = url.includes('cursor=siguiente');
      return new Response(JSON.stringify([{
        id: next ? 1 : 2, nombre: next ? 'anterior.csv' : 'actual.csv', formato_id: 'talkwalker_simple',
        tamano_bytes: 1024, filas_leidas: next ? 3 : 5, estado: next ? 'procesado' : 'procesando',
        subido_por_nombre: 'Administradora', subido_en: '2026-10-23T12:00:00Z',
      }]), { status: 200, headers: next ? {} : { 'X-Next-Cursor': 'siguiente' } });
    }));
    render(<MeasurementFileHistory measurementId={7} formatDate={value => value.slice(0, 10)} sources={[
      { origen: 'archivo', activo: true, al_cargar: { incorporar: true, relevancia: false } },
    ]} />);
    expect(await screen.findByText('actual.csv')).toBeInTheDocument();
    expect(screen.getByText('Al cargar · por tipo de dato')).toBeInTheDocument();
    expect(screen.getByLabelText('Opciones de Archivos (Excel)')).toBeInTheDocument();
    expect(screen.getByText('Fecha de carga')).toBeInTheDocument();
    expect(screen.getByText('Procesando')).toBeInTheDocument();
    expect(await screen.findByText('Lotes de carga')).toBeInTheDocument();
    expect(screen.getByText('3.0 s')).toBeInTheDocument();
    expect(screen.getByText('Archivo de octubre')).toBeInTheDocument();
    expect(screen.getByLabelText('Opciones al cargar del lote')).toBeInTheDocument();
    expect(within(screen.getByLabelText('Opciones al cargar del lote')).getByLabelText('Incorporar automáticamente: Sí')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cargar más' }));
    expect(await screen.findByText('anterior.csv')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cargar más' })).not.toBeInTheDocument();
    expect(calls).toEqual(['/api/v1/mediciones/7/archivos?limite=25',
                           '/api/v1/mediciones/7/lotes?limite=25',
                           '/api/v1/mediciones/7/archivos?limite=25&cursor=siguiente']);
    fireEvent.change(screen.getByRole('combobox', { name: 'Filtrar por fuente' }),
                     { target: { value: 'archivo' } });
    await vi.waitFor(() => expect(calls.at(-1)).toBe('/api/v1/mediciones/7/lotes?limite=25&origen=archivo'));
  });

  it('identifica un fallo terminal de carga sin atribuirlo siempre al formato', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(
      url.includes('/lotes') ? [] : [{ id: 23, nombre: 'fallido.csv', formato_id: 'talkwalker_simple',
        tamano_bytes: 32, filas_leidas: 0, estado: 'error', proceso_id: 99,
        subido_en: '2026-10-26T20:12:00Z' }]), { status: 200 })));
    render(<MeasurementFileHistory measurementId={7} formatDate={value => value} />);
    expect(await screen.findByText('Error de carga')).toBeInTheDocument();
    expect(screen.getByText('Proceso #99')).toBeInTheDocument();
    expect(screen.queryByText('Error de formato')).not.toBeInTheDocument();
  });

  it('separa las tres áreas y muestra solo fuentes activas para próximas cargas', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => new Response(JSON.stringify(url.includes('/lotes') ? [] : []), { status: 200 })));
    render(<MeasurementFileHistory measurementId={7} formatDate={value => value} sources={[
      { origen: 'archivo', activo: true, al_cargar: { incorporar: true } },
      { origen: 'manual', activo: false, al_cargar: { incorporar: false } },
    ]} />);
    const settings = screen.getByRole('region', { name: 'Al cargar por tipo de dato' });
    expect(within(settings).getByText('Archivos (Excel)')).toBeInTheDocument();
    expect(within(settings).queryByText('Manual')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Historial de archivos cargados' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Lotes de carga' })).toBeInTheDocument();
  });

  it('muestra un error HTTP comprensible si el contenido privado ya no está disponible', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/descargar')
      ? new Response(JSON.stringify({ detail: 'El contenido del archivo no está disponible' }),
                     { status: 404, headers: { 'Content-Type': 'application/json' } })
      : url.includes('/lotes') ? new Response(JSON.stringify([]), { status: 200 })
      : new Response(JSON.stringify([{
          id: 9, nombre: 'prueba.csv', formato_id: 'talkwalker_simple', tamano_bytes: 12,
          filas_leidas: 1, estado: 'procesado', subido_en: '2026-10-23T12:00:00Z',
        }]), { status: 200 })));
    render(<MeasurementFileHistory measurementId={7} formatDate={value => value.slice(0, 10)} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Descargar prueba.csv' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'No se pudo descargar el archivo (404): El contenido del archivo no está disponible');
  });

  it('permite reintentar el historial tras un fallo transitorio de la API', async () => {
    let failed = false;
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.includes('/archivos?') && !failed) {
        failed = true;
        return new Response(JSON.stringify({ detail: 'Error temporal' }), { status: 503 });
      }
      return new Response(JSON.stringify(url.includes('/lotes') ? [] : [{
        id: 11, nombre: 'carga.xlsx', formato_id: 'talkwalker_simple', tamano_bytes: 100,
        filas_leidas: 2, estado: 'procesado', subido_en: '2026-10-26T20:12:00Z',
      }]), { status: 200 });
    }));
    render(<MeasurementFileHistory measurementId={7} formatDate={value => value} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 503');
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByText('carga.xlsx')).toBeInTheDocument();
  });
});
