import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { X } from 'lucide-react';
import { ACCESS_CLASS_LABEL, type AccessClass } from '../lib/model';

/* Toast ------------------------------------------------------------------------------------- */

type ToastKind = 'info' | 'error';
const ToastContext = createContext<(message: string, kind?: ToastKind) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ message: string; kind: ToastKind; id: number } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const show = useCallback((message: string, kind: ToastKind = 'info') => {
    window.clearTimeout(timer.current);
    setToast({ message, kind, id: Date.now() });
    timer.current = window.setTimeout(() => setToast(null), kind === 'error' ? 6000 : 3200);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div
        className={`toast${toast ? ' show' : ''}${toast?.kind === 'error' ? ' error' : ''}`}
        role="status"
        aria-live="polite"
      >
        {toast?.message}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

/* Dialog ------------------------------------------------------------------------------------ */

/** Native <dialog>: focus trap, Escape and inert background come from the platform. */
export function Dialog({
  open,
  onClose,
  title,
  subtitle,
  children,
  footer,
  wide,
  className = '',
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  className?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={`dialog${wide ? ' wide' : ''} ${className}`}
      aria-labelledby="dialog-title"
      onClose={onClose}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === ref.current) onClose();
      }}
    >
      {open && (
        <>
          <div className="panel-head">
            <div>
              <h2 id="dialog-title">{title}</h2>
              {subtitle && <span className="sub">{subtitle}</span>}
            </div>
            <button
              type="button"
              className="button small icon-button ghost no-print"
              aria-label="Close"
              onClick={onClose}
            >
              <X className="icon" aria-hidden="true" />
            </button>
          </div>
          <div className="dialog-body">{children}</div>
          {footer && <div className="dialog-foot no-print">{footer}</div>}
        </>
      )}
    </dialog>
  );
}

/* Display bits ------------------------------------------------------------------------------ */

export function Skeleton({
  width = '100%',
  height = 14,
  style,
}: {
  width?: number | string;
  height?: number;
  style?: React.CSSProperties;
}) {
  return <div className="skeleton" style={{ width, height, ...style }} aria-hidden="true" />;
}

export function PanelSkeleton({ lines = 4 }: { lines?: number }) {
  return (
    <div className="stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={`${90 - i * 12}%`} height={i === 0 ? 28 : 14} />
      ))}
    </div>
  );
}

export function ErrorNotice({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string | null;
  onRetry?: () => void;
}) {
  return (
    <div className="notice error" role="alert">
      <strong>{title}</strong>
      <div className="muted xs" style={{ marginTop: 4 }}>
        {message ?? 'The query did not complete.'}
      </div>
      {onRetry && (
        <div className="row">
          <button type="button" className="button small" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

const SWATCH_CLASS: Record<AccessClass, string> = {
  beyond: 'beyond',
  near: 'near',
  within: '',
  suppressed: 'suppressed',
  no_population: 'none',
};

/** Access class is always shown as colour plus text, never colour alone. */
export function ClassLabel({ value }: { value: AccessClass }) {
  return (
    <span className="class-cell">
      <span className={`swatch ${SWATCH_CLASS[value]}`} aria-hidden="true" />
      {ACCESS_CLASS_LABEL[value]}
    </span>
  );
}

export function useOutsideClose(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onPointer = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose]);
  return ref;
}
