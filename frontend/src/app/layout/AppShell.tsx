import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { CSSProperties, RefObject } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { Icon } from '../../shared/Icon';
import { EmptyState } from '../../shared/EmptyState';
import { navigation, routeLabels } from '../../shared/navigation';
import { api } from '../../shared/api';
import type { Yo } from '../../shared/api';
import { useToast } from '../../shared/Toast';
import { downloadAuditExport, trackedExportIds } from '../../shared/auditExports';
import type { TrackedExport } from '../../shared/auditExports';
import { previewMode } from '../runtime';
import { AppRoutes } from '../router';
import { clientError } from '../../shared/httpErrors';
function GlobalSearch({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);
  if (!open) return null;
  const items = navigation.flatMap(group => group.items).filter(item => item.label.toLowerCase().includes(query.trim().toLowerCase()));
  const to = (path: string) => `${path}${previewMode ? '?preview=1' : ''}`;
  return <div className="command-scrim command-search-scrim" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="command-panel command-search-panel" role="dialog" aria-modal="true" aria-label="Búsqueda global">
      <div className="command-search-field"><Icon name="search" size={18} /><input ref={inputRef} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Busca secciones de Syntra…" aria-label="Buscar secciones" /><button type="button" className="icon-button" onClick={onClose} aria-label="Cerrar búsqueda"><Icon name="close" size={16} /></button></div>
      <div className="command-results" aria-live="polite">{items.length ? items.map(item => <Link key={item.path} to={to(item.path)} onClick={onClose}><Icon name={item.icon} size={17} />{item.label}<Icon name="chevron" size={15} /></Link>) : <EmptyState title="Sin resultados" detail="Prueba con otro término." />}</div>
      <p className="command-hint"><kbd>Esc</kbd> Cerrar · Selecciona una sección</p>
    </section>
  </div>;
}

function HeaderPopover({ id, anchorRef, panelRef, role, labelledBy, children, onKeyDown }: {
  id: string;
  anchorRef: RefObject<HTMLButtonElement | null>;
  panelRef: RefObject<HTMLDivElement | null>;
  role: 'dialog' | 'menu';
  labelledBy: string;
  children: React.ReactNode;
  onKeyDown?: (event: React.KeyboardEvent<HTMLDivElement>) => void;
}) {
  const [position, setPosition] = useState<CSSProperties>({ visibility: 'hidden' });
  useLayoutEffect(() => {
    const updatePosition = () => {
      const anchor = anchorRef.current;
      const panel = panelRef.current;
      if (!anchor || !panel) return;
      const anchorRect = anchor.getBoundingClientRect();
      const panelRect = panel.getBoundingClientRect();
      const left = Math.min(Math.max(12, anchorRect.right - panelRect.width), window.innerWidth - panelRect.width - 12);
      const below = anchorRect.bottom + 8;
      const top = below + panelRect.height <= window.innerHeight - 12 ? below : Math.max(12, anchorRect.top - panelRect.height - 8);
      setPosition({ top, left, visibility: 'visible' });
    };
    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);
    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [anchorRef, panelRef]);
  useLayoutEffect(() => {
    if (role === 'menu' && position.visibility === 'visible') panelRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
  }, [panelRef, position.visibility, role]);
  return <div id={id} ref={panelRef} className="header-popover" role={role} aria-labelledby={labelledBy} style={position} onKeyDown={onKeyDown}>{children}</div>;
}

function PreviewBanner() {
  return <div className="preview-banner"><Icon name="info" size={16} /> Vista previa de desarrollo · no autenticada <span>Este acceso solo existe durante el servidor de desarrollo.</span></div>;
}

