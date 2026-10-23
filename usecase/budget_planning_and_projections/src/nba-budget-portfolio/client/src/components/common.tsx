import { useEffect } from 'react';
import { Alert, AlertDescription, Skeleton } from '@databricks/appkit-ui/react';
import { X } from 'lucide-react';

export type Tone = 'neutral' | 'risk' | 'good' | 'warn';

export function StatusBadge({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: Tone }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function statusTone(status: string | null | undefined): Tone {
  const s = String(status ?? '');
  if (['Endorsed', 'Approved', 'Locked', 'Attested', 'Action closed', 'Green', 'SUCCESS', 'Within capacity'].includes(s)) return 'good';
  if (['Action required', 'Returned', 'Red', 'Amber/Red', 'Breach', 'FAILED'].includes(s)) return 'risk';
  if (['Submitted', 'Awaiting attestation', 'Amber', 'Constrained', 'Draft', 'Pending'].includes(s)) return 'warn';
  return 'neutral';
}

export function KpiCard({ label, value, detail, onClick }: { label: string; value: string; detail: React.ReactNode; onClick?: () => void }) {
  const body = <><p className="kpi-label">{label}</p><div className="kpi-value">{value}</div><div className="kpi-detail">{detail}</div></>;
  return onClick
    ? <button className="card kpi-card clickable" onClick={onClick}>{body}</button>
    : <article className="card kpi-card">{body}</article>;
}

export function QueryError({ message }: { message: string }) {
  return (
    <Alert variant="destructive" className="query-alert">
      <AlertDescription>{message} Refresh the view or try a different filter.</AlertDescription>
    </Alert>
  );
}

export function LoadingCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid kpis" aria-label="Loading metrics">
      {Array.from({ length: count }, (_, index) => (
        <div className="card skeleton-card" key={index}>
          <Skeleton className="skeleton-label" />
          <Skeleton className="skeleton-value" />
          <Skeleton className="skeleton-detail" />
        </div>
      ))}
    </div>
  );
}

export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return <div className="exception-list" aria-label="Loading">{Array.from({ length: rows }, (_, index) => <Skeleton className="list-skeleton" key={index} />)}</div>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="empty-state">{children}</p>;
}

export function Modal({ title, eyebrow, onClose, children, wide = false }: { title: string; eyebrow?: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop open" role="dialog" aria-modal="true" aria-labelledby="modal-title" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className={`modal ${wide ? 'wide' : ''}`}>
        <div className="modal-head">
          <div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h2 id="modal-title">{title}</h2></div>
          <button className="button icon-button" aria-label="Close dialog" onClick={onClose}><X size={18} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: Array<[T, string]>; onChange: (value: T) => void; label: string }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map(([key, text]) => (
        <button key={key} role="radio" aria-checked={value === key} className={value === key ? 'active' : ''} onClick={() => onChange(key)}>{text}</button>
      ))}
    </div>
  );
}
