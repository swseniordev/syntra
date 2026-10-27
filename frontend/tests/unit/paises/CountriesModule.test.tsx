import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { CountriesList, CountryForm } from '../../../src/modules/paises/CountriesModule';
import { ToastProvider } from '../../../src/shared/Toast';
import type { Yo } from '../../../src/shared/api';

const admin: Yo = {
  usuario: { id: 1, nombre: 'Admin', email: 'admin@example.test', rol_id: 1 },
  rol: { id: 1, nombre: 'Administrador', ver_todas: true },
  permisos: { paises: ['ver', 'crear', 'editar', 'eliminar'], auditoria: ['ver'] },
  cuentas_visibles: [],
};
const country = { id: 4, nombre: 'Colombia', codigo: 'CO', idioma: 'es-419', estado_id: 1,
  creado_en: '2026-10-21T00:00:00Z', creado_por: 1, actualizado_en: '2026-10-21T00:00:00Z', actualizado_por: 1 };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Países con el patrón de Clientes', () => {
  it('muestra datos de API, badge, fila seleccionable e iconos sin botón Ver', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [country], siguiente: null, total_aprox: 1 }), { status: 200 })));
    render(<ToastProvider><MemoryRouter initialEntries={['/paises']}><Routes>
      <Route path="/paises" element={<CountriesList yo={admin} />} />
      <Route path="/paises/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    const row = await screen.findByRole('row', { name: 'Ver detalle de Colombia' });
    expect(row).toHaveClass('client-row');
    expect(row.querySelector('.badge.ok')).toHaveTextContent('Activo');
    expect(screen.getByText('hl=es-419&gl=CO&ceid=CO:es-419')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ver Colombia' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Editar Colombia' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ver historial de cambios de Colombia' })).toBeInTheDocument();
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(screen.getByText('Detalle abierto')).toBeInTheDocument();
  });

  it('la acción Eliminar abre la misma confirmación sin navegar', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [country], siguiente: null, total_aprox: 1 }), { status: 200 })));
    render(<ToastProvider><MemoryRouter initialEntries={['/paises']}><Routes>
      <Route path="/paises" element={<CountriesList yo={admin} />} />
      <Route path="/paises/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter></ToastProvider>);
    fireEvent.click(await screen.findByRole('button', { name: 'Eliminar Colombia' }));
    expect(screen.getByRole('dialog', { name: 'Eliminar país' })).toBeInTheDocument();
    expect(screen.queryByText('Detalle abierto')).not.toBeInTheDocument();
  });

  it('el formulario nuevo no precarga datos y conserva los campos del mockup', () => {
    render(<ToastProvider><MemoryRouter><CountryForm /></MemoryRouter></ToastProvider>);
    expect(screen.getByRole('textbox', { name: 'Nombre del país *' })).toHaveValue('');
    expect(screen.getByRole('textbox', { name: 'Código ISO (2 letras) *' })).toHaveValue('');
    expect(screen.getByRole('combobox', { name: 'Idioma de los resultados' })).toHaveValue('es-419');
  });
});
