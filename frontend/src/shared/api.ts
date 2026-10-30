/** Access JWT vive solo en memoria. El refresh se envía como cookie HttpOnly. */
export type Cliente = {
  id: number; nombre: string; rfc: string | null; sector: string | null; contacto: string | null;
  estado_id: number; creado_en: string; creado_por: number | null;
  actualizado_en: string; actualizado_por: number | null;
};
export type ClienteDetalle = Cliente & {
  creado_por_nombre: string | null;
  actualizado_por_nombre: string | null;
};
export type CuentaResumen = {
  id: number; cliente_id: number; nombre: string; estado_id: number;
};

export type Yo = {
  usuario: { id: number; nombre: string; email: string; rol_id: number };
  rol: { id: number; nombre: string; ver_todas: boolean };
  permisos: Record<string, string[]>;
  cuentas_visibles: number[];
};

let accessToken: string | null = null;
let onTokenChange: ((token: string | null) => void) | null = null;
let pendingRefresh: Promise<boolean> | null = null;

export function watchToken(listener: (token: string | null) => void) {
  onTokenChange = listener;
  return () => { if (onTokenChange === listener) onTokenChange = null; };
}

export function setToken(token: string | null) {
  accessToken = token;
  onTokenChange?.(token);
}

export class ApiError extends Error {
  constructor(public status: number, message: string, public detail?: unknown) { super(message); }
}

async function checked(response: Response) {
  if (response.ok) return response;
  let message = `Error ${response.status}`;
  let detail: unknown;
  try {
    const body = await response.json();
    detail = body.detail;
    message = typeof body.detail === 'string' ? body.detail
      : typeof body.title === 'string' ? body.title : message;
  } catch { /* respuesta sin JSON */ }
  throw new ApiError(response.status, message, detail);
}

export async function login(email: string, password: string, recordarme: boolean) {
  const response = await checked(await fetch('/api/v1/auth/login', {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, recordarme }),
  }));
  const body = await response.json();
  setToken(body.access_token);
}

export async function refreshAccess(): Promise<boolean> {
  if (pendingRefresh) return pendingRefresh;
  pendingRefresh = (async () => {
    try {
      const response = await checked(await fetch('/api/v1/auth/refresh', { method: 'POST', credentials: 'include' }));
      const body = await response.json();
      setToken(body.access_token);
      return true;
    } catch { setToken(null); return false; }
    finally { pendingRefresh = null; }
  })();
  return pendingRefresh;
}

export async function api(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  const response = await fetch(`/api/v1${path}`, { ...init, headers, credentials: 'include' });
  if (response.status === 401 && retry && await refreshAccess()) return api(path, init, false);
  return checked(response);
}

export async function logout(todas = false) {
  try { if (accessToken) await api(`/auth/logout${todas ? '?todas=true' : ''}`, { method: 'POST' }, false); }
  finally { setToken(null); }
}

export function hasToken() { return Boolean(accessToken); }

export type ActorCatalogo = {
  id: number; red: string; uso: string; nombre: string; actor: string;
  max_registros: number; max_urls_por_corrida: number; memoria_mb: number;
  nota: string | null; estado_id: number;
};

export type ScraperResumen = {
  id: number; nombre: string; medicion_id: number; estado_id: number;
  ejecucion_auto: boolean; gn_activo: boolean; frecuencia_min: number | null;
  proxima_ejecucion: string | null; redes: string[];
};

export type EjecucionScraper = { proceso_id: number; estado: string; reutilizado: boolean };

export async function listActors(): Promise<ActorCatalogo[]> {
  const body = await (await api('/actores?estado=activos&limite=200')).json();
  return body.items ?? [];
}

export async function listScrapers(medicionId: number | string): Promise<ScraperResumen[]> {
  const body = await (await api(`/scrapers?medicion_id=${medicionId}`)).json();
  return body.items ?? [];
}

// Cada "ejecutar ahora" es una corrida nueva; el Idempotency-Key solo protege
// contra el reenvío de la MISMA solicitud (p. ej. el reintento tras un 401).
export async function executeScraper(scraperId: number, body: Record<string, unknown> = {}): Promise<EjecucionScraper> {
  const response = await api(`/scrapers/${scraperId}/ejecutar`, {
    method: 'POST',
    headers: { 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify(body),
  });
  return response.json();
}
