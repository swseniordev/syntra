import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { GroupsList, GroupForm } from '../../../src/modules/grupos/GroupsModule';
import { ToastProvider } from '../../../src/shared/Toast';
import type { Yo } from '../../../src/shared/api';

const admin: Yo = {
  usuario: { id: 1, nombre: 'Admin', email: 'admin@example.test', rol_id: 1 },
  rol: { id: 1, nombre: 'Administrador', ver_todas: true },
  permisos: { grupos: ['ver', 'crear', 'editar', 'eliminar'], usuarios: ['ver'], cuentas: ['ver'], auditoria: ['ver'] },
  cuentas_visibles: [],
};
const group = { id: 7, nombre: 'Equipo Norte', descripcion: 'Investigación', usuario_ids: [2], cuenta_ids: [8],
  estado_id: 1, creado_en: '2026-10-21T00:00:00Z', actualizado_en: '2026-10-21T00:00:00Z' };
function fetcher(url: string) {
  const data = url.startsWith('/api/v1/usuarios') ? { items: [{ id: 2, nombre: 'Persona real', email: 'persona@example.test', rol_id: 3, estado_id: 1 }], siguiente: null }
    : url.startsWith('/api/v1/cuentas') ? { items: [{ id: 8, nombre: 'Cuenta real', cliente_nombre: 'Cliente real', estado_id: 1 }], siguiente: null }
      : { items: [group], siguiente: null, total_aprox: 1 };
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }));
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Grupos según patrón de Clientes', () => {
  it('fila seleccionable, badge y acciones separadas', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetcher));
    render(<ToastProvider><MemoryRouter initialEntries={['/grupos']}><Routes>
      <Route path="/grupos" element={<GroupsList yo={admin} />} />
      <Route path="/grupos/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    const row = await screen.findByRole('row', { name: 'Ver detalle de Equipo Norte' });
    expect(row).toHaveClass('client-row');
    expect(row.querySelector('.badge.ok')).toHaveTextContent('Activo');
    expect(screen.getByRole('link', { name: 'Ver historial de cambios de Equipo Norte' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Eliminar Equipo Norte' }));
    expect(screen.getByRole('dialog', { name: 'Eliminar grupo' })).toBeInTheDocument();
    expect(screen.queryByText('Detalle abierto')).not.toBeInTheDocument();
  });

  it('el formulario muestra opciones reales de usuarios y cuentas', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => url.startsWith('/api/v1/usuarios')
      ? Promise.resolve(new Response(JSON.stringify({ items: [
        { id: 2, nombre: 'Persona real', email: 'persona@example.test', rol_id: 3, estado_id: 1 },
        { id: 3, nombre: 'Otra persona', email: 'otra@example.test', rol_id: 3, estado_id: 1 },
      ], siguiente: null }), { status: 200 })) : fetcher(url)));
    render(<ToastProvider><MemoryRouter><GroupForm /></MemoryRouter></ToastProvider>);
    expect(await screen.findByText('Persona real')).toBeInTheDocument();
    expect(screen.getByText('Cuenta real')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Persona real/ })).not.toBeChecked();
    const users = screen.getByRole('region', { name: 'Seleccionar usuarios' });
    fireEvent.click(within(users).getByRole('checkbox', { name: /Persona real/ }));
    expect(within(users).getByText('1')).toHaveClass('group-picker-count');
    fireEvent.click(within(users).getByRole('checkbox', { name: /Otra persona/ }));
    expect(within(users).getByText('2')).toHaveClass('group-picker-count');
    fireEvent.change(within(users).getByRole('searchbox', { name: 'Filtrar usuarios' }), { target: { value: 'sin coincidencia' } });
    expect(within(users).getByText('Sin resultados para el filtro.')).toBeInTheDocument();
    fireEvent.change(within(users).getByRole('searchbox', { name: 'Filtrar usuarios' }), { target: { value: '' } });
    expect(within(users).getByRole('checkbox', { name: /Persona real/ })).toBeChecked();
    expect(within(users).getByRole('checkbox', { name: /Otra persona/ })).toBeChecked();
  });
});
