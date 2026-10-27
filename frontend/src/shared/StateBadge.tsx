/** Estados oficiales (-1, 0, 1) con los colores del mockup v0.4. */
export function StateBadge({ state }: { state: number }) {
  const variant = state === 1 ? 'ok' : state === 0 ? 'warn' : 'err';
  const label = state === 1 ? 'Activo' : state === 0 ? 'Inactivo' : 'Eliminado';
  return <span className={`badge ${variant}`}><span className="d" aria-hidden="true" />{label}</span>;
}
