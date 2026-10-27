import { useState } from 'react';
import { Icon } from '../../shared/Icon';
import { EmptyState } from '../../shared/EmptyState';
import { PageHeading } from '../../shared/PageHeading';
const AUDIT_MODULES = ['Cliente', 'Cuenta', 'Usuario', 'Rol', 'Grupo', 'Prompt', 'Cruce', 'Regex', 'País', 'Actor', 'Formato', 'Medición', 'Scraper', 'Fiscalización', 'Registro', 'Configuración de tarjetas', 'Proceso', 'Informe'];
const AUDIT_ACTIONS = ['Creación', 'Actualización', 'Actualización masiva', 'Eliminación lógica', 'Restauración', 'Cambio de estado', 'Ejecución', 'Exportación'];
export function AuditPage() {
  const [query, setQuery] = useState('');
  const [module, setModule] = useState('');
  const [user, setUser] = useState('');
  const [action, setAction] = useState('');
  const [period, setPeriod] = useState('30');
  const [notice, setNotice] = useState('');
  return <>
    <PageHeading title="Log de auditoría" description="Trazabilidad de todo lo que se hace en la plataforma: clientes, cuentas, usuarios, roles, configuración de tarjetas, mediciones y procesos." action={{ label: 'Exportar log', icon: 'download', onClick: () => setNotice('No hay eventos de auditoría para exportar.') }} />
    <div className="dashboard-grid audit-charts"><section className="panel"><header className="panel-heading"><div><h2>Actividad diaria</h2><span className="panel-sub">últimos 30 días</span></div></header><div className="chart-placeholder"><EmptyState title="Sin datos para el periodo" detail="La gráfica aparecerá cuando haya eventos registrados." /></div></section><section className="panel"><header className="panel-heading"><h2>Eventos por módulo</h2></header><EmptyState title="Sin datos para mostrar" detail="Los módulos aparecerán cuando haya eventos registrados." /></section></div>
    <section className="panel entity-list-panel">
      <div className="module-toolbar audit-toolbar" aria-label="Filtros del log de auditoría"><label className="search-field"><Icon name="search" size={16} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Buscar en el log…" aria-label="Buscar en el log" /></label><select aria-label="Módulo" value={module} onChange={event => setModule(event.target.value)}><option value="">Módulo: todos</option>{AUDIT_MODULES.map(item => <option key={item}>{item}</option>)}</select><select aria-label="Usuario" value={user} onChange={event => setUser(event.target.value)}><option value="">Usuario: todos</option></select><select aria-label="Acción" value={action} onChange={event => setAction(event.target.value)}><option value="">Acción: todas</option>{AUDIT_ACTIONS.map(item => <option key={item}>{item}</option>)}</select><select aria-label="Periodo" value={period} onChange={event => setPeriod(event.target.value)}><option value="1">Últimas 24 h</option><option value="7">Últimos 7 días</option><option value="30">Últimos 30 días</option><option value="365">Último año</option></select></div>
      {notice && <p className="control-notice" role="status">{notice}</p>}
      <div className="table-wrap"><table className="data-table audit-table"><thead><tr>{['Fecha', 'Usuario', 'Módulo', 'Acción', 'Entidad', 'Cambios', ''].map((column, index) => <th key={`${column}-${index}`}>{column}</th>)}</tr></thead><tbody><tr><td colSpan={7} className="empty-cell"><EmptyState title={query || module || user || action ? 'Sin eventos para los filtros' : 'Sin eventos de auditoría'} detail="Amplía el rango de fechas o limpia los filtros." /></td></tr></tbody></table></div>
      <div className="table-pager"><span>— eventos</span><div><button type="button" disabled aria-label="Página anterior"><Icon name="chevron" size={16} /></button><span>— / —</span><button type="button" disabled aria-label="Página siguiente"><Icon name="chevron" size={16} /></button></div></div>
    </section>
  </>;
}
