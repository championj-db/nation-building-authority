import { AlertTriangle, RotateCcw } from 'lucide-react';
import type { ReactNode } from 'react';
import type { Status } from '../../../shared/contracts';
import { STATUSES } from '../../../shared/contracts';

export function Skeleton({ width = '100%', height = 14 }: { width?: number | string; height?: number }) {
  return <span className="skeleton" style={{ width, height }} aria-hidden="true" />;
}

export function SkeletonRows({ rows = 5, height = 52 }: { rows?: number; height?: number }) {
  return (
    <div aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} style={{ padding: '12px 20px', borderBottom: '1px solid var(--line-soft)' }}>
          <Skeleton width={`${55 + ((i * 17) % 35)}%`} height={14} />
          <div style={{ height: 8 }} />
          <Skeleton width="30%" height={height > 40 ? 11 : 8} />
        </div>
      ))}
    </div>
  );
}

export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="notice-box error" role="alert">
      <span>
        <AlertTriangle size={15} style={{ verticalAlign: -2, marginRight: 8 }} aria-hidden="true" />
        {message}
      </span>
      {onRetry && (
        <button className="button small" onClick={onRetry}>
          <RotateCcw aria-hidden="true" /> Try again
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children}
    </div>
  );
}

export function StatusText({ status, label }: { status: Status; label?: string }) {
  return <span className={`status ${status}`}>{label ?? STATUSES[status] ?? status}</span>;
}

export function PanelHead({
  title,
  copy,
  children,
  id,
}: {
  title: string;
  copy?: ReactNode;
  children?: ReactNode;
  id?: string;
}) {
  return (
    <div className="panel-head">
      <div>
        <h2 id={id}>{title}</h2>
        {copy && <p className="panel-copy">{copy}</p>}
      </div>
      {children}
    </div>
  );
}
