import { api } from './api';

export type TrackedExport = { id: number; estado: string };
const key = (userId: number) => `syntra.audit.exports.${userId}`;

/** Genera una clave UUID v4 también en HTTP; randomUUID solo está disponible en contextos seguros. */
export function createAuditExportIdempotencyKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function trackedExportIds(userId: number): number[] {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(key(userId)) || '[]');
    return Array.isArray(value) ? value.filter((id): id is number => Number.isSafeInteger(id) && id > 0).slice(-20) : [];
  } catch { return []; }
}

export function rememberAuditExport(userId: number, processId: number) {
  if (!Number.isSafeInteger(processId) || processId < 1) return;
  try {
    sessionStorage.setItem(key(userId), JSON.stringify([...new Set([...trackedExportIds(userId), processId])].slice(-20)));
    window.dispatchEvent(new Event('syntra:audit-export'));
  } catch { /* El seguimiento de la pestaña es opcional; el proceso sigue en el servidor. */ }
}

export async function downloadAuditExport(processId: number) {
  const link = await (await api(`/auditoria/exportaciones/${processId}/descarga`)).json() as { url: string };
  if (link.url !== `/api/v1/auditoria/exportaciones/${processId}/archivo`) throw new Error('Enlace de descarga inválido');
  const response = await api(link.url.slice('/api/v1'.length));
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = `auditoria-${processId}.xlsx`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
}
