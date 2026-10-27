import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { RolesList, RoleForm, RoleDetail } from '../../../src/modules/roles/RolesModule';
import { ToastProvider } from '../../../src/shared/Toast';
import type { Yo } from '../../../src/shared/api';

const admin: Yo = {
  usuario: { id: 1, nombre: 'Admin', email: 'admin@example.test', rol_id: 1 },
  rol: { id: 1, nombre: 'Administrador', ver_todas: true },
  permisos: { roles: ['ver', 'crear', 'editar', 'eliminar'], clientes: ['ver'] },
  cuentas_visibles: [],
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Roles y accesos', () => {
  it('muestra roles reales devueltos por la API', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{ id: 1, nombre: 'Administrador', descripcion: 'Acceso global', ver_todas: true,
        permisos: { roles: ['ver', 'crear'] }, estado_id: 1, actualizado_en: '2026-01-01T00:00:00Z' }],
      siguiente: null, total_aprox: 1,
    }), { status: 200 })));
    render(<ToastProvider><MemoryRouter initialEntries={['/roles']}><Routes>
      <Route path="/roles" element={<RolesList yo={admin} />} />
      <Route path="/roles/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    const row = await screen.findByRole('row', { name: 'Ver detalle de Administrador' });
    expect(row).toHaveClass('client-row');
    expect(row.querySelector('.badge.ok')).toHaveTextContent('Activo');
    expect(screen.getByText('2 / 67')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Nuevo rol' })).toBeInTheDocument();
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(screen.getByText('Detalle abierto')).toBeInTheDocument();
  });

  it('no navega al detalle al pulsar una acción de la fila', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{ id: 4, nombre: 'Editor', descripcion: null, ver_todas: false,
        permisos: {}, estado_id: 1, actualizado_en: '2026-01-01T00:00:00Z' }],
      siguiente: null, total_aprox: 1,
    }), { status: 200 })));
    render(<ToastProvider><MemoryRouter initialEntries={['/roles']}><Routes>
      <Route path="/roles" element={<RolesList yo={admin} />} />
      <Route path="/roles/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    fireEvent.click(await screen.findByRole('button', { name: 'Eliminar Editor' }));
    expect(screen.getByRole('dialog', { name: 'Eliminar rol' })).toBeInTheDocument();
    expect(screen.queryByText('Detalle abierto')).not.toBeInTheDocument();
  });

  it('solo presenta pares del catálogo y bloquea asignaciones que el actor no posee', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [
        { modulo: 'clientes', modulo_nombre: 'Clientes', accion: 'ver', accion_nombre: 'Ver' },
        { modulo: 'clientes', modulo_nombre: 'Clientes', accion: 'crear', accion_nombre: 'Crear' },
      ],
    }), { status: 200 })));
    render(<ToastProvider><MemoryRouter initialEntries={['/roles/nuevo']}><Routes>
      <Route path="/roles/nuevo" element={<RoleForm yo={admin} />} />
    </Routes></MemoryRouter></ToastProvider>);
    expect(await screen.findByRole('checkbox', { name: 'Clientes: Ver' })).toBeEnabled();
    expect(screen.getByRole('checkbox', { name: 'Clientes: Crear' })).toBeDisabled();
    expect(screen.queryByRole('checkbox', { name: 'Clientes: Exportar' })).not.toBeInTheDocument();
    expect(screen.queryByText('Configuración completa de mediciones')).not.toBeInTheDocument();
  });

  it('consulta el historial real solo cuando se abre y el actor tiene auditoria:ver', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/historial')) return Promise.resolve(new Response(JSON.stringify([{
        id: 9, fecha: '2026-10-21T12:00:00Z', usuario_id: 1, accion: 'editar',
        antes: { nombre: 'Anterior' }, despues: { nombre: 'Nuevo' },
      }]), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({ id: 4, nombre: 'Nuevo', descripcion: null,
        ver_todas: true, permisos: { roles: ['ver'] }, estado_id: 1 }), { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<ToastProvider><MemoryRouter initialEntries={['/roles/4']}><Routes>
      <Route path="/roles/:id" element={<RoleDetail yo={{ ...admin, permisos: { ...admin.permisos, auditoria: ['ver'] } }} />} />
    </Routes></MemoryRouter></ToastProvider>);
    const historyButton = await screen.findByRole('button', { name: 'Ver historial de cambios' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(historyButton);
    expect(await screen.findByText('editar')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
