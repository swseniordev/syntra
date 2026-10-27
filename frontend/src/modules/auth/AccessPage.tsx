import { useState } from 'react';
import type { FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Brand } from '../../shared/Brand';
import { Icon } from '../../shared/Icon';
import { ApiError, login as loginApi } from '../../shared/api';
import { useToast } from '../../shared/Toast';
import { clientError } from '../../shared/httpErrors';
export function postLoginPath(state: unknown): string {
  if (!state || typeof state !== 'object' || !('from' in state)) return '/';
  const from = state.from;
  if (typeof from !== 'string' || !from.startsWith('/') || from.startsWith('//') || from.includes('\\')) return '/';
  return from.split(/[?#]/)[0] === '/acceso' ? '/' : from;
}

export function AccessPage() {
  const toast = useToast();
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setNotice('');
    try {
      await loginApi(String(data.get('email') || ''), String(data.get('password') || ''), data.get('recordarme') === 'on');
      navigate(postLoginPath(location.state), { replace: true });
    } catch (error) {
      const message = error instanceof ApiError && error.status === 401
        ? error.message : clientError(error, 'No se pudo conectar con el servidor.');
      setNotice(message);
      toast('No se pudo iniciar sesión', message, 'err');
    } finally { setBusy(false); }
  }
  return (
    <main className="login-page">
      <section className="login-brand-panel">
        <div className="login-brand"><Brand inverse /></div>
        <div className="login-brand-copy">
          <h1>Convierte la conversación social en <span>decisiones</span>.</h1>
          <p>Mediciones, clusters con IA, sentimiento, detección de bots e informes ejecutivos en una sola plataforma.</p>
        </div>
        <div className="brand-claims" aria-label="Información institucional">
          <div><strong>6</strong><span>redes y medios monitoreados</span></div>
          <div><strong>&lt; 15 min</strong><span>SLA por ejecución</span></div>
          <div><strong>100%</strong><span>trazabilidad auditada</span></div>
        </div>
        <svg className="login-wave" viewBox="0 0 800 220" preserveAspectRatio="none" aria-hidden="true">
          <defs><linearGradient id="login-wave-gradient" x1="0" x2="1"><stop offset="0" stopColor="#04B8FB" /><stop offset=".35" stopColor="#1293F8" /><stop offset=".7" stopColor="#3655D2" /><stop offset="1" stopColor="#7850EE" /></linearGradient></defs>
          {[0, 1, 2, 3].map((index) => <path key={index} d={`M0 ${150 - index * 18} C 160 ${90 - index * 20}, 300 ${200 - index * 10}, 460 ${130 - index * 16} S 720 ${80 - index * 8}, 800 ${120 - index * 14}`} stroke="url(#login-wave-gradient)" strokeWidth={2 - index * 0.3} fill="none" opacity={1 - index * 0.2} />)}
        </svg>
      </section>
      <section className="login-form-panel">
        <form className="login-card" onSubmit={submit}>
          <img className="login-symbol" src="/brand/symbol.png" alt="" />
          <h2>Bienvenido de nuevo</h2>
          <p className="muted">Ingresa con tu cuenta corporativa de Syntra.</p>
          <div className="stack">
            <div className="field"><label htmlFor="email">Correo electrónico</label><input id="email" name="email" type="email" autoComplete="username" placeholder="Correo electrónico" /></div>
            <div className="field"><label htmlFor="password">Contraseña</label><input id="password" name="password" type="password" autoComplete="current-password" placeholder="Contraseña" /></div>
          </div>
          <div className="login-options"><label className="remember"><input type="checkbox" name="recordarme" /> Recordarme</label></div>
          <button className="button primary full" type="submit" disabled={busy}>Ingresar <Icon name="arrow" size={16} /></button>
          <p className={`implementation-note${notice ? ' error' : ''}`} role="status">{notice}</p>
        </form>
      </section>
    </main>
  );
}

