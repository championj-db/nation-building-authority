import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  Skeleton,
  Spinner,
} from '@databricks/appkit-ui/react';
import { AlertTriangle, Check, Copy, Inbox, RotateCw, Search, X } from 'lucide-react';
import { useMediaQuery } from '../lib/api';

export function PageHeader({ title, detail, actions }: { title: string; detail: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{detail}</p>
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Panel({
  title,
  note,
  actions,
  children,
  className = '',
  flush = false,
  id,
}: {
  title: ReactNode;
  note?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  flush?: boolean;
  id?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section className={`panel ${className}`} aria-labelledby={headingId} id={id}>
      <div className="panel-header">
        <div>
          <h2 id={headingId}>{title}</h2>
          {note && <p className="muted">{note}</p>}
        </div>
        {actions && <div className="panel-actions">{actions}</div>}
      </div>
      <div className={flush ? 'panel-body flush' : 'panel-body'}>{children}</div>
    </section>
  );
}

export function LoadingRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="skeleton-stack" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Alert variant="destructive" className="inline-alert">
      <AlertTriangle />
      <AlertTitle>This view could not be loaded</AlertTitle>
      <AlertDescription>
        <p>{message}</p>
        {onRetry ? (
          <Button size="sm" variant="outline" onClick={onRetry}>
            <RotateCw /> Try again
          </Button>
        ) : (
          <p>
            Reload the page. If it keeps failing, check the SQL warehouse is running and the app can read the schema.
          </p>
        )}
      </AlertDescription>
    </Alert>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state" role="status">
      <Inbox aria-hidden="true" />
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

/** Loading / error / empty, then content. */
export function QueryState({
  loading,
  error,
  empty,
  emptyTitle = 'Nothing to show',
  emptyDetail,
  emptyAction,
  rows,
  children,
}: {
  loading: boolean;
  error: string | null;
  empty: boolean;
  emptyTitle?: string;
  emptyDetail?: ReactNode;
  emptyAction?: ReactNode;
  rows?: number;
  children: ReactNode;
}) {
  if (error) return <ErrorState message={error} />;
  if (loading) return <LoadingRows rows={rows} />;
  if (empty)
    return (
      <EmptyState title={emptyTitle} action={emptyAction}>
        {emptyDetail}
      </EmptyState>
    );
  return <>{children}</>;
}

export type Tone = 'good' | 'warn' | 'bad' | 'info' | 'neutral';

export function toneFor(value: string | null | undefined): Tone {
  const v = (value ?? '').toLowerCase();
  if (/^(complete|current|online|verified|issued|mapped|confirm|active|succeeded|success|true|match)/.test(v))
    return 'good';
  if (/(gap|offline|failed|broken|expired|high|reject|mismatch|no approved|failure|error)/.test(v)) return 'bad';
  if (/^(ready|submitted)/.test(v)) return 'info';
  if (/^draft/.test(v)) return 'neutral';
  if (/(expir|review|degraded|medium|pending|running|unmapped|queued)/.test(v)) return 'warn';
  if (/(not evidence|no threshold|retired)/.test(v)) return 'neutral';
  return 'neutral';
}

export function Status({ value, tone, label }: { value: string | null | undefined; tone?: Tone; label?: string }) {
  const text = label ?? value ?? '—';
  return <span className={`status ${tone ?? toneFor(value)}`}>{text}</span>;
}

export function SearchBox({
  value,
  onChange,
  label,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  placeholder?: string;
}) {
  return (
    <div className="search-box">
      <Search size={16} aria-hidden="true" />
      <Input
        type="search"
        aria-label={label}
        placeholder={placeholder ?? label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {value && (
        <button type="button" className="clear-search" onClick={() => onChange('')} aria-label="Clear search">
          <X size={14} />
        </button>
      )}
    </div>
  );
}

export function FilterSelect({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  allLabel: string;
}) {
  return (
    <Select value={value || 'all'} onValueChange={(next) => onChange(next === 'all' ? '' : next)}>
      <SelectTrigger className="filter-select" aria-label={label}>
        <SelectValue placeholder={allLabel} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">{allLabel}</SelectItem>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function Toolbar({ children, summary }: { children: ReactNode; summary?: ReactNode }) {
  return (
    <div className="toolbar">
      <div className="toolbar-controls">{children}</div>
      {summary && (
        <p className="toolbar-summary" aria-live="polite">
          {summary}
        </p>
      )}
    </div>
  );
}

export interface Column<T> {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  className?: string;
}

/**
 * Selectable table. Rows are keyboard reachable (Tab, then Enter or Space) and announce selection.
 */
export function DataTable<T>({
  columns,
  rows,
  rowKey,
  selectedKey,
  onSelect,
  caption,
  limit,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  selectedKey?: string | null;
  onSelect?: (row: T) => void;
  caption: string;
  limit?: number;
}) {
  const [shown, setShown] = useState(limit ?? rows.length);
  const bodyRef = useRef<HTMLTableSectionElement>(null);
  const selectedIndex = selectedKey ? rows.findIndex((row) => rowKey(row) === selectedKey) : -1;
  // Deep links (?id=) can point past the first page or below the fold: reveal the selected row.
  useEffect(() => {
    if (selectedIndex < 0) return;
    if (limit && selectedIndex >= shown) setShown(selectedIndex + 1);
    bodyRef.current?.querySelector('tr.selected')?.scrollIntoView({ block: 'nearest' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey, selectedIndex]);
  const visible = limit ? rows.slice(0, shown) : rows;
  const onKey = (event: KeyboardEvent, row: T) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onSelect?.(row);
    }
  };
  return (
    <>
      <div className="table-wrap" tabIndex={-1}>
        <table className="data-table">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key} scope="col" className={column.className}>
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody ref={bodyRef}>
            {visible.map((row) => {
              const key = rowKey(row);
              const selected = key === selectedKey;
              return (
                <tr
                  key={key}
                  className={`${onSelect ? 'selectable' : ''} ${selected ? 'selected' : ''}`}
                  onClick={onSelect ? () => onSelect(row) : undefined}
                  onKeyDown={onSelect ? (event) => onKey(event, row) : undefined}
                  tabIndex={onSelect ? 0 : undefined}
                  aria-selected={onSelect ? selected : undefined}
                >
                  {columns.map((column) => (
                    <td key={column.key} className={column.className}>
                      {column.cell(row)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {limit && rows.length > shown && (
        <div className="table-more">
          <Button variant="outline" size="sm" onClick={() => setShown((n) => n + (limit ?? 50))}>
            Show {Math.min(limit, rows.length - shown)} more of {rows.length - shown} remaining
          </Button>
        </div>
      )}
    </>
  );
}

/** Side panel on wide screens, a sheet on narrow ones. */
export function DetailPanel({
  open,
  onClose,
  title,
  children,
  placeholder,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  placeholder: ReactNode;
}) {
  const narrow = useMediaQuery('(max-width: 1100px)');
  if (narrow)
    return (
      <Sheet open={open} onOpenChange={(next) => !next && onClose()}>
        {/* Do not auto-focus the first control: it is often an irreversible decision button. */}
        <SheetContent
          side="right"
          className="detail-sheet"
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => event.preventDefault()}
        >
          <SheetHeader className="sr-only">
            <SheetTitle>{title}</SheetTitle>
          </SheetHeader>
          <div className="detail-sheet-body">{children}</div>
        </SheetContent>
      </Sheet>
    );
  return (
    <aside className="detail-panel" aria-label={title}>
      {open ? children : <div className="detail-placeholder">{placeholder}</div>}
    </aside>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export function CopyValue({ value, display }: { value: string; display?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="copy-value">
      <code title={value}>{display ?? value}</code>
      <button
        type="button"
        className="icon-button"
        aria-label={copied ? 'Copied' : 'Copy to clipboard'}
        onClick={() => {
          void navigator.clipboard?.writeText(value).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          });
        }}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </span>
  );
}

export function InlineSpinner({ label }: { label: string }) {
  return (
    <span className="inline-spinner" role="status">
      <Spinner /> {label}
    </span>
  );
}

/** Proportional bar of complete / expiring / gap counts. */
export function StackedBar({
  complete,
  expiring,
  gap,
  label,
}: {
  complete: number;
  expiring: number;
  gap: number;
  label: string;
}) {
  const total = Math.max(complete + expiring + gap, 1);
  return (
    <div className="stacked-bar" role="img" aria-label={label}>
      {complete > 0 && <span className="seg good" style={{ width: `${(complete / total) * 100}%` }} />}
      {expiring > 0 && <span className="seg warn" style={{ width: `${(expiring / total) * 100}%` }} />}
      {gap > 0 && <span className="seg bad" style={{ width: `${(gap / total) * 100}%` }} />}
    </div>
  );
}

export function matches(query: string, ...values: unknown[]) {
  if (!query) return true;
  const haystack = values
    .map((v) =>
      v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v as string | number)
    )
    .join(' ')
    .toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => haystack.includes(term));
}

export function uniqueOptions<T>(rows: T[], value: (row: T) => string | null | undefined, label?: (row: T) => string) {
  const seen = new Map<string, string>();
  for (const row of rows) {
    const v = value(row);
    if (v && !seen.has(v)) seen.set(v, label ? label(row) : v);
  }
  return Array.from(seen, ([v, l]) => ({ value: v, label: l })).sort((a, b) => a.label.localeCompare(b.label));
}
