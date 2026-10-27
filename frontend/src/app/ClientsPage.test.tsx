import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { ClientDetail, ClientsPage, CreationFormPage } from './App';
import type { Cliente, Yo } from '../shared/api';
import { ToastProvider } from '../shared/Toast';

const client: Cliente = {
  id: 1, nombre: 'Cliente aislado', rfc: null, sector: null, contacto: null,
  estado_id: 1, creado_en: '2026-01-01T00:00:00Z', creado_por: 1,
  actualizado_en: '2026-01-01T00:00:00Z', actualizado_por: 1,
};
const admin: Yo = {
  usuario: { id: 1, nombre: 'Admin aislado', email: 'admin@example.test', rol_id: 1 },
  rol: { id: 1, nombre: 'Administrador', ver_todas: true },
  permisos: { clientes: ['ver', 'editar', 'eliminar'], cuentas: ['ver'], auditoria: ['ver'] },
  cuentas_visibles: [],
};

function mount(item: Cliente = client) {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => {
    if (url.includes('/clientes/sectores')) return new Response(JSON.stringify({ items: ['OPERACION', 'SALUD'] }), { status: 200 });
    const visible = item.estado_id !== -1 || url.includes('estado=eliminados');
    return new Response(
      JSON.stringify({ items: visible ? [item] : [], siguiente: null, total_aprox: visible ? 1 : 0 }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    );
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<ToastProvider><MemoryRouter initialEntries={['/clientes']}><Routes>
    <Route path="/clientes" element={<ClientsPage yo={admin} />} />
    <Route path="/clientes/:id" element={<p>Detalle de prueba</p>} />
    <Route path="/clientes/:id/editar" element={<p>Edición de prueba</p>} />
  </Routes></MemoryRouter></ToastProvider>);
  return fetchMock;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Tabla de Clientes', () => {
  it('muestra cuatro iconos, habilita historial autorizado y abre el detalle con la fila', async () => {
    mount();
    const row = await screen.findByRole('row', { name: 'Ver detalle de Cliente aislado' });
    expect(screen.getByRole('link', { name: 'Editar Cliente aislado' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Inactivar Cliente aislado' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Eliminar Cliente aislado' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ver historial de cambios de Cliente aislado' })).toHaveAttribute('href', '/clientes/1?historial=1');
    expect(screen.queryByRole('link', { name: 'Ver' })).not.toBeInTheDocument();
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(screen.getByText('Detalle de prueba')).toBeInTheDocument();
  });

  it('la fila abre el detalle con el mouse, pero el historial es una acción independiente', async () => {
    mount();
    await screen.findByRole('row', { name: 'Ver detalle de Cliente aislado' });
    fireEvent.click(screen.getByRole('link', { name: 'Ver historial de cambios de Cliente aislado' }));
    expect(screen.getByText('Detalle de prueba')).toBeInTheDocument();
  });

  it('sin auditoria:ver no presenta el icono del historial', async () => {
    const fetchMock = vi.fn().mockImplementation(fetcherWithoutHistory);
    vi.stubGlobal('fetch', fetchMock);
    render(<ToastProvider><MemoryRouter initialEntries={['/clientes']}><ClientsPage yo={{ ...admin, permisos: { clientes: ['ver'] } }} /></MemoryRouter></ToastProvider>);
    await screen.findByRole('row', { name: 'Ver detalle de Cliente aislado' });
    expect(screen.queryByRole('link', { name: /Ver historial de cambios/ })).not.toBeInTheDocument();
  });

  it('la fila sigue abriendo el detalle sin accionar el historial', async () => {
    mount();
    const row = await screen.findByRole('row', { name: 'Ver detalle de Cliente aislado' });
    fireEvent.click(row.querySelector('td')!);
    expect(screen.getByText('Detalle de prueba')).toBeInTheDocument();
  });

  it('las acciones no abren el detalle y envían el cambio de estado al endpoint real', async () => {
    const fetchMock = mount();
    await screen.findByRole('row', { name: 'Ver detalle de Cliente aislado' });
    fireEvent.click(screen.getByRole('button', { name: 'Inactivar Cliente aislado' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/clientes/1/estado', expect.objectContaining({ method: 'POST', body: '{"estado_id":0}' }),
    ));
    expect(screen.queryByText('Detalle de prueba')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Eliminar Cliente aislado' }));
    expect(screen.getByRole('dialog', { name: 'Eliminar cliente' })).toBeInTheDocument();
    expect(screen.queryByText('Detalle de prueba')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
    fireEvent.click(await screen.findByRole('link', { name: 'Editar Cliente aislado' }));
    expect(screen.getByText('Edición de prueba')).toBeInTheDocument();
  });

  it('ofrece Restaurar solo en Eliminados y no abre el detalle de esa fila', async () => {
    const fetchMock = mount({ ...client, estado_id: -1 });
    fireEvent.click(screen.getByRole('button', { name: /Eliminados/ }));
    const row = await screen.findByRole('row', { name: 'Cliente eliminado Cliente aislado' });
    expect(screen.queryByRole('link', { name: 'Editar Cliente aislado' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Eliminar Cliente aislado' })).not.toBeInTheDocument();
    fireEvent.click(row.querySelector('td')!);
    expect(screen.queryByText('Detalle de prueba')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Restaurar Cliente aislado' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/clientes/1/restaurar', expect.objectContaining({ method: 'POST' }),
    ));
    expect(await screen.findByText('Restaurado como Inactivo')).toBeInTheDocument();
    expect(screen.queryByText('Detalle de prueba')).not.toBeInTheDocument();
  });
});

function fetcherWithoutHistory(url: string) {
  return Promise.resolve(new Response(JSON.stringify(url.includes('/sectores') ? { items: [] } : { items: [client], siguiente: null }), { status: 200 }));
}

describe('Detalle de Clientes', () => {
  it('muestra historial real, estado vacío y errores según la respuesta protegida', async () => {
    let historyResponse = new Response(JSON.stringify([]), { status: 200 });
    const fetchMock = vi.fn().mockImplementation(async (url: string) => url.includes('/historial') ? historyResponse
      : new Response(JSON.stringify(url.includes('/cuentas?') ? { items: [], siguiente: null } : client), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    render(<ToastProvider><MemoryRouter initialEntries={['/clientes/1?historial=1']}><Routes><Route path="/clientes/:id" element={<ClientDetail yo={admin} />} /></Routes></MemoryRouter></ToastProvider>);
    expect(await screen.findByText('Sin cambios registrados')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Ocultar historial' }));
    historyResponse = new Response(JSON.stringify([{ id: 9, fecha: '2026-10-21T12:00:00Z', accion: 'editar', usuario_id: 1,
      antes: { nombre: 'Anterior' }, despues: { nombre: 'Actual' } }]), { status: 200 });
    fireEvent.click(screen.getByRole('button', { name: 'Ver historial de cambios' }));
    expect(await screen.findByText('editar')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Ocultar historial' }));
    historyResponse = new Response(JSON.stringify({ detail: 'Consulta denegada' }), { status: 403 });
    fireEvent.click(screen.getByRole('button', { name: 'Ver historial de cambios' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No tienes permiso');
  });
  it('presenta nombres reales y fechas de creación y última actualización', async () => {
    const detail = { ...client, creado_por_nombre: 'Creadora real', actualizado_por_nombre: 'Editora real', actualizado_en: '2026-01-02T00:00:00Z' };
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string) => new Response(
      JSON.stringify(url.includes('/cuentas?') ? { items: [], siguiente: null } : detail), { status: 200 },
    )));
    render(<ToastProvider><MemoryRouter initialEntries={['/clientes/1']}><Routes><Route path="/clientes/:id" element={<ClientDetail yo={admin} />} /></Routes></MemoryRouter></ToastProvider>);
    expect(await screen.findByText('Creadora real')).toBeInTheDocument();
    expect(screen.getByText('Editora real')).toBeInTheDocument();
    expect(screen.getByText('31 dic 2025, 19:00')).toBeInTheDocument();
    expect(screen.getByText('01 ene 2026, 19:00')).toBeInTheDocument();
    expect(document.querySelector('time[datetime="2026-01-01T00:00:00Z"]')).toBeInTheDocument();
    expect(document.querySelector('time[datetime="2026-01-02T00:00:00Z"]')).toBeInTheDocument();
  });
  it('muestra cuentas reales activas e inactivas desde el filtro del contrato', async () => {
    const fetchMock = vi.fn().mockImplementation(async (url: string) => new Response(
      JSON.stringify(url.includes('/cuentas?')
        ? { items: [{ id: 10, cliente_id: 1, nombre: 'Cuenta real activa', estado_id: 1 }, { id: 11, cliente_id: 1, nombre: 'Cuenta real inactiva', estado_id: 0 }], siguiente: null }
        : client),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchMock);
    render(<ToastProvider><MemoryRouter initialEntries={['/clientes/1']}><Routes><Route path="/clientes/:id" element={<ClientDetail yo={admin} />} /></Routes></MemoryRouter></ToastProvider>);
    expect(await screen.findByText('Cuenta real activa')).toBeInTheDocument();
    expect(screen.getByText('Cuenta real inactiva')).toBeInTheDocument();
    expect(screen.getByText('Activa')).toBeInTheDocument();
    expect(screen.getByText('Inactiva')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/cuentas?cliente_id=1&estado=vigentes&limite=200'))).toBe(true);
  });

  it('no consulta las cuentas sin el permiso cuentas:ver', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(client), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    render(<ToastProvider><MemoryRouter initialEntries={['/clientes/1']}><Routes><Route path="/clientes/:id" element={<ClientDetail yo={{ ...admin, permisos: { clientes: ['ver'] } }} />} /></Routes></MemoryRouter></ToastProvider>);
    expect(await screen.findByText('No tienes permiso para consultar cuentas asociadas.')).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes('/cuentas?'))).toBe(true);
  });
});

describe('Sectores y notificaciones de Clientes', () => {
  it('carga sectores de la API y aplica el filtro seleccionado', async () => {
    const fetchMock = mount();
    fireEvent.change(await screen.findByRole('combobox', { name: 'Sector' }), { target: { value: 'OPERACION' } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/clientes?estado=vigentes&sector=OPERACION'))).toBe(true));
    expect(screen.getAllByRole('option', { name: 'OPERACION' })).toHaveLength(1);
  });

  it('muestra éxito solo tras la respuesta del cambio de estado', async () => {
    const fetchMock = mount();
    await screen.findByRole('row', { name: 'Ver detalle de Cliente aislado' });
    fireEvent.click(screen.getByRole('button', { name: 'Inactivar Cliente aislado' }));
    expect(await screen.findByText('Inactivado')).toBeInTheDocument();
    expect(screen.getAllByText('Inactivado')).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith('/clientes/1/estado') && init.method === 'POST')).toBe(true);
  });

  it('muestra error de backend sin éxito y conserva el registro', async () => {
    const fetchMock = mount();
    fetchMock.mockImplementation(async (url: string) => {
      if (url.includes('/clientes/sectores')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/estado')) return new Response(JSON.stringify({ detail: 'No se pudo cambiar el estado' }), { status: 409 });
      return new Response(JSON.stringify({ items: [client], siguiente: null }), { status: 200 });
    });
    await screen.findByRole('row', { name: 'Ver detalle de Cliente aislado' });
    fireEvent.click(screen.getByRole('button', { name: 'Inactivar Cliente aislado' }));
    expect(await screen.findByRole('alertdialog')).toHaveTextContent('No se pudo cambiar el estado');
    expect(screen.queryByText('Inactivado')).not.toBeInTheDocument();
    expect(screen.getByRole('row', { name: 'Ver detalle de Cliente aislado' })).toBeInTheDocument();
  });

  it('notifica la eliminación lógica confirmada y el bloqueo por cuentas activas', async () => {
    const fetchMock = mount();
    let blocked = true;
    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url.includes('/clientes/sectores')) return new Response(JSON.stringify({ items: [] }), { status: 200 });
      if (url.endsWith('/clientes/1') && init?.method === 'DELETE') return blocked
        ? new Response(JSON.stringify({ detail: 'El cliente tiene cuentas asociadas activas' }), { status: 409 })
        : new Response(null, { status: 204 });
      return new Response(JSON.stringify({ items: [client], siguiente: null }), { status: 200 });
    });
    await screen.findByRole('row', { name: 'Ver detalle de Cliente aislado' });
    fireEvent.click(screen.getByRole('button', { name: 'Eliminar Cliente aislado' }));
    fireEvent.click(screen.getByRole('button', { name: /^Eliminar$/ }));
    expect(await screen.findByText('No se pudo eliminar')).toBeInTheDocument();
    expect(screen.queryByText('Eliminado lógicamente')).not.toBeInTheDocument();
    blocked = false;
    fireEvent.click(screen.getByRole('button', { name: /^Eliminar$/ }));
    expect(await screen.findByText('Eliminado lógicamente')).toBeInTheDocument();
  });

  it('confirma creación antes de mostrar toast y muestra error si falla el backend', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Ya existe un cliente vigente con ese nombre' }), { status: 409 }));
    vi.stubGlobal('fetch', fetchMock);
    render(<ToastProvider><MemoryRouter initialEntries={['/clientes/nuevo']}><Routes>
      <Route path="/clientes/nuevo" element={<CreationFormPage path="/clientes" />} />
      <Route path="/clientes" element={<p>Lista</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    fireEvent.change(screen.getByLabelText(/Nombre del cliente/), { target: { value: '  Nombre nuevo  ' } });
    fireEvent.click(screen.getByRole('button', { name: /Guardar/ }));
    expect(await screen.findByText('No se pudo guardar el cliente')).toBeInTheDocument();
    expect(screen.queryByText('Cliente creado')).not.toBeInTheDocument();
    expect(screen.queryByText('Lista')).not.toBeInTheDocument();
    fetchMock.mockResolvedValue(new Response('{}', { status: 201 }));
    fireEvent.click(screen.getByRole('button', { name: /Guardar/ }));
    expect(await screen.findByText('Lista')).toBeInTheDocument();
    expect(screen.getByText('Cliente creado')).toBeInTheDocument();
    expect(fetchMock.mock.calls.at(-1)?.[1].body).toContain('"nombre":"Nombre nuevo"');
  });

  it('muestra Cambios guardados solo después de editar con If-Match', async () => {
    const fetchMock = vi.fn().mockImplementation(async (_url: string, init?: RequestInit) =>
      init?.method === 'PATCH' ? new Response('{}', { status: 200 })
        : new Response(JSON.stringify(client), { status: 200, headers: { ETag: '"version-real"' } }),
    );
    vi.stubGlobal('fetch', fetchMock);
    render(<ToastProvider><MemoryRouter initialEntries={['/clientes/1/editar']}><Routes>
      <Route path="/clientes/:id/editar" element={<CreationFormPage path="/clientes" editId={1} />} />
      <Route path="/clientes/:id" element={<p>Detalle guardado</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    expect(await screen.findByDisplayValue('Cliente aislado')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Nombre del cliente/), { target: { value: '  Cliente editado  ' } });
    fireEvent.click(screen.getByRole('button', { name: /Guardar/ }));
    expect(await screen.findByText('Detalle guardado')).toBeInTheDocument();
    expect(screen.getByText('Cambios guardados')).toBeInTheDocument();
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
    expect(new Headers(patch?.[1].headers).get('If-Match')).toBe('"version-real"');
    expect(patch?.[1].body).toContain('"nombre":"Cliente editado"');
  });
});
