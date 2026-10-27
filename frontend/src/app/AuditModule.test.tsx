import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AuditList } from './AuditModule';
import { ToastProvider } from '../shared/Toast';
import { setToken } from '../shared/api';
import type { Yo } from '../shared/api';

const event = { id: 15, fecha: '2026-10-21T14:00:00Z', usuario_id: 1, modulo: 'clientes', accion: 'editar',
  entidad_tipo: 'Cliente', entidad_id: '8', entidad_nombre: 'Cliente real',
  antes: { nombre: 'Antes' }, despues: { nombre: 'Después' }, detalle: null, ip: null, request_id: null };

afterEach(() => { cleanup(); setToken(null); vi.unstubAllGlobals(); });

describe('Auditoría de lectura', () => {
  it('muestra evento real paginado, badge y abre detalle con fecha e id', async () => {
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
      url.startsWith('/api/v1/usuarios') ? { items: [{ id: 1, nombre: 'Admin' }], siguiente: null }
        : url.startsWith('/api/v1/auditoria/resumen') ? { por_dia: [{ dia: '2026-10-21', total: 1 }], por_modulo: [{ modulo: 'clientes', total: 1 }] }
          : { items: [event], siguiente: null },
    ), { status: 200 }))));
    render(<MemoryRouter initialEntries={['/auditoria']}><Routes>
      <Route path="/auditoria" element={<AuditList yo={null} />} />
      <Route path="/auditoria/:id" element={<p>Detalle abierto</p>} />
    </Routes></MemoryRouter>);
    const row = await screen.findByRole('row', { name: 'Ver evento 15 de Cliente real' });
    expect(row).toHaveClass('client-row');
    expect(row.querySelector('.badge.info')).toHaveTextContent('Actualización');
    expect(row).toHaveTextContent('Admin');
    expect(screen.getByRole('button', { name: 'Exportar log' })).toBeDisabled();
    expect(await screen.findByRole('img', { name: 'Eventos de auditoría por día durante los últimos 30 días' })).toBeInTheDocument();
    expect(screen.getByTitle('clientes: 1 eventos')).toBeInTheDocument();
    fireEvent.keyDown(row, { key: 'Enter' });
    expect(screen.getByText('Detalle abierto')).toBeInTheDocument();
  });

  it('encola la exportación con filtros y solo anuncia éxito tras el 202', async () => {
    const yo = { permisos: { auditoria: ['ver'], procesos: ['ver'] } } as unknown as Yo;
    // Simula el navegador de QA por HTTP: crypto.randomUUID no existe, pero getRandomValues sí.
    vi.stubGlobal('crypto', { randomUUID: undefined, getRandomValues: (bytes: Uint8Array) => {
      bytes.set(new Uint8Array(16).fill(1));
      return bytes;
    } });
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url === '/api/v1/auditoria/exportar') {
        expect(init?.method).toBe('POST');
        expect(JSON.parse(String(init?.body)).desde).toBeTruthy();
        const idempotencyKey = new Headers(init?.headers).get('Idempotency-Key') || '';
        expect(idempotencyKey).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
        return Promise.resolve(new Response(JSON.stringify({ proceso_id: 51, tipo: 'exportacion', estado: 'en_cola' }), { status: 202 }));
      }
      return Promise.resolve(new Response(JSON.stringify(url.startsWith('/api/v1/auditoria/resumen')
        ? { por_dia: [], por_modulo: [] } : { items: [], siguiente: null }), { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<ToastProvider><MemoryRouter><AuditList yo={yo} /></MemoryRouter></ToastProvider>);
    fireEvent.click(screen.getByRole('button', { name: 'Exportar log' }));
    await waitFor(() => expect(screen.getByText('Exportación #51')).toBeInTheDocument());
    expect(screen.getByText('Exportación solicitada')).toBeInTheDocument();
  });

  it('envía primero la exportación y muestra el vencimiento si falla la renovación', async () => {
    const yo = { permisos: { auditoria: ['ver'], procesos: ['ver'] } } as unknown as Yo;
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url === '/api/v1/auditoria/exportar') return Promise.resolve(new Response(
        JSON.stringify({ detail: 'Sesión no válida' }), { status: 401 },
      ));
      if (url === '/api/v1/auth/refresh') return Promise.resolve(new Response(
        JSON.stringify({ detail: 'Sesión no válida' }), { status: 401 },
      ));
      return Promise.resolve(new Response(JSON.stringify(url.startsWith('/api/v1/auditoria/resumen')
        ? { por_dia: [], por_modulo: [] } : { items: [], siguiente: null }), { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<ToastProvider><MemoryRouter><AuditList yo={yo} /></MemoryRouter></ToastProvider>);

    fireEvent.click(screen.getByRole('button', { name: 'Exportar log' }));

    await waitFor(() => expect(screen.getByText('La sesión venció. Ingresa de nuevo.')).toBeInTheDocument());
    const authFlow = fetchMock.mock.calls.map(([url]) => url)
      .filter(url => url === '/api/v1/auditoria/exportar' || url === '/api/v1/auth/refresh');
    expect(authFlow).toEqual(['/api/v1/auditoria/exportar', '/api/v1/auth/refresh']);
    expect(screen.queryByText('Exportación solicitada')).not.toBeInTheDocument();
  });

  it('navega con cursor estable y conserva filtros al avanzar y retroceder', async () => {
    const older = { ...event, id: 14, fecha: '2026-10-21T13:00:00Z', entidad_nombre: 'Cliente anterior' };
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.startsWith('/api/v1/auditoria/resumen')) return Promise.resolve(new Response(JSON.stringify({ por_dia: [], por_modulo: [] })));
      if (url.startsWith('/api/v1/usuarios')) return Promise.resolve(new Response(JSON.stringify({ items: [], siguiente: null })));
      const params = new URL(url, 'https://local.test').searchParams;
      expect(params.get('modulo')).toBe('clientes');
      return Promise.resolve(new Response(JSON.stringify(params.get('cursor') === 'cursor-1'
        ? { items: [older], siguiente: null } : { items: [event], siguiente: 'cursor-1' })));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MemoryRouter><AuditList yo={null} /></MemoryRouter>);
    fireEvent.change(screen.getByRole('combobox', { name: 'Módulo' }), { target: { value: 'clientes' } });
    expect(await screen.findByRole('row', { name: 'Ver evento 15 de Cliente real' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Página siguiente' }));
    expect(await screen.findByRole('row', { name: 'Ver evento 14 de Cliente anterior' })).toBeInTheDocument();
    expect(screen.queryByRole('row', { name: 'Ver evento 15 de Cliente real' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Página siguiente' })).toBeDisabled();
    const calls = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Página anterior' }));
    expect(screen.getByRole('row', { name: 'Ver evento 15 de Cliente real' })).toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(calls);
    expect(screen.getByText('Sin actividad para el periodo')).toBeInTheDocument();
  });
});
