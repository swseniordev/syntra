import { Icon } from './Icon';

export function EmptyState({ title = 'Sin información disponible', detail = 'El contenido aparecerá cuando haya información disponible.', icon = 'info' }: {
  title?: string; detail?: string; icon?: string;
}) {
  return <div className="empty-state"><span className="empty-icon"><Icon name={icon} size={25} /></span><h3>{title}</h3><p>{detail}</p></div>;
}
