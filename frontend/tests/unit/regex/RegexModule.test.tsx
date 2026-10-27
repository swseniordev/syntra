import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { RegexList, RegexForm } from '../../../src/modules/regex/RegexModule';
import { ToastProvider } from '../../../src/shared/Toast';
import type { Yo } from '../../../src/shared/api';

const admin: Yo = {
  usuario: { id: 1, nombre: 'Admin', email: 'admin@example.test', rol_id: 1 },
  rol: { id: 1, nombre: 'Administrador', ver_todas: true },
  permisos: { regex: ['ver', 'crear', 'editar', 'eliminar'], auditoria: ['ver'] },
  cuentas_visibles: [],
};
const expression = { id: 7, nombre: 'Crisis del agua', condicion: 'agua', flags: 'i',
  texto_prueba: 'Agua potable', descripcion: null, version: 2, estado_id: 1,
  creado_en: '2026-10-21T00:00:00Z', creado_por: 1, actualizado_en: '2026-10-21T00:00:00Z', actualizado_por: 1 };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Regex con el patrón de Clientes', () => {
  it('muestra badge, iconos y fila seleccionable sin botón Ver', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [expression], siguiente: null, total_aprox: 1 }), { status: 200 })));
    render(<ToastProvider><MemoryRouter initialEntries={['/regex']}><Routes>
      <Route path="/regex" element={<RegexList yo={admin} />} />
      <Route path="/regex/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    const row = await screen.findByRole('row', { name: 'Ver detalle de Crisis del agua' });
    expect(row).toHaveClass('client-row');
    expect(row.querySelector('.badge.ok')).toHaveTextContent('Activo');
    expect(row).toHaveTextContent('v2');
    expect(screen.queryByRole('button', { name: 'Ver Crisis del agua' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ver historial de cambios de Crisis del agua' })).toBeInTheDocument();
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(screen.getByText('Detalle abierto')).toBeInTheDocument();
  });

  it('la acción eliminar confirma sin navegar al detalle', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [expression], siguiente: null, total_aprox: 1 }), { status: 200 })));
    render(<ToastProvider><MemoryRouter initialEntries={['/regex']}><Routes>
      <Route path="/regex" element={<RegexList yo={admin} />} />
      <Route path="/regex/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    fireEvent.click(await screen.findByRole('button', { name: 'Eliminar Crisis del agua' }));
    expect(screen.getByRole('dialog', { name: 'Eliminar regex' })).toBeInTheDocument();
    expect(screen.queryByText('Detalle abierto')).not.toBeInTheDocument();
  });

  it('prueba la condición en la API RE2 y presenta coincidencias', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      valida: true, cumple: true, coincidencias: [{ inicio: 0, fin: 4, texto: 'Agua' }], error: null,
    }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    render(<ToastProvider><MemoryRouter><RegexForm /></MemoryRouter></ToastProvider>);
    fireEvent.change(screen.getByRole('textbox', { name: 'Condición (expresión regular) *' }), { target: { value: 'agua' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Texto de prueba *' }), { target: { value: 'Agua potable' } });
    expect(await screen.findByText('1 coincidencia(s) en el texto de prueba.')).toBeInTheDocument();
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/v1/regex/probar', expect.objectContaining({ method: 'POST' })));
    expect(screen.getByText('Agua', { selector: 'mark' })).toBeInTheDocument();
  });

  it('informa expresión inválida o sin coincidencia y no permite guardarla', async () => {
    const fetcher = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      const body = JSON.parse(String(init.body));
      return Promise.resolve(new Response(JSON.stringify(body.condicion === '['
        ? { valida: false, cumple: false, coincidencias: [], error: 'La condición no es válida en RE2' }
        : { valida: true, cumple: false, coincidencias: [], error: null }), { status: 200 }));
    });
    vi.stubGlobal('fetch', fetcher);
    render(<ToastProvider><MemoryRouter><RegexForm /></MemoryRouter></ToastProvider>);
    const condition = screen.getByRole('textbox', { name: 'Condición (expresión regular) *' });
    fireEvent.change(condition, { target: { value: '[' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Texto de prueba *' }), { target: { value: 'agua' } });
    expect(await screen.findByText('La condición no es válida en RE2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled();
    fireEvent.change(condition, { target: { value: 'tierra' } });
    expect(screen.queryByText('La condición no es válida en RE2')).not.toBeInTheDocument();
    expect(await screen.findByText('La expresión no coincide con el texto de prueba.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Guardar' })).toBeDisabled();
  });
});
