import { Link } from 'react-router-dom';
import { Icon } from '../../shared/Icon';
import { EmptyState } from '../../shared/EmptyState';
import { previewMode } from '../../app/runtime';
export function HomePage({ onOpenSearch }: { onOpenSearch: () => void }) {
  const route = (path: string) => `${path}${previewMode ? '?preview=1' : ''}`;
  const metrics = [
    { title: 'Registros cargados', icon: 'upload', detail: 'Nuevos en 24 h · duplicados omitidos' },
    { title: 'Por fiscalizar', icon: 'alert', detail: 'Descartados por relevancia' },
    { title: 'Incorporados', icon: 'check', detail: 'Metadata actualizada · transcritos' },
    { title: 'En tableros', icon: 'grid', detail: 'Pendientes de análisis · publicación' },
    { title: 'SLA < 15 min', icon: 'clock', detail: 'Ejecuciones · últimas 24 h' },
  ];
  return <>
    <section className="welcome-band"><div className="welcome-copy"><p className="eyebrow">SYNTRA · ESCUCHA SOCIAL</p><h1>Inicio</h1><p>Resumen de actividad y seguimiento de mediciones.</p></div><div className="welcome-actions"><Link className="button primary" to={route('/mediciones/nueva')}><Icon name="plus" size={16} /> Nueva medición</Link><Link className="button" to={route('/mediciones')}><Icon name="pulse" size={16} /> Mediciones</Link><Link className="button" to={route('/procesos')}><Icon name="cycle" size={16} /> Procesos</Link><button className="button" type="button" onClick={onOpenSearch}><Icon name="search" size={16} /> Buscar <kbd>Ctrl K</kbd></button></div></section>
    <div className="metric-grid">{metrics.map(({ title, icon, detail }) => <section className="panel metric-card" key={title}><span>{title}</span><strong>—</strong><small>{detail}</small><i><Icon name={icon} size={18} /></i></section>)}</div>
    <div className="dashboard-grid"><section className="panel"><header className="panel-heading"><h2>Conversación publicada · últimas 3 semanas</h2><span className="panel-sub">neto —</span><div className="chart-legend"><span><i className="legend-dot" style={{ background: 'var(--syntra-blue)' }} /> Positivo</span><span><i className="legend-dot" style={{ background: '#A6B1C4' }} /> Neutral</span><span><i className="legend-dot" style={{ background: '#E5484D' }} /> Negativo</span></div></header><div className="chart-placeholder"><EmptyState title="Sin datos para el periodo" detail="La gráfica aparecerá cuando haya registros publicados." /></div></section><section className="panel"><header className="panel-heading"><h2>Cargado por fuente</h2><span className="panel-sub">quién incorporó</span></header><EmptyState title="Sin datos para mostrar" detail="Las fuentes aparecerán cuando haya cargas registradas." /></section></div>
    <div className="dashboard-grid"><section className="panel"><header className="panel-heading"><h2>Procesos recientes</h2><span className="panel-sub">en vivo</span><Link className="button small" to={route('/procesos')}>Ver monitor</Link></header><EmptyState title="Sin procesos recientes" detail="Las cargas, fiscalizaciones y procesamientos aparecerán aquí." /></section><div className="dashboard-stack"><section className="panel"><header className="panel-heading"><h2>Pendientes por medición</h2></header><EmptyState title="Sin información disponible" detail="Los pendientes aparecerán cuando existan mediciones y procesos." /></section><section className="panel"><header className="panel-heading"><h2>Actividad reciente</h2><Link className="button small" to={route('/auditoria')}>Auditoría</Link></header><EmptyState title="Sin actividad reciente" detail="Los cambios realizados en la plataforma aparecerán aquí." /></section></div></div>
  </>;
}
