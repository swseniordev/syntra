const previewRequested = new URLSearchParams(window.location.search).get('preview') === '1';
export const previewMode = import.meta.env.DEV && previewRequested;

const clientDateTime = new Intl.DateTimeFormat('es-CO', { day: '2-digit', month: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: 'America/Bogota' });
const clientMonths = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
export function formatClientDateTime(value: string) {
  const parts = Object.fromEntries(clientDateTime.formatToParts(new Date(value)).map(part => [part.type, part.value]));
  return `${parts.day} ${clientMonths[Number(parts.month) - 1]} ${parts.year}, ${parts.hour}:${parts.minute}`;
}
export function toLocalDateTimeInput(value: Date) {
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}
export function defaultMeltwaterWindow() {
  const start = new Date();
  const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
  return { start: toLocalDateTimeInput(start), end: toLocalDateTimeInput(end) };
}