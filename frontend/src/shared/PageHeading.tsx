import { Link } from 'react-router-dom';
import { Icon } from './Icon';

export type HeadingAction = { label: string; path?: string; icon?: string; onClick?: () => void; disabled?: boolean; className?: string };

export function PageHeading({ title, description, action, preview = false }: {
  title: string; description?: string; action?: string | HeadingAction; preview?: boolean;
}) {
  const content = typeof action === 'string' ? action : <>{action?.icon && <Icon name={action.icon} size={16} />}{action?.label}</>;
  const className = `button primary heading-action${typeof action === 'object' && action?.className ? ` ${action.className}` : ''}`;
  return <div className="page-heading"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{typeof action === 'string' ? <button className={className} disabled>{action}</button> : action && (action.path ? <Link className={className} to={`${action.path}${preview ? '?preview=1' : ''}`}>{content}</Link> : <button className={className} type="button" disabled={action.disabled} onClick={action.onClick}>{content}</button>)}</div>;
}