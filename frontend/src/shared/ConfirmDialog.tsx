import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';

type Props = {
  title: string;
  description: ReactNode;
  error?: string;
  busy: boolean;
  confirmLabel: string;
  busyLabel: string;
  onConfirm: () => void;
  onClose: () => void;
};

/** Diálogo de confirmación usado por la eliminación lógica de los maestros. */
export function ConfirmDialog({ title, description, error, busy, confirmLabel, busyLabel, onConfirm, onClose }: Props) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    confirmRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [busy, onClose]);
  return <div className="command-scrim" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
    <section className="command-panel discard-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title" aria-describedby="confirm-dialog-description">
      <div className="panel-heading"><h2 id="confirm-dialog-title">{title}</h2></div>
      <p id="confirm-dialog-description">{description}</p>
      {error && <p className="client-delete-error" role="alert">{error}</p>}
      <div className="form-actions"><button className="button" type="button" onClick={onClose} disabled={busy}>Cancelar</button><button ref={confirmRef} className="button danger-button" type="button" onClick={onConfirm} disabled={busy}>{busy ? busyLabel : confirmLabel}</button></div>
    </section>
  </div>;
}
