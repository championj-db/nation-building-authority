import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';
import type { CaseStatus, RiskBand } from '../../../shared/contracts';
import { personName } from '../lib/format';

/* Toast -------------------------------------------------------------------------------------- */

type ToastKind = 'info' | 'error';
const ToastContext = createContext<(message: string, kind?: ToastKind) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<{ message: string; kind: ToastKind } | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const show = useCallback((message: string, kind: ToastKind = 'info') => {
    window.clearTimeout(timer.current);
    setToast({ message, kind });
    timer.current = window.setTimeout(() => setToast(null), kind === 'error' ? 6500 : 3600);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className={`toast${toast ? ' show' : ''}${toast?.kind === 'error' ? ' error' : ''}`} role="status" aria-live="polite">
        {toast?.message}
      </div>
    </ToastContext.Provider>
  );
}
export const useToast = () => useContext(ToastContext);

/* Display bits ------------------------------------------------------------------------------- */

export function Skeleton({ width = '100%', height = 12, style }: { width?: number | string; height?: number; style?: React.CSSProperties }) {
  return <div className="skeleton" style={{ width, height, ...style }} aria-hidden="true" />;
}

export function ErrorNotice({ title, message, onRetry }: { title: string; message: string | null; onRetry?: () => void }) {
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

const BAND_LABEL: Record<RiskBand, string> = { high: 'High', medium: 'Medium' };

/** Score plus band word: risk is never colour alone. */
export function RiskBadge({ score, band }: { score: number; band: RiskBand }) {
  return (
    <span className={`risk ${band}`}>
      {score} · {BAND_LABEL[band] ?? band}
    </span>
  );
}

const STATUS_LABEL: Record<CaseStatus, string> = { unassigned: 'Unassigned', review: 'In review', closed: 'Closed' };

export function StatusLabel({
  status,
  assignee,
  user,
  closedToday,
}: {
  status: CaseStatus;
  assignee?: string | null;
  user?: string | null;
  closedToday?: boolean;
}) {
  const who = status === 'review' && assignee ? (assignee === user ? 'You' : personName(assignee)) : null;
  return (
    <span className={`state ${status}`}>
      {status === 'closed' && closedToday ? 'Closed today' : STATUS_LABEL[status]}
      {who && <span className="who">{who}</span>}
    </span>
  );
}
