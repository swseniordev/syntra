import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import App from './App';
import { setToken } from '../shared/api';
import { rememberAuditExport } from '../shared/auditExports';

afterEach(() => { cleanup(); setToken(null); sessionStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function CurrentPath() {
  const location = useLocation();
  return <output data-testid="current-path">{location.pathname}{location.search}</output>;
}

function mockLoginApi(success = true) {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => {
    if (url.endsWith('/auth/login')) return success
      ? new Response(JSON.stringify({ access_token: 'token-de-prueba' }), { status: 200 })
      : new Response(JSON.stringify({ detail: 'Credenciales inválidas' }), { status: 401 });
    if (url.endsWith('/auth/refresh')) return new Response(JSON.stringify({ detail: 'Sesión vencida' }), { status: 401 });
    if (url.endsWith('/auth/yo')) return new Response(JSON.stringify({
      usuario: { id: 1, nombre: 'Admin', email: 'admin@syntra.test', rol_id: 1 },
      rol: { id: 1, nombre: 'Administrador', ver_todas: true }, permisos: { dashboard: ['ver'], clientes: ['ver'] }, cuentas_visibles: [],
    }), { status: 200 });
    if (url.includes('/clientes?')) return new Response(JSON.stringify({ items: [], siguiente: null }), { status: 200 });
    return new Response('{}', { status: 200 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('Syntra access screen', () => {
  it('renders the approved institutional claims without demo credentials', () => {
    render(<MemoryRouter initialEntries={['/acceso']}><App /></MemoryRouter>);

    expect(screen.getByText('6')).toBeInTheDocument();
    expect(screen.getByText('< 15 min')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByLabelText('Correo electrónico')).toHaveValue('');
    expect(screen.getByLabelText('Contraseña')).toHaveValue('');
    expect(screen.getByRole('button', { name: /^Ingresar\s*$/ })).toBeEnabled();
    expect(screen.queryByText('¿Olvidaste tu contraseña?')).not.toBeInTheDocument();
    expect(screen.queryByText('Ingresar con SSO corporativo')).not.toBeInTheDocument();
  });

  it('abre Inicio tras un login correcto sin ruta de retorno y permite navegar a Clientes', async () => {
    mockLoginApi();
    render(<MemoryRouter initialEntries={['/acceso']}><App /><CurrentPath /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Correo electrónico'), { target: { value: 'admin@syntra.test' } });
    fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'clave-de-prueba' } });
    fireEvent.click(screen.getByRole('button', { name: /^Ingresar\s*$/ }));
    expect(await screen.findByRole('heading', { name: 'Inicio' })).toBeInTheDocument();
    expect(screen.getByTestId('current-path')).toHaveTextContent(/^\/$/);
    fireEvent.click(screen.getByRole('link', { name: 'Clientes' }));
    expect(screen.getByTestId('current-path')).toHaveTextContent(/^\/clientes$/);
  });

  it('conserva el error de login sin navegar', async () => {
    mockLoginApi(false);
    render(<MemoryRouter initialEntries={['/acceso']}><App /><CurrentPath /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('Correo electrónico'), { target: { value: 'admin@syntra.test' } });
    fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'clave-errónea' } });
    fireEvent.click(screen.getByRole('button', { name: /^Ingresar\s*$/ }));
    expect(await screen.findByRole('alertdialog')).toHaveTextContent('Credenciales inválidas');
    expect(await screen.findByRole('alertdialog')).toHaveTextContent('No se pudo iniciar sesión');
    fireEvent.click(screen.getByRole('button', { name: 'OK' }));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(screen.getByTestId('current-path')).toHaveTextContent(/^\/acceso$/);
  });

  it('regresa a la ruta protegida solicitada después del login', async () => {
    mockLoginApi();
    render(<MemoryRouter initialEntries={['/clientes?origen=directo']}><App /><CurrentPath /></MemoryRouter>);
    expect(await screen.findByLabelText('Correo electrónico')).toBeInTheDocument();
    expect(screen.getByTestId('current-path')).toHaveTextContent(/^\/acceso$/);
    fireEvent.change(screen.getByLabelText('Correo electrónico'), { target: { value: 'admin@syntra.test' } });
    fireEvent.change(screen.getByLabelText('Contraseña'), { target: { value: 'clave-de-prueba' } });
    fireEvent.click(screen.getByRole('button', { name: /^Ingresar\s*$/ }));
    await waitFor(() => expect(screen.getByTestId('current-path')).toHaveTextContent('/clientes?origen=directo'));
  });

  it('envía a Inicio una sesión ya activa que visite Acceso', async () => {
    mockLoginApi();
    setToken('token-de-prueba');
    render(<MemoryRouter initialEntries={['/acceso']}><App /><CurrentPath /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'Inicio' })).toBeInTheDocument();
    expect(screen.getByTestId('current-path')).toHaveTextContent(/^\/$/);
  });
});

