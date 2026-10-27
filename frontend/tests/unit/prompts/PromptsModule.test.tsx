import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { PromptsList, PromptForm, PromptDetail } from '../../../src/modules/prompts/PromptsModule';
import { ToastProvider } from '../../../src/shared/Toast';
import type { Yo } from '../../../src/shared/api';

const admin: Yo = {
  usuario: { id: 1, nombre: 'Admin', email: 'admin@example.test', rol_id: 1 },
  rol: { id: 1, nombre: 'Administrador', ver_todas: true },
  permisos: { prompts: ['ver', 'crear', 'editar', 'eliminar'], auditoria: ['ver'] },
  cuentas_visibles: [],
};
const prompt = { id: 2, nombre: 'Relevancia general', tipo: 'relevancia', red: null,
  contenido: 'Evalúa si el contenido es relevante para la cuenta.', por_defecto: true,
  version_actual: 2, estado_id: 1, creado_en: '2026-10-21T00:00:00Z', creado_por: 1,
  actualizado_en: '2026-10-21T00:00:00Z', actualizado_por: 1 };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Prompts con el patrón de Clientes', () => {
  it('muestra datos reales, badge y acciones; la fila abre detalle por teclado', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [prompt], siguiente: null, total_aprox: 1 }), { status: 200 })));
    render(<ToastProvider><MemoryRouter initialEntries={['/prompts']}><Routes>
      <Route path="/prompts" element={<PromptsList yo={admin} />} />
      <Route path="/prompts/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    const row = await screen.findByRole('row', { name: 'Ver detalle de Relevancia general' });
    expect(row).toHaveClass('client-row');
    expect(row.querySelector('.badge.ok')).toHaveTextContent('Activo');
    expect(row).toHaveTextContent('v2');
    expect(row).toHaveTextContent('★ Por defecto');
    expect(screen.getByRole('link', { name: 'Ver historial de cambios de Relevancia general' })).toBeInTheDocument();
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(screen.getByText('Detalle abierto')).toBeInTheDocument();
  });

  it('las acciones no navegan al detalle de fila', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [prompt], siguiente: null, total_aprox: 1 }), { status: 200 })));
    render(<ToastProvider><MemoryRouter initialEntries={['/prompts']}><Routes>
      <Route path="/prompts" element={<PromptsList yo={admin} />} />
      <Route path="/prompts/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    fireEvent.click(await screen.findByRole('button', { name: 'Eliminar Relevancia general' }));
    expect(screen.getByRole('dialog', { name: 'Eliminar prompt' })).toBeInTheDocument();
    expect(screen.queryByText('Detalle abierto')).not.toBeInTheDocument();
  });

  it('el formulario presenta tipo, red, estado, variables y contenido del mockup', () => {
    render(<ToastProvider><MemoryRouter><PromptForm /></MemoryRouter></ToastProvider>);
    expect(screen.getByRole('combobox', { name: 'Tipo' })).toHaveValue('cluster');
    expect(screen.queryByRole('combobox', { name: 'Red social' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Tipo' }), { target: { value: 'relevancia' } });
    expect(screen.getByRole('combobox', { name: 'Red social' })).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: '{{cuenta}}' }));
    expect(screen.getByRole('textbox', { name: 'Contenido del prompt *' })).toHaveValue('{{cuenta}}');
  });

  it('el detalle consulta versiones reales sin simular contenido', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(
      JSON.stringify(url.includes('/versiones') ? [{ version: 2, contenido: prompt.contenido, creado_en: prompt.actualizado_en, creado_por: 1 }] : prompt),
      { status: 200 },
    ))));
    render(<ToastProvider><MemoryRouter initialEntries={['/prompts/2']}><Routes>
      <Route path="/prompts/:id" element={<PromptDetail yo={admin} />} />
    </Routes></MemoryRouter></ToastProvider>);
    expect(await screen.findByText('Versiones inmutables')).toBeInTheDocument();
    expect(screen.getByText(/v2 ·/)).toBeInTheDocument();
  });
});