export function AppShell({ yo, onLogout }: { yo?: Yo | null; onLogout?: () => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const toast = useToast();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [searchOpen, setSearchOpen] = useState(false);
  const [activeHeaderPanel, setActiveHeaderPanel] = useState<'notifications' | 'user' | null>(null);
  const [auditExports, setAuditExports] = useState<TrackedExport[]>([]);
  const [notifications, setNotifications] = useState<Array<{ id: number; titulo: string; cuerpo: string | null;
    enlace: string | null; tipo: 'ok' | 'warn' | 'err' | 'info'; leida: boolean; creado_en: string }>>([]);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [theme, setTheme] = useState<'light' | 'dark'>(() => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
  const searchTriggerRef = useRef<HTMLButtonElement>(null);
  const notificationTriggerRef = useRef<HTMLButtonElement>(null);
  const userTriggerRef = useRef<HTMLButtonElement>(null);
  const headerPanelRef = useRef<HTMLDivElement>(null);
  const canTrackExports = Boolean(yo?.permisos.auditoria?.includes('ver') && yo?.permisos.procesos?.includes('ver'));
  useEffect(() => {
    if (!yo || !canTrackExports) { setAuditExports([]); return; }
    let live = true;
    const userId = yo.usuario.id;
    async function refresh() {
      const rows = await Promise.allSettled(trackedExportIds(userId).map(async id => {
        const process = await (await api(`/procesos/${id}`)).json() as TrackedExport;
        return { id, estado: process.estado };
      }));
      if (live) setAuditExports(rows.filter((row): row is PromiseFulfilledResult<TrackedExport> => row.status === 'fulfilled').map(row => row.value));
    }
    void refresh();
    window.addEventListener('syntra:audit-export', refresh);
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => { live = false; window.clearInterval(timer); window.removeEventListener('syntra:audit-export', refresh); };
  }, [yo?.usuario.id, canTrackExports]);
  const readyExports = auditExports.filter(item => item.estado === 'completado').length;
  useEffect(() => {
    if (!yo || previewMode) { setNotifications([]); setUnreadNotifications(0); return; }
    let live = true;
    async function refresh() {
      try {
        const result = await (await api('/notificaciones?limite=8')).json() as {
          no_leidas: number; items: typeof notifications };
        if (live && Array.isArray(result.items)) {
          setNotifications(result.items);
          setUnreadNotifications(Number.isSafeInteger(result.no_leidas) ? result.no_leidas : 0);
        }
      } catch { /* La campana conserva el último estado; la próxima consulta reintenta. */ }
    }
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 5000);
    return () => { live = false; window.clearInterval(timer); };
  }, [yo?.usuario.id]);
  async function openNotification(item: typeof notifications[number]) {
    try {
      if (!item.leida) await api(`/notificaciones/${item.id}/leer`, { method: 'POST' });
      setNotifications(current => current.map(row => row.id === item.id ? { ...row, leida: true } : row));
      setUnreadNotifications(current => Math.max(0, current - (item.leida ? 0 : 1)));
      setActiveHeaderPanel(null);
      if (item.enlace && /^\/mediciones\/[1-9]\d*\?tab=cargas$/.test(item.enlace)) navigate(item.enlace);
    } catch { toast('No se pudo abrir la notificación', 'Inténtalo de nuevo.', 'err'); }
  }
  async function markAllNotifications() {
    try {
      await api('/notificaciones/leer-todas', { method: 'POST' });
      setNotifications(current => current.map(row => ({ ...row, leida: true })));
      setUnreadNotifications(0);
    } catch { toast('No se pudieron marcar las notificaciones', 'Inténtalo de nuevo.', 'err'); }
  }
  const bellCount = unreadNotifications + readyExports;
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  useEffect(() => {
    function handleGlobalKeys(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (searchOpen) {
          setSearchOpen(false);
          searchTriggerRef.current?.focus();
        } else if (activeHeaderPanel) {
          setActiveHeaderPanel(null);
          (activeHeaderPanel === 'notifications' ? notificationTriggerRef : userTriggerRef).current?.focus();
        }
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setActiveHeaderPanel(null);
        setSearchOpen(open => !open);
      }
    }
    window.addEventListener('keydown', handleGlobalKeys);
    return () => window.removeEventListener('keydown', handleGlobalKeys);
  }, [activeHeaderPanel, searchOpen]);
  useEffect(() => {
    if (!activeHeaderPanel) return;
    const triggerRef = activeHeaderPanel === 'notifications' ? notificationTriggerRef : userTriggerRef;
    function handleOutsidePointer(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node) || headerPanelRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      setActiveHeaderPanel(null);
    }
    document.addEventListener('pointerdown', handleOutsidePointer, true);
    return () => document.removeEventListener('pointerdown', handleOutsidePointer, true);
  }, [activeHeaderPanel]);
  function openSearch() {
    setActiveHeaderPanel(null);
    setSearchOpen(true);
  }
  function toggleHeaderPanel(panel: 'notifications' | 'user') {
    setSearchOpen(false);
    setActiveHeaderPanel(current => current === panel ? null : panel);
  }
  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    setTheme(next);
    setActiveHeaderPanel(null);
  }
  function handleUserMenuKeys(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const items = Array.from(headerPanelRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? []);
    if (!items.length) return;
    event.preventDefault();
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    const nextIndex = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : event.key === 'ArrowDown' ? (index + 1) % items.length : index <= 0 ? items.length - 1 : index - 1;
    items[nextIndex]?.focus();
  }
  const createTitles: Record<string, string> = { '/clientes/nuevo': 'Nuevo cliente', '/cuentas/nueva': 'Nueva cuenta', '/prompts/nuevo': 'Nuevo prompt', '/regex/nueva': 'Nueva regex', '/paises/nuevo': 'Nuevo país', '/usuarios/nuevo': 'Nuevo usuario', '/roles/nuevo': 'Nuevo rol', '/grupos/nuevo': 'Nuevo grupo' };
  const current = location.pathname === '/' ? 'Inicio' : location.pathname === '/mediciones/nueva' ? 'Nueva medición' : location.pathname.match(/^\/clientes\/\d+\/editar$/) ? 'Editar cliente' : location.pathname.match(/^\/clientes\/\d+$/) ? 'Detalle de cliente' : location.pathname.match(/^\/roles\/\d+\/editar$/) ? 'Editar rol' : location.pathname.match(/^\/roles\/\d+$/) ? 'Detalle de rol' : location.pathname.match(/^\/paises\/\d+\/editar$/) ? 'Editar país' : location.pathname.match(/^\/paises\/\d+$/) ? 'Detalle de país' : location.pathname.match(/^\/prompts\/\d+\/editar$/) ? 'Editar prompt' : location.pathname.match(/^\/prompts\/\d+$/) ? 'Detalle de prompt' : location.pathname.match(/^\/regex\/\d+\/editar$/) ? 'Editar regex' : location.pathname.match(/^\/regex\/\d+$/) ? 'Detalle de regex' : location.pathname.match(/^\/cuentas\/\d+\/editar$/) ? 'Editar cuenta' : location.pathname.match(/^\/cuentas\/\d+$/) ? 'Detalle de cuenta' : location.pathname.match(/^\/grupos\/\d+\/editar$/) ? 'Editar grupo' : location.pathname.match(/^\/grupos\/\d+$/) ? 'Detalle de grupo' : location.pathname.match(/^\/usuarios\/\d+\/editar$/) ? 'Editar usuario' : location.pathname.match(/^\/usuarios\/\d+$/) ? 'Detalle de usuario' : location.pathname.match(/^\/auditoria\/\d+$/) ? 'Detalle del evento' : createTitles[location.pathname] ?? routeLabels[location.pathname] ?? (location.pathname.startsWith('/mediciones/') ? 'Detalle de medición' : 'No encontrado');
  return <div className={`app-shell${sidebarOpen ? '' : ' sidebar-collapsed'}`}>
    {previewMode && <PreviewBanner />}
    <aside className="sidebar" aria-label="Navegación principal">
      <Link className="sidebar-brand" to={`/${previewMode ? '?preview=1' : ''}`}><img src="/brand/symbol.png" alt="" /><img src="/brand/word-light.png" alt="Syntra" /></Link>
      <nav className="side-nav">{navigation.map(({ group, items }) => <section className="nav-group" key={group}><h2>{group}</h2>{items.map(item => <NavLink key={item.path} to={`${item.path}${previewMode ? '?preview=1' : ''}`} end={item.path === '/'} onClick={() => { if (window.innerWidth <= 860) setSidebarOpen(true); }} className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}><Icon name={item.icon} /><span>{item.label}</span></NavLink>)}</section>)}</nav>
      <div className="sidebar-footer"><span className="avatar">S</span><span><strong>{yo?.usuario.nombre || 'Syntra'}</strong><small>{yo?.rol.nombre || 'Vista sin sesión'}</small></span></div>
    </aside>
    <div className="main-column">
      <header className="topbar"><button className="icon-button menu-toggle" aria-label="Mostrar u ocultar menú" onClick={() => setSidebarOpen(value => !value)}><Icon name="menu" /></button><nav className="breadcrumbs" aria-label="Ruta"><Link to={`/${previewMode ? '?preview=1' : ''}`}>Syntra</Link><Icon name="chevron" size={14} /><strong>{current}</strong></nav><div className="top-actions"><button ref={searchTriggerRef} className="search-pill" type="button" aria-label="Buscar en Syntra" aria-keyshortcuts="Control+K Meta+K" onClick={openSearch}><Icon name="search" /><span>Buscar en Syntra…</span><kbd>Ctrl K</kbd></button><button className="icon-button" type="button" aria-label={theme === 'dark' ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'} onClick={toggleTheme}><Icon name={theme === 'dark' ? 'sun' : 'moon'} /></button><button ref={notificationTriggerRef} className="icon-button notification-trigger" type="button" aria-label={unreadNotifications ? `Notificaciones: ${unreadNotifications} sin leer · ${readyExports} exportaciones completadas` : readyExports ? `Notificaciones: ${readyExports} exportaciones completadas` : 'Notificaciones'} aria-haspopup="dialog" aria-expanded={activeHeaderPanel === 'notifications'} aria-controls={activeHeaderPanel === 'notifications' ? 'notifications-popover' : undefined} onClick={() => toggleHeaderPanel('notifications')}><Icon name="bell" />{bellCount > 0 && <span className="notification-count" aria-hidden="true">{bellCount > 99 ? "99+" : bellCount}</span>}</button><button ref={userTriggerRef} className="user-chip" type="button" aria-label="Menú de usuario" aria-haspopup="menu" aria-expanded={activeHeaderPanel === 'user'} aria-controls={activeHeaderPanel === 'user' ? 'user-menu-popover' : undefined} onClick={() => toggleHeaderPanel('user')}><span className="avatar small">S</span><span className="user-chip-label"><strong>{yo?.usuario.nombre || 'Syntra'}</strong><small>{yo?.rol.nombre || 'Vista previa'}</small></span><Icon name="chevron" size={14} /></button></div></header>
      {activeHeaderPanel === 'notifications' && <HeaderPopover id="notifications-popover" anchorRef={notificationTriggerRef} panelRef={headerPanelRef} role="dialog" labelledBy="notifications-title">
        <div className="header-popover-heading"><h2 id="notifications-title">Notificaciones</h2>{unreadNotifications > 0 && <button className="button small" type="button" onClick={() => void markAllNotifications()}>Marcar leídas</button>}</div>
        {notifications.length > 0 && <div className="audit-notifications">{notifications.map(item => <button className={`audit-notification app-notification${item.leida ? '' : ' unread'}`} type="button" key={item.id} onClick={() => void openNotification(item)}><span className={`app-notification-icon ${item.tipo}`}><Icon name={item.tipo === 'err' ? 'alert' : item.tipo === 'warn' ? 'info' : 'check'} size={14} /></span><span><strong>{item.titulo}</strong><small>{item.cuerpo}</small></span></button>)}</div>}
        {auditExports.length > 0 && <div className="audit-notifications">{auditExports.slice().reverse().map(item => <div className="audit-notification" key={item.id}><div><strong>Exportación de Auditoría #{item.id}</strong><small>{item.estado === 'completado' ? 'Completada' : item.estado === 'error' ? 'Fallida' : item.estado === 'en_cola' ? 'En cola' : 'En proceso'}</small></div>{item.estado === 'completado' && <button className="button small" type="button" aria-label={`Descargar exportación de Auditoría ${item.id}`} onClick={() => void downloadAuditExport(item.id).catch(error => toast('No se pudo descargar', clientError(error, 'El archivo no está disponible.'), 'err'))}><Icon name="download" size={14} />Descargar</button>}</div>)}</div>}
        {!notifications.length && !auditExports.length && <div className="notification-empty" role="status">Sin notificaciones</div>}
      </HeaderPopover>}
      {activeHeaderPanel === 'user' && <HeaderPopover id="user-menu-popover" anchorRef={userTriggerRef} panelRef={headerPanelRef} role="menu" labelledBy="user-menu-title" onKeyDown={handleUserMenuKeys}><div className="user-menu-profile"><span className="avatar">S</span><div><strong id="user-menu-title">{yo?.usuario.nombre || 'Syntra'}</strong><small>{yo?.rol.nombre || 'Vista previa · sin sesión'}</small></div></div><button className="user-menu-action" type="button" role="menuitem" onClick={toggleTheme}><Icon name={theme === 'dark' ? 'sun' : 'moon'} size={16} />Cambiar tema claro / oscuro</button>{onLogout && <button className="user-menu-action" type="button" role="menuitem" onClick={onLogout}>Cerrar sesión</button>}</HeaderPopover>}
      <main id="page" className="page-content" tabIndex={-1}>
        <AppRoutes yo={yo || null} onOpenSearch={openSearch} />
      </main>
    </div>
    <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
  </div>;
}
