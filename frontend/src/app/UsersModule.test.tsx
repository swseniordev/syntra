import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { UsersList, UserForm } from './UsersModule';
import { ToastProvider } from '../shared/Toast';
import type { Yo } from '../shared/api';

const admin: Yo = {
  usuario: { id: 1, nombre: 'Admin', email: 'admin@example.test', rol_id: 1 },
  rol: { id: 1, nombre: 'Administrador', ver_todas: true },
  permisos: { usuarios: ['ver', 'crear', 'editar', 'eliminar'], roles: ['ver'], grupos: ['ver'], auditoria: ['ver'] },
  cuentas_visibles: [],
};
const user = { id: 2, nombre: 'Persona real', email: 'persona@example.test', telefono: null, rol_id: 4,
  grupo_ids: [3], ultimo_acceso: null, estado_id: 1, creado_en: '2026-10-21T00:00:00Z', actualizado_en: '2026-10-21T00:00:00Z' };
function fetcher(url: string) {
  const data = url.startsWith('/api/v1/roles') ? { items: [{ id: 4, nombre: 'Consultor', ver_todas: false, estado_id: 1 }], siguiente: null }
    : url.startsWith('/api/v1/grupos') ? { items: [{ id: 3, nombre: 'Grupo real', cuenta_ids: [9], estado_id: 1 }], siguiente: null }
      : { items: [user], siguiente: null, total_aprox: 1 };
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }));
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Usuarios según Clientes y el mockup', () => {
  it('usa fila seleccionable, badge real y acciones independientes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetcher));
    render(<ToastProvider><MemoryRouter initialEntries={['/usuarios']}><Routes>
      <Route path="/usuarios" element={<UsersList yo={admin} />} />
      <Route path="/usuarios/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    const row = await screen.findByRole('row', { name: 'Ver detalle de Persona real' });
    expect(row).toHaveClass('client-row');
    expect(row.querySelector('.badge.ok')).toHaveTextContent('Activo');
    expect(row).toHaveTextContent('Grupo real');
    expect(row).toHaveTextContent('Consultor');
    fireEvent.click(screen.getByRole('button', { name: 'Eliminar Persona real' }));
    expect(screen.getByRole('dialog', { name: 'Eliminar usuario' })).toBeInTheDocument();
    expect(screen.queryByText('Detalle abierto')).not.toBeInTheDocument();
  });

  it('toma roles y grupos reales; el alta queda activa y el correo se indica como pendiente', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetcher));
    render(<ToastProvider><MemoryRouter><UserForm yo={admin} /></MemoryRouter></ToastProvider>);
    expect(await screen.findByRole('option', { name: 'Consultor · por grupos' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Grupo real/ })).not.toBeChecked();
    expect(screen.getByText(/se encolará una contraseña temporal/)).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveClass('user-mail-notice');
    expect(screen.getByRole('note')).toHaveTextContent('el envío es asíncrono');
    expect(screen.getByText(/Si el rol no tiene acceso global/).tagName).toBe('SMALL');
    expect(screen.getByLabelText('Estado')).toBeDisabled();
  });
});
