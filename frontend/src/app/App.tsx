import { useEffect, useState } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { api, hasToken, logout as logoutApi, refreshAccess, watchToken } from '../shared/api';
import type { Yo } from '../shared/api';
import { ToastProvider } from '../shared/Toast';
import { previewMode } from './runtime';
import { AccessPage, postLoginPath } from '../modules/auth/AccessPage';
import { AppShell } from './layout/AppShell';
import { CREATION_ROUTES, CREATION_SPECS } from '../modules/general/GenericEntityModule';
import { routeLabels } from '../shared/navigation';
function DocumentTitle({ authenticated = false }: { authenticated?: boolean }) {
  const location = useLocation();
  useEffect(() => {
    if (!previewMode && !authenticated && location.pathname !== '/acceso') {
      document.title = 'Acceso — Syntra';
      return;
    }
    const path = location.pathname;
    const creationPath = Object.entries(CREATION_ROUTES).find(([, route]) => route === path)?.[0];
    const title = path === '/acceso' ? 'Acceso'
      : path.match(/^\/clientes\/\d+\/editar$/) ? 'Editar cliente'
        : path.match(/^\/clientes\/\d+$/) ? 'Detalle de cliente'
      : path.match(/^\/roles\/\d+\/editar$/) ? 'Editar rol'
        : path.match(/^\/roles\/\d+$/) ? 'Detalle de rol'
      : path.match(/^\/paises\/\d+\/editar$/) ? 'Editar país'
        : path.match(/^\/paises\/\d+$/) ? 'Detalle de país'
      : path.match(/^\/prompts\/\d+\/editar$/) ? 'Editar prompt'
        : path.match(/^\/prompts\/\d+$/) ? 'Detalle de prompt'
      : path.match(/^\/regex\/\d+\/editar$/) ? 'Editar regex'
        : path.match(/^\/regex\/\d+$/) ? 'Detalle de regex'
      : path.match(/^\/cuentas\/\d+\/editar$/) ? 'Editar cuenta'
        : path.match(/^\/cuentas\/\d+$/) ? 'Detalle de cuenta'
      : path.match(/^\/grupos\/\d+\/editar$/) ? 'Editar grupo'
        : path.match(/^\/grupos\/\d+$/) ? 'Detalle de grupo'
      : path.match(/^\/usuarios\/\d+\/editar$/) ? 'Editar usuario'
        : path.match(/^\/usuarios\/\d+$/) ? 'Detalle de usuario'
      : path.match(/^\/auditoria\/\d+$/) ? 'Detalle del evento'
      : path === '/mediciones/nueva' ? 'Nueva medición'
        : path.startsWith('/mediciones/') ? 'Detalle de medición'
          : creationPath ? CREATION_SPECS[creationPath]?.title ?? 'Formulario'
            : routeLabels[path] ?? 'No encontrado';
    document.title = `${title} — Syntra`;
  }, [location.pathname, authenticated]);
  return null;
}
export default function App() {
  const location = useLocation();
  const [authenticated, setAuthenticated] = useState(hasToken());
  const [checkingSession, setCheckingSession] = useState(!previewMode && !hasToken() && location.pathname !== '/acceso');
  const [yo, setYo] = useState<Yo | null>(null);
  const navigate = useNavigate();
  useEffect(() => watchToken(token => setAuthenticated(Boolean(token))), []);
  useEffect(() => {
    if (previewMode || hasToken()) return;
    let live = true;
    void refreshAccess().finally(() => { if (live) setCheckingSession(false); });
    return () => { live = false; };
  }, []);
  useEffect(() => {
    if (!authenticated || previewMode) { setYo(null); return; }
    api('/auth/yo').then(response => response.json()).then(setYo).catch(() => setYo(null));
  }, [authenticated]);
  if (previewMode) return <ToastProvider><DocumentTitle /><AppShell /></ToastProvider>;
  if (checkingSession) return <main className="session-check" role="status">Comprobando sesión…</main>;
  if (authenticated && location.pathname === '/acceso') return <Navigate to={postLoginPath(location.state)} replace />;
  if (authenticated) return <ToastProvider><DocumentTitle authenticated /><AppShell yo={yo} onLogout={() => { void logoutApi().finally(() => navigate('/acceso')); }} /></ToastProvider>;
  return <ToastProvider><DocumentTitle /><Routes><Route path="/acceso" element={<AccessPage />} /><Route path="*" element={<Navigate to="/acceso" replace state={{ from: `${location.pathname}${location.search}${location.hash}` }} />} /></Routes></ToastProvider>;
}
