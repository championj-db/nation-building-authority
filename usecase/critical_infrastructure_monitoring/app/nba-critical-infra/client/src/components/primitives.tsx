import type { CSSProperties, ReactNode } from 'react';
import { friendlyError } from '../lib/status';

export function Skeleton({ width = '100%', height = 16, style }: { width?: number | string; height?: number | string; style?: CSSProperties }) {
  return <span className="skeleton" aria-hidden="true" style={{ width, height, ...style }} />;
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state" role="status">
      <strong>{title}</strong>
      {children ? <span>{children}</span> : null}
      {action}
    </div>
  );
}

export function ErrorState({ title = 'This panel could not load', message, action }: { title?: string; message: string; action?: ReactNode }) {
  return (
    <div className="state error" role="alert">
      <strong>{title}</strong>
      <span>{friendlyError(message)}</span>
      {action}
    </div>
  );
}

const iconProps = { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, 'aria-hidden': true } as const;

export const Icon = {
  Brand: () => (
    <svg {...iconProps} strokeWidth={1.7}>
      <path d="M4 19V9l8-5 8 5v10M8 19v-5h8v5M3 19h18" />
    </svg>
  ),
  Check: () => (
    <svg {...iconProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 2.5 2.5L16 9" />
    </svg>
  ),
  Attention: () => (
    <svg {...iconProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5.5M12 16.5h.01" />
    </svg>
  ),
  Refresh: ({ spinning = false }: { spinning?: boolean }) => (
    <svg {...iconProps} className={spinning ? 'spin' : undefined}>
      <path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v4h-4" />
    </svg>
  ),
  Shield: () => (
    <svg {...iconProps}>
      <path d="M12 3 5 6v5c0 4.5 3 8.3 7 10 4-1.7 7-5.5 7-10V6l-7-3Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  ),
};

export function Toast({ message, tone }: { message: string | null; tone: 'info' | 'error' }) {
  return (
    <div className={`toast${message ? ' show' : ''}${tone === 'error' ? ' error' : ''}`} role="status" aria-live="polite">
      {message}
    </div>
  );
}
