import { Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import { money } from '../lib/format';
import { applyFilter, counts, FILTERS, type FilterKey } from '../lib/queue';
import type { QueueRow } from '../lib/types';
import { ErrorNotice, PanelHead, SkeletonRows } from './primitives';
import { QueueList } from './QueueList';

export type QueueMode = FilterKey | 'due' | 'overdue';
const PAGE = 25;

export function QueueView({
  rows,
  loading,
  error,
  mode,
  onMode,
  onOpen,
  onRetry,
}: {
  rows: QueueRow[] | null;
  loading: boolean;
  error: string | null;
  mode: QueueMode;
  onMode: (m: QueueMode) => void;
  onOpen: (docId: string) => void;
  onRetry: () => void;
}) {
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const all = useMemo(() => rows ?? [], [rows]);
  const c = useMemo(() => counts(all), [all]);
  const shown = useMemo(() => {
    if (mode === 'due')
      return applyFilter(all, 'all', search).filter(
        (r) => r.clock_state !== 'overdue' && r.clock_state !== 'not_started' && (r.business_days_left ?? 99) <= 5
      );
    if (mode === 'overdue') return applyFilter(all, 'all', search).filter((r) => r.clock_state === 'overdue');
    return applyFilter(all, mode, search);
  }, [all, mode, search]);
  const pages = Math.max(1, Math.ceil(shown.length / PAGE));
  const current = Math.min(page, pages - 1);
  const value = shown.reduce((s, r) => s + (r.total_inc_gst ?? 0), 0);

  return (
    <div className="content">
      <div className="page-head">
        <div>
          <h1>Review queue</h1>
          <p className="page-intro">
            Every open invoice and adjustment note, ordered by the payment clock. Ready items passed every check with
            confident fields; the rest need a decision from you.
          </p>
        </div>
      </div>
      {error && <ErrorNotice message={error} onRetry={onRetry} />}
      <section className="card" aria-labelledby="queue-title">
        <PanelHead
          id="queue-title"
          title={
            mode === 'due'
              ? 'Due within 5 business days'
              : mode === 'overdue'
                ? 'Past the pay-by date'
                : (FILTERS.find((f) => f.key === mode)?.label ?? 'All open')
          }
          copy={`${shown.length} documents · ${money(value, true)}`}
        />
        <div className="filter-row" role="group" aria-label="Filter review queue">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              className="filter"
              aria-pressed={mode === f.key}
              onClick={() => {
                setPage(0);
                onMode(f.key);
              }}
            >
              {f.label} <span className="num">{c[f.key]}</span>
            </button>
          ))}
          <label className="search">
            <span className="sr-only">Search supplier, invoice or purchase order</span>
            <Search aria-hidden="true" />
            <input
              value={search}
              onChange={(e) => {
                setPage(0);
                setSearch(e.target.value);
              }}
              placeholder="Supplier, invoice or PO"
            />
          </label>
        </div>
        {loading ? (
          <SkeletonRows rows={8} />
        ) : (
          <QueueList rows={shown.slice(current * PAGE, current * PAGE + PAGE)} onOpen={onOpen} showHead />
        )}
        {!loading && shown.length > PAGE && (
          <div className="pager">
            <span>
              {current * PAGE + 1}-{Math.min(shown.length, current * PAGE + PAGE)} of {shown.length}
            </span>
            <span style={{ display: 'flex', gap: 8 }}>
              <button className="button small" disabled={current === 0} onClick={() => setPage(current - 1)}>
                Previous
              </button>
              <button className="button small" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
                Next
              </button>
            </span>
          </div>
        )}
      </section>
    </div>
  );
}
