import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { AuditMetadata } from './AuditMetadata';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('presenta fechas e identificadores reales sin inventar una actualización', () => {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  render(<AuditMetadata record={{ creado_en: '2026-10-21T14:00:00Z', creado_por: 8,
    actualizado_en: '2026-10-21T14:00:00Z', actualizado_por: 8 }} />);
  expect(screen.getByText('Usuario #8')).toBeInTheDocument();
  expect(screen.getByText('Usuario #8').parentElement).toHaveTextContent('Sin actualización registrada');
  expect(fetchMock).not.toHaveBeenCalled();
});
