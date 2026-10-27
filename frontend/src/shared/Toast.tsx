import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Icon } from './Icon';

type ToastKind = 'ok' | 'err';
type ToastItem = { id: number; title: string; body: string; kind: ToastKind };
type ToastAction = (title: string, body?: string, kind?: ToastKind) => void;

const ToastContext = createContext<ToastAction>(() => undefined);

export function useToast() { return useContext(ToastContext); }

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const [errors, setErrors] = useState<ToastItem[]>([]);
  const sequence = useRef(0);
  const timers = useRef<number[]>([]);
  useEffect(() => () => { timers.current.forEach(window.clearTimeout); }, []);
  const toast = useCallback<ToastAction>((title, body = '', kind = 'ok') => {
    const id = ++sequence.current;
    if (kind === 'err') {
      setErrors(current => current.some(item => item.title === title && item.body === body)
        ? current : [...current, { id, title, body, kind }]);
      return;
    }
    setItems(current => [...current, { id, title, body, kind }]);
    timers.current.push(window.setTimeout(() => setItems(current => current.filter(item => item.id !== id)), 3800));
  }, []);
  return <ToastContext.Provider value={toast}>
    {children}
    <div className="toasts" aria-live="polite" aria-atomic="false">
      {items.map(item => <div className={`toast ${item.kind}`} role={item.kind === 'err' ? 'alert' : 'status'} key={item.id}>
        <span className="t-ico"><Icon name={item.kind === 'err' ? 'alert' : 'check'} size={16} /></span>
        <span className="toast-copy"><b>{item.title}</b>{item.body && <span>{item.body}</span>}</span>
      </div>)}
    </div>
    {errors[0] && <div className="error-dialog-backdrop">
      <section className="error-dialog" role="alertdialog" aria-modal="true" aria-labelledby="error-dialog-title" aria-describedby="error-dialog-message">
        <span className="error-dialog-icon"><Icon name="alert" size={20} /></span>
        <div className="error-dialog-copy"><h2 id="error-dialog-title">{errors[0].title}</h2><p id="error-dialog-message">{errors[0].body}</p></div>
        <button className="button error-dialog-ok" type="button" autoFocus onClick={() => setErrors(current => current.slice(1))}>OK</button>
      </section>
    </div>}
  </ToastContext.Provider>;
}
