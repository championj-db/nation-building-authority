import { AlarmClock, CalendarClock, ChevronRight, FileWarning, ScanSearch } from 'lucide-react';
import { useMemo, useState } from 'react';
import { firstName, greeting, money, plural, received } from '../lib/format';
import { applyFilter, counts, FILTERS, summarise, type FilterKey } from '../lib/queue';
import type { PipelineStatus, QueueRow } from '../lib/types';
import { ErrorNotice, PanelHead, Skeleton, SkeletonRows } from './primitives';
import { QueueList } from './QueueList';

export function Overview({
  email,
  rows,
  loading,
  error,
  status,
  decisionsRecorded,
  onOpen,
  onQueue,
  onRetry,
}: {
  email: string | null;
  rows: QueueRow[] | null;
  loading: boolean;
  error: string | null;
  status: PipelineStatus | null;
  decisionsRecorded: number;
  onOpen: (docId: string) => void;
  onQueue: (filter: FilterKey | 'due' | 'overdue') => void;
  onRetry: () => void;
}) {
  const [filter, setFilter] = useState<FilterKey>('all');
  const summary = useMemo(() => summarise(rows ?? []), [rows]);
  const c = useMemo(() => counts(rows ?? []), [rows]);
  const shown = useMemo(() => applyFilter(rows ?? [], filter), [rows, filter]);
  const name = firstName(email);
  const today = new Date().toLocaleDateString('en-AU', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });

  const tiles = [
    {
      key: 'due' as const,
      label: 'Due within 5 business days',
      icon: <CalendarClock aria-hidden="true" />,
      value: summary.dueSoon,
      foot: summary.dueSoon ? `${money(summary.dueSoonValue, true)} to accept in time` : 'Nothing due this week',
    },
    {
      key: 'overdue' as const,
      label: 'Past the pay-by date',
      icon: <AlarmClock aria-hidden="true" />,
      value: summary.overdue,
      alert: summary.overdue > 0,
      foot: summary.overdue ? `${money(summary.interest)} interest accrued so far` : 'No interest accruing',
    },
    {
      key: 'needs_review' as const,
      label: 'Needs review',
      icon: <ScanSearch aria-hidden="true" />,
      value: summary.needsReview,
      foot: summary.heldFields ? `${plural(summary.heldFields, 'field')} to check on the page` : 'No fields held',
    },
    {
      key: 'exception' as const,
      label: 'To return to supplier',
      icon: <FileWarning aria-hidden="true" />,
      value: summary.toReturn,
      foot: 'Not correctly rendered, so no clock',
    },
  ];

  const s = status;
  const stages = [
    {
      n: 1,
      title: 'Land',
      done: Boolean(s),
      text: s
        ? `${plural(s.documents_landed, 'document')} in the inbox volume · last ${received(s.last_arrival_ts)}`
        : 'Change detection on the inbox volume',
    },
    {
      n: 2,
      title: 'Parse',
      done: Boolean(s && s.documents_parsed >= s.documents_landed),
      text: s
        ? `${s.documents_parsed.toLocaleString('en-AU')} parsed with ai_parse_document · ${plural(s.parse_errors, 'error')}`
        : 'Text, tables, layout and page images',
    },
    {
      n: 3,
      title: 'Classify & extract',
      done: Boolean(s && s.documents_classified >= s.documents_parsed),
      text: s
        ? `${s.documents_classified.toLocaleString('en-AU')} classified · ${s.invoices_extracted.toLocaleString('en-AU')} invoices extracted with cited evidence`
        : 'Typed fields against a schema per document type',
    },
    {
      n: 4,
      title: 'Check & review',
      done: false,
      text: s
        ? `${s.straight_through_pct ?? '-'}% straight through · ${plural(decisionsRecorded, 'decision')} recorded here`
        : 'Human control before a record is relied on',
    },
  ];

  return (
    <div className="content">
      <div className="page-head">
        <div>
          <h1>
            {greeting()}
            {name ? `, ${name}` : ''}.
          </h1>
          <p className="page-intro">
            Decide which invoices are correctly rendered before the payment clock runs out. Uncertain fields are held
            for you to check against the page. All content shown is synthetic demonstration data.
          </p>
        </div>
        <div className="date-note">{today}</div>
      </div>

      {error && <ErrorNotice message={error} onRetry={onRetry} />}

      <div className="summary-grid">
        {tiles.map((t) => (
          <button key={t.key} className="card summary-card" onClick={() => onQueue(t.key)}>
            <span className="summary-label">
              {t.label}
              {t.icon}
            </span>
            {loading ? (
              <Skeleton width={56} height={28} />
            ) : (
              <strong className={`summary-value${t.alert ? ' alert' : ''}`}>{t.value}</strong>
            )}
            <span className="summary-foot">
              {loading ? <Skeleton width="70%" height={10} /> : t.foot}
              <ChevronRight aria-hidden="true" className="tile-go" />
            </span>
          </button>
        ))}
      </div>

      <div className="work-grid">
        <section className="card" aria-labelledby="overview-queue">
          <PanelHead
            id="overview-queue"
            title="Review queue"
            copy="Ordered by days left on the payment clock, then by arrival."
          >
            <button className="button" onClick={() => onQueue(filter)}>
              Open queue
            </button>
          </PanelHead>
          <div className="filter-row" role="group" aria-label="Filter review queue">
            {FILTERS.map((f) => (
              <button key={f.key} className="filter" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
                {f.label} <span className="num">{c[f.key]}</span>
              </button>
            ))}
          </div>
          {loading ? <SkeletonRows rows={6} /> : <QueueList rows={shown} onOpen={onOpen} limit={8} />}
          {!loading && shown.length > 8 && (
            <div className="panel-foot">
              <span>Showing 8 of {shown.length}</span>
              <button className="link-button" onClick={() => onQueue(filter)}>
                See all {shown.length}
              </button>
            </div>
          )}
        </section>

        <div className="stack">
          <section className="card" aria-labelledby="pipeline-title">
            <PanelHead
              id="pipeline-title"
              title="Document pipeline"
              copy="Reusable governed processing path, live counts."
            />
            {stages.map((st) => (
              <div key={st.n} className={`stage${st.done ? ' complete' : ''}`}>
                <span className="stage-num">{st.n}</span>
                <div>
                  <h3>{st.title}</h3>
                  <p>{st.text}</p>
                </div>
              </div>
            ))}
          </section>
          <aside className="card assurance" aria-labelledby="assurance-title">
            <h3 id="assurance-title">Assurance note</h3>
            <p>
              Parsed content is treated at the highest classification found in the corpus. Confidence is a routing
              control, not a quality claim: a high score is never proof that a value is right.
            </p>
            <p>
              The clock starts the day after delivery is acknowledged and a correctly rendered invoice is received. From
              1 January 2027 the maximum term is 10 business days for every invoice.
            </p>
            <a
              href="https://www.finance.gov.au/publications/resource-management-guides/supplier-pay-time-or-pay-interest-policy-rmg-417"
              target="_blank"
              rel="noreferrer"
            >
              Read RMG 417
            </a>
          </aside>
        </div>
      </div>
    </div>
  );
}