describe('Mediciones contra la estructura del mockup', () => {
  const measurement = {
    id: 17, nombre: 'Medición de revisión', cuenta_id: 3, cuenta_nombre: 'Cuenta de revisión', cliente_id: 2,
    estado_id: 1, coyuntura: false, creado_en: '2026-10-24T15:00:00Z', actualizado_en: '2026-10-24T15:30:00Z',
    fuentes: ['archivo'],
    num_clusters: 15, num_subclusters: 3, tipo_analisis: 'general', auto_publicar: false, precluster_activo: false,
    x_num_menciones: 0, x_num_cuentas: 50, preparacion_estado: 'completado', proceso_preparacion_id: 14,
  };
  function mockMeasurementApi(fileSourceActive = true) {
    setToken('token-mediciones');
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/yo')) return new Response(JSON.stringify({ usuario: { id: 1, nombre: 'Admin' }, rol: { id: 1, nombre: 'Administrador' },
        permisos: { mediciones: ['ver', 'crear', 'editar', 'ejecutar'], formatos: ['ver'], clientes: ['ver'], procesos: ['ver'] }, cuentas_visibles: [] }), { status: 200 });
      if (url.includes('/mediciones?')) return new Response(JSON.stringify({ items: [measurement], siguiente: null }), { status: 200 });
      if (url.endsWith('/mediciones/17')) return new Response(JSON.stringify({ ...measurement,
        fuentes: [{ origen: 'archivo', activo: fileSourceActive, al_cargar: { incorporar: true }, config: {} }],
      }), { status: 200 });
      if (url.endsWith('/mediciones/17/resumen')) return new Response(JSON.stringify({
        por_fuente: [
          { origen: 'archivo', cargados: 4, duplicados: 2, por_fiscalizar: 1 },
          { origen: 'manual', cargados: 3, duplicados: 0, por_fiscalizar: 0 },
        ],
      }), { status: 200 });
      if (url.includes('/mediciones/17/archivos?')) return new Response('[]', { status: 200, headers: { 'X-Next-Cursor': '' } });
      if (url.includes('/procesos?medicion_id=17')) return new Response(JSON.stringify([
        { id: 14, medicion_id: 17, tipo: 'preparar_medicion', estado: 'completado', procesados: 1, creado_en: '2026-10-24T15:00:00Z', duracion_ms: 1000 },
      ]), { status: 200 });
      if (url.includes('/clientes?')) return new Response(JSON.stringify({ items: [], siguiente: null }), { status: 200 });
      return new Response(JSON.stringify({ items: [], siguiente: null }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('usa encabezados de tabla estáticos y mantiene solo datos reales disponibles', async () => {
    mockMeasurementApi();
    render(<MemoryRouter initialEntries={['/mediciones']}><App /></MemoryRouter>);
    fireEvent.click(await screen.findByRole('button', { name: 'Vista de lista' }));
    expect(await screen.findByRole('columnheader', { name: 'Por fiscalizar' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Sentimiento' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Actualizado' })).toBeInTheDocument();
    expect(screen.getByText('Medición de revisión')).toBeInTheDocument();
  });

  it('navega entre las ocho pestañas, muestra el pipe y no simula métricas', async () => {
    const fetchMock = mockMeasurementApi();
    render(<MemoryRouter initialEntries={['/mediciones/17']}><App /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'Medición de revisión' })).toBeInTheDocument();
    expect(screen.getAllByRole('tab')).toHaveLength(8);
    expect(screen.getByRole('heading', { name: 'Estado por fuente' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Registros por fecha de publicación' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Últimos procesos' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Resumen' })).not.toBeInTheDocument();
    const statusSection = screen.getByRole('heading', { name: 'Estado por fuente' }).closest('section')!;
    expect(await within(statusSection).findByText('Manual')).toBeInTheDocument();
    expect(within(statusSection).getByText('4')).toBeInTheDocument();
    expect(screen.getByLabelText('Cargados: 7')).toHaveTextContent('7');
    expect(screen.getByLabelText('Enriquecidos: dato no disponible')).toHaveTextContent('—');
    expect(screen.getByRole('link', { name: 'Ver monitor' })).toHaveAttribute('href', '/procesos');
    expect(await screen.findByText('Preparación de medición · #14')).toBeInTheDocument();
    expect(screen.getAllByText('Métrica no disponible en la API actual').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('tab', { name: /Cargas/ }));
    expect(await screen.findByRole('heading', { name: 'Historial de archivos cargados' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /Scraper/ }));
    expect(screen.getByText(/no está disponible en el contrato de detalle actual/i)).toBeInTheDocument();
    for (const [label, pendingTitle] of [['Fiscalización', 'Fiscalización pendiente'], ['Registros', 'Registros pendiente'],
      ['Procesamiento', 'Procesamiento pendiente'], ['Informe', 'Informe pendiente']] as const) {
      fireEvent.click(screen.getByRole('tab', { name: new RegExp(label) }));
      expect(screen.getByRole('heading', { name: pendingTitle })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole('tab', { name: /Configuración/ }));
    expect(screen.getByRole('heading', { name: 'Configuración de análisis' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Resumen' })).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/procesos?medicion_id=17'))).toBe(true));
  });

  it('abre Nueva carga desde el detalle y deja deshabilitado el envío si el catálogo no ofrece formato compatible', async () => {
    mockMeasurementApi();
    render(<MemoryRouter initialEntries={['/mediciones/17']}><App /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'Medición de revisión' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Nueva carga' }));
    expect(await screen.findByRole('dialog', { name: 'Nueva carga' })).toHaveTextContent('Medición #17');
    expect(screen.getByRole('button', { name: 'Iniciar carga' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Cerrar nueva carga' }));
    expect(screen.queryByRole('dialog', { name: 'Nueva carga' })).not.toBeInTheDocument();
  });

  it('no ofrece Nueva carga cuando la fuente Archivos está inactiva', async () => {
    mockMeasurementApi(false);
    render(<MemoryRouter initialEntries={['/mediciones/17?tab=cargas']}><App /></MemoryRouter>);
    expect(await screen.findByRole('heading', { name: 'Medición de revisión' })).toBeInTheDocument();
    const newUpload = screen.getByRole('button', { name: 'Nueva carga' });
    expect(newUpload).toBeDisabled();
    expect(newUpload).toHaveAttribute('title', 'La fuente Archivos está inactiva en esta medición');
    expect(screen.queryByRole('dialog', { name: 'Nueva carga' })).not.toBeInTheDocument();
  });
});

describe('Campana de exportaciones de la pestaña', () => {
  it('muestra la notificación persistida de una carga propia y la marca como leída', async () => {
    setToken('token-de-prueba');
    let read = false;
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/yo')) return new Response(JSON.stringify({
        usuario: { id: 1, nombre: 'Admin' }, rol: { nombre: 'Administrador' },
        permisos: { mediciones: ['ver'] },
      }), { status: 200 });
      if (url.endsWith('/notificaciones?limite=8')) return new Response(JSON.stringify({
        no_leidas: read ? 0 : 1,
        items: [{ id: 9, titulo: 'Carga con advertencias', cuerpo: '4 registros rechazados',
          enlace: '/mediciones/1?tab=cargas', tipo: 'warn', leida: read, creado_en: '2026-10-26T20:12:00Z' }],
      }), { status: 200 });
      if (url.endsWith('/notificaciones/9/leer')) { read = true; return new Response(null, { status: 204 }); }
      return new Response('{}', { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter initialEntries={['/']}><App /><CurrentPath /></MemoryRouter>);
    const bell = await screen.findByRole('button', { name: /Notificaciones: 1 sin leer/ });
    fireEvent.click(bell);
    fireEvent.click(screen.getByRole('button', { name: /Carga con advertencias/ }));
    await waitFor(() => expect(screen.getByTestId('current-path')).toHaveTextContent('/mediciones/1?tab=cargas'));
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/notificaciones/9/leer'))).toBe(true);
  });

  it('solo ofrece descarga para un proceso propio completado y distingue un fallo', async () => {
    setToken('token-de-prueba');
    rememberAuditExport(1, 51);
    rememberAuditExport(1, 52);
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/yo')) return new Response(JSON.stringify({ usuario: { id: 1, nombre: 'Admin' }, rol: { nombre: 'Administrador' },
        permisos: { auditoria: ['ver'], procesos: ['ver'] } }), { status: 200 });
      if (url.endsWith('/ops/colas') || url.endsWith('/ops/workers') || url.includes('/procesos?')) return new Response('[]', { status: 200 });
      if (url.endsWith('/procesos/51')) return new Response(JSON.stringify({ id: 51, estado: 'completado' }), { status: 200 });
      if (url.endsWith('/procesos/52')) return new Response(JSON.stringify({ id: 52, estado: 'error' }), { status: 200 });
      return new Response(JSON.stringify({ items: [], siguiente: null }), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter initialEntries={['/procesos']}><App /></MemoryRouter>);
    const bell = await screen.findByRole('button', { name: /Notificaciones: 1 exportaciones completadas/ });
    fireEvent.click(bell);
    expect(screen.getByText('Exportación de Auditoría #51')).toBeInTheDocument();
    expect(screen.getByText('Exportación de Auditoría #52')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Descargar exportación de Auditoría 51' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Descargar exportación de Auditoría 52' })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/procesos/51'))).toBe(true);
  });

  it('separa mediciones vacías del monitor operativo y muestra tareas reales con sus identificadores', async () => {
    setToken('token-de-prueba');
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/yo')) return new Response(JSON.stringify({ usuario: { id: 7, nombre: 'Admin' }, rol: { nombre: 'Administrador' },
        permisos: { auditoria: ['ver'], procesos: ['ver'], usuarios: ['editar'] } }), { status: 200 });
      if (url.endsWith('/ops/colas')) return new Response(JSON.stringify([
        { cola: 'q.notificaciones', en_cola: 1, en_ejecucion: 0, con_error: 0, mas_antigua_s: 8, workers: 0 },
        { cola: 'q.reportes', en_cola: 0, en_ejecucion: 1, con_error: 0, mas_antigua_s: 0, workers: 1 },
        { cola: 'q.ingesta', en_cola: 2, en_ejecucion: 0, con_error: 1, mas_antigua_s: 15, workers: 1 },
      ]), { status: 200 });
      if (url.endsWith('/ops/workers')) return new Response(JSON.stringify([
        { id: 'local:q.reportes:1', servidor: 'local', colas: ['q.reportes'], iniciado_en: '2026-10-22T10:00:00Z',
          latido: '2026-10-22T10:01:00Z', tareas_en_curso: 1, vivo: false },
        { id: 'local:q.ingesta:1', servidor: 'local', colas: ['q.ingesta'], iniciado_en: '2026-10-22T10:00:00Z',
          latido: '2026-10-22T10:01:00Z', tareas_en_curso: 0, vivo: true },
      ]), { status: 200 });
      if (url.includes('/procesos?')) return new Response(JSON.stringify([
        { id: 83, tipo: 'exportacion', estado: 'error', progreso: 0, total: 0, procesados: 0, ok: 0, errores: 1,
          creado_en: '2026-10-22T10:00:00Z', iniciado_en: '2026-10-22T10:00:01Z', finalizado_en: '2026-10-22T10:00:02Z', duracion_ms: 1000, sla_ms: null },
        { id: 84, tipo: 'correo_acceso', estado: 'completado', progreso: 100, total: 1, procesados: 1, ok: 1, errores: 0,
          creado_en: '2026-10-22T10:00:00Z', iniciado_en: '2026-10-22T10:00:01Z', finalizado_en: '2026-10-22T10:00:02Z', duracion_ms: 1000, sla_ms: null },
        { id: 85, tipo: 'exportacion', estado: 'completado', progreso: 100, total: 1, procesados: 1, ok: 1, errores: 0,
          creado_en: '2026-10-22T10:00:00Z', iniciado_en: '2026-10-22T10:00:01Z', finalizado_en: '2026-10-22T10:00:02Z', duracion_ms: 1000, sla_ms: null },
      ]), { status: 200 });
      if (url.endsWith('/procesos/83/tareas')) return new Response(JSON.stringify([
        { id: 91, clave: 'auditoria', tipo: 'auditoria_exportar', estado: 'error', intentos: 3, ok: 0, errores: 1,
          error_codigo: 'exportacion_fallida', error_mensaje: 'No fue posible generar la exportación.', iniciado_en: null, finalizado_en: null },
      ]), { status: 200 });
      if (url.endsWith('/procesos/84/tareas')) return new Response(JSON.stringify([
        { id: 96, clave: 'correo-acceso', tipo: 'correo_acceso', estado: 'completado', intentos: 1, ok: 1, errores: 0,
          error_codigo: null, error_mensaje: 'Error de tarea registrado; detalle no disponible.', iniciado_en: null, finalizado_en: '2026-10-22T10:00:02Z' },
      ]), { status: 200 });
      if (url.endsWith('/auditoria/exportaciones/85/descarga')) return new Response(JSON.stringify({ url: '/api/v1/auditoria/exportaciones/85/archivo' }), { status: 200 });
      if (url.endsWith('/auditoria/exportaciones/85/archivo')) return new Response('xlsx-bytes', { status: 200 });
      return new Response('[]', { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter initialEntries={['/procesos']}><App /></MemoryRouter>);
    expect((await screen.findAllByText('Envío de correos')).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText('Ingesta de archivos').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('local:q.ingesta:1')).toBeInTheDocument();
    expect(screen.getAllByText('1 worker con latido reciente').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Sin worker con latido reciente')).toBeInTheDocument();
    expect(screen.getByText('Vencido')).toBeInTheDocument();
    expect(screen.getByText('Duración de las últimas ejecuciones')).toBeInTheDocument();
    expect(screen.getByText('Completados (24 h)')).toBeInTheDocument();
    expect(screen.getAllByText('Indicador de mediciones · aún sin datos')).toHaveLength(2);
    expect(screen.getByText('Las cargas, fiscalizaciones y procesamientos aparecerán aquí cuando el módulo de mediciones tenga datos disponibles.')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/procesos/estadisticas'))).toBe(false);
    expect(document.querySelectorAll('.process-workers-table')).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Ver tarea del proceso #83' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Descargar XLSX de exportación #83' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Descargar XLSX de exportación #84' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Descargar XLSX de exportación #85' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Ver tarea del proceso #84' }));
    expect(await screen.findByText('Tarea #96 · correo-acceso')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/procesos/84/tareas'))).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Ver tarea del proceso #83' }));
    expect(await screen.findByText(/exportacion_fallida/)).toBeInTheDocument();
    expect(screen.getByText('No fue posible generar la exportación.')).toBeInTheDocument();
    expect(screen.getByText('Tarea #91 · auditoria')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/procesos/83/tareas'))).toBe(true);
    expect(screen.queryByText(/SMTP|token|payload/i)).not.toBeInTheDocument();
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:exportacion'), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    fireEvent.click(screen.getByRole('button', { name: 'Descargar XLSX de exportación #85' }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/auditoria/exportaciones/85/archivo'))).toBe(true));
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/auditoria/exportaciones/85/descarga'))).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/ops/colas'))).toBe(true);
  });

  it('reutiliza la carga paginada de Auditoría: 25 registros, cursor, anterior/siguiente y fin deshabilitado', async () => {
    setToken('token-de-prueba');
    const processes = Array.from({ length: 27 }, (_, index) => ({
      id: 200 - index, tipo: 'exportacion', estado: 'completado', progreso: 100, total: 1, procesados: 1, ok: 1, errores: 0,
      creado_en: `2026-10-${String(22 - Math.floor(index / 24)).padStart(2, '0')}T10:00:00Z`, iniciado_en: null,
      finalizado_en: `2026-10-${String(22 - Math.floor(index / 24)).padStart(2, '0')}T10:01:00Z`, duracion_ms: 60000, sla_ms: null,
    }));
    const calls: string[] = [];
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      calls.push(String(url));
      if (url.endsWith('/auth/yo')) return new Response(JSON.stringify({ usuario: { id: 7, nombre: 'Admin' }, rol: { nombre: 'Administrador' },
        permisos: { auditoria: ['ver'], procesos: ['ver'] } }), { status: 200 });
      if (url.endsWith('/ops/colas')) return new Response('[]', { status: 200 });
      if (url.endsWith('/ops/workers')) return new Response(JSON.stringify([
        { id: 'worker-current', servidor: 'local', colas: ['q.reportes'], iniciado_en: '2026-10-22T10:00:00Z', latido: '2026-10-22T10:01:00Z', tareas_en_curso: 0, vivo: true },
      ]), { status: 200 });
      if (url.includes('/procesos?')) {
        const request = new URL(url, 'https://syntra.test');
        const cursor = request.searchParams.get('cursor');
        const limit = Number(request.searchParams.get('limite'));
        const rows = cursor ? processes.slice(24, 24 + limit) : processes.slice(0, limit);
        return new Response(JSON.stringify(rows), { status: 200, headers: {
          ...(cursor ? {} : { 'X-Next-Cursor': 'cursor-page-2' }),
        } });
      }
      return new Response('[]', { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter initialEntries={['/procesos']}><App /></MemoryRouter>);
    expect(await screen.findByText('25 registros')).toBeInTheDocument();
    expect(screen.getByText('worker-current')).toBeInTheDocument();
    expect(document.querySelectorAll('.process-workers-table tbody tr')).toHaveLength(25);
    expect(document.querySelector('.process-workers-panel .table-pager-current')).toHaveTextContent('1');
    const firstPageRequest = calls.find(url => url.includes('/procesos?'))!;
    expect(new URL(firstPageRequest, 'https://syntra.test').searchParams.get('limite')).toBe('24');
    fireEvent.click(screen.getByRole('button', { name: 'Página siguiente' }));
    await waitFor(() => expect(calls.some(url => url.includes('limite=25') && url.includes('cursor=cursor-page-2'))).toBe(true));
    expect(document.querySelectorAll('.process-workers-table tbody tr')).toHaveLength(3);
    expect(document.querySelector('.process-workers-panel .table-pager-current')).toHaveTextContent('2');
    expect(screen.queryByText('worker-current')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Página siguiente' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Página anterior' }));
    expect(document.querySelector('.process-workers-panel .table-pager-current')).toHaveTextContent('1');
    expect(screen.getByText('worker-current')).toBeInTheDocument();
    expect(calls.filter(url => url.includes('/procesos?')).every(url => ['24', '25'].includes(new URL(url, 'https://syntra.test').searchParams.get('limite') || ''))).toBe(true);
  });
});
