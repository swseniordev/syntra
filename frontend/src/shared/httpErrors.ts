import { ApiError } from './api';

export function clientError(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    if (error.status >= 500) return 'El servidor no pudo completar la operación. Inténtalo de nuevo.';
    if (error.status === 401) return 'La sesión venció. Ingresa de nuevo.';
    if (error.status === 403) return 'No tienes permiso para realizar esta acción.';
    return typeof error.message === 'string' && error.message !== '[object Object]' ? error.message : fallback;
  }
  return fallback;
}