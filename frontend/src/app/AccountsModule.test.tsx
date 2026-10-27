import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AccountsList, AccountForm } from './AccountsModule';
import { ToastProvider } from '../shared/Toast';
import type { Yo } from '../shared/api';

const admin: Yo = {
  usuario: { id: 1, nombre: 'Admin', email: 'admin@example.test', rol_id: 1 },
  rol: { id: 1, nombre: 'Administrador', ver_todas: true },
  permisos: { cuentas: ['ver', 'crear', 'editar', 'eliminar'], clientes: ['ver'], auditoria: ['ver'] },
  cuentas_visibles: [],
};
const account = { id: 8, nombre: 'Cuenta real', cliente_id: 2, cliente_nombre: 'Cliente real',
  actor_principal: null, entidad: null, taxonomia: 'gobierno', prompt_clusters: 'Agrupa registros por tema.',
  prompt_temas: 'Resume los temas del debate.', estado_id: 1, creado_en: '2026-10-21T00:00:00Z',
  creado_por: 1, actualizado_en: '2026-10-21T00:00:00Z', actualizado_por: 1 };
const client = { id: 2, nombre: 'Cliente real', estado_id: 1 };
function fetcher(url: string) {
  const data = url.startsWith('/api/v1/clientes') ? { items: [client], siguiente: null }
    : url.startsWith('/api/v1/prompts') ? { items: [], siguiente: null }
      : { items: [account], siguiente: null, total_aprox: 1 };
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200 }));
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Cuentas con el patrón de Clientes', () => {
  it('muestra cliente real, badge, iconos y fila seleccionable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetcher));
    render(<ToastProvider><MemoryRouter initialEntries={['/cuentas']}><Routes>
      <Route path="/cuentas" element={<AccountsList yo={admin} />} />
      <Route path="/cuentas/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    const row = await screen.findByRole('row', { name: 'Ver detalle de Cuenta real' });
    expect(row).toHaveClass('client-row');
    expect(row).toHaveTextContent('Cliente real');
    expect(row.querySelector('.badge.ok')).toHaveTextContent('Activo');
    expect(screen.getByRole('link', { name: 'Ver historial de cambios de Cuenta real' })).toBeInTheDocument();
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(screen.getByText('Detalle abierto')).toBeInTheDocument();
  });

  it('eliminar abre confirmación sin navegar', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetcher));
    render(<ToastProvider><MemoryRouter initialEntries={['/cuentas']}><Routes>
      <Route path="/cuentas" element={<AccountsList yo={admin} />} />
      <Route path="/cuentas/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    fireEvent.click(await screen.findByRole('button', { name: 'Eliminar Cuenta real' }));
    expect(screen.getByRole('dialog', { name: 'Eliminar cuenta' })).toBeInTheDocument();
    expect(screen.queryByText('Detalle abierto')).not.toBeInTheDocument();
  });

  it('el formulario usa clientes reales y deja los prompts vacíos hasta seleccionarlos', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation(fetcher));
    render(<ToastProvider><MemoryRouter><AccountForm /></MemoryRouter></ToastProvider>);
    expect(await screen.findByRole('option', { name: 'Cliente real' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Prompt de clusters *' })).toHaveValue('');
    expect(screen.getByRole('textbox', { name: 'Prompt de temas finales *' })).toHaveValue('');
  });
});
