import { useMemo, useState } from 'react';
import type { PipelineSummary } from '../App';
import type { CaseStates } from '../lib/caseState';
import { useBaseParams, useRows, useScope } from '../lib/data';
import { clock, int, money, moneyShort, plural } from '../lib/format';
import {
  applyFilters,
  DEFAULT_FILTERS,
  filtersActive,
  mergeState,
  summarise,
  tabCounts,
  type CaseRow,
  type Filters,
  type QueueTab,
} from '../lib/queue';
import { CaseDrawer } from './CaseDrawer';
import { ErrorNotice, RiskBadge, Skeleton, StatusLabel } from './primitives';

const PAGE = 25;

const TAB_LABEL: Record<QueueTab, string> = {
  all: 'All cases',
  unassigned: 'Unassigned',
  review: 'In review',
  mine: 'Assigned to me',
  closed: 'Closed today',
};

export function QueueView({
  tab,
  onTab,
  caseId,
  onCase,
  caseStates,
  pipeline,
  onPrecision,
}: {
  tab: QueueTab;
  onTab: (t: QueueTab) => void;
  caseId: string | null;
  onCase: (id: string | null) => void;
  caseStates: CaseStates;
  pipeline: PipelineSummary | null;
  onPrecision: () => void;
}) {
  const { user } = useScope();
  const base = useBaseParams();
  const queue = useRows('case_queue', base);
  const rows = useMemo(() => (queue.data ?? []) as CaseRow[], [queue.data]);
  const cases = useMemo(() => mergeState(rows, caseStates.states), [rows, caseStates.states]);
  const counts = useMemo(() => tabCounts(cases, user), [cases, user]);
  const totals = useMemo(() => summarise(cases), [cases]);
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [page, setPage] = useState(0);
  const visible = useMemo(() => applyFilters(cases, tab, filters, user), [cases, tab, filters, user]);
  const pages = Math.max(1, Math.ceil(visible.length / PAGE));
  const current = Math.min(page, pages - 1);
  const shown = visible.slice(current * PAGE, current * PAGE + PAGE);
  const selected = caseId ? (cases.find((c) => c.case_id === caseId) ?? null) : null;
  const loading = queue.loading && queue.data == null;

  // Back to the first page whenever the slice of the queue changes.
  const sliceKey = `${tab}|${filters.term}|${filters.band}|${filters.program}|${filters.sort}`;
  const [pageSlice, setPageSlice] = useState(sliceKey);
  if (pageSlice !== sliceKey) {
    setPageSlice(sliceKey);
    setPage(0);
  }

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => setFilters((f) => ({ ...f, [key]: value }));
  const programs = useMemo(() => {
    const map = new Map<string, string>();
    for (const r of rows) map.set(r.program, r.program_label);
    return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [rows]);

  return (
    <main className="workspace" id="main">
      <section className="page-head" aria-labelledby="page-title">
        <div>
          <h1 id="page-title">Payment review queue</h1>
          <p className="lede">
            Prioritise potentially improper payments, inspect linked evidence, and record an accountable investigation outcome.
          </p>
        </div>
        <div className="status-note">
          <strong>Synthetic demonstration data</strong>
          <br />
          Scores are indicators, not findings.
        </div>
      </section>

      <section className="summary-grid" aria-label="Queue summary">
        <Metric label="Unassigned cases" value={loading ? null : int(totals.unassigned)} foot={loading ? '' : `${plural(totals.highOpen, 'high-risk case')} open`} />
        <Metric label="In review" value={loading ? null : int(totals.review)} foot="Across the investigation team" />
        <Metric label="Value under review" value={loading ? null : moneyShort(totals.openValue)} foot="Not an estimated recovery amount" />
        <Metric
          label="Outcomes captured"
          value={caseStates.loading ? null : caseStates.enabled ? int(caseStates.outcomesTotal) : '–'}
          foot={
            caseStates.enabled ? (
              <a
                href="?view=precision"
                onClick={(e) => {
                  e.preventDefault();
                  onPrecision();
                }}
              >
                Feeds precision monitoring
              </a>
            ) : (
              'Outcome capture is not connected'
            )
          }
        />
      </section>

      <div className="tabs" role="tablist" aria-label="Case status">
        {(Object.keys(TAB_LABEL) as QueueTab[]).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            id={`tab-${key}`}
            aria-selected={tab === key}
            aria-controls="case-queue"
            className="tab"
            onClick={() => onTab(key)}
          >
            {TAB_LABEL[key]} <span className="num">{loading ? '–' : counts[key]}</span>
          </button>
        ))}
      </div>

      <section className="panel" id="case-queue" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        <div className="filters">
          <div className="field">
            <label htmlFor="search">Search case, entity or signal</label>
            <input
              className="control"
              id="search"
              type="search"
              placeholder="e.g. IP-2048 or North Harbour"
              value={filters.term}
              onChange={(e) => set('term', e.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="field">
            <label htmlFor="riskFilter">Risk band</label>
            <select className="control" id="riskFilter" value={filters.band} onChange={(e) => set('band', e.target.value as Filters['band'])}>
              <option value="all">All risk bands</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="programFilter">Program</label>
            <select className="control" id="programFilter" value={filters.program} onChange={(e) => set('program', e.target.value)}>
              <option value="all">All programs</option>
              {programs.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="sortFilter">Sort by</label>
            <select className="control" id="sortFilter" value={filters.sort} onChange={(e) => set('sort', e.target.value as Filters['sort'])}>
              <option value="risk">Highest risk</option>
              <option value="value">Highest value</option>
              <option value="age">Oldest first</option>
            </select>
          </div>
          <button type="button" className="button" disabled={!filtersActive(filters)} onClick={() => setFilters(DEFAULT_FILTERS)}>
            Clear filters
          </button>
        </div>

        {queue.error && !queue.data ? (
          <div style={{ padding: 16 }}>
            <ErrorNotice title="The review queue could not be loaded" message={queue.error} onRetry={() => window.location.reload()} />
          </div>
        ) : (
          <div className="table-wrap">
            <table className="case-table" aria-label="Payment review cases" aria-busy={loading}>
              <thead>
                <tr>
                  <th scope="col">Case</th>
                  <th scope="col">Entity</th>
                  <th scope="col">Program</th>
                  <th scope="col">Primary signal</th>
                  <th scope="col">Risk</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num-col">
                    Payment value
                  </th>
                </tr>
              </thead>
              <tbody>
                {loading
                  ? ['s1', 's2', 's3', 's4', 's5', 's6'].map((key) => (
                      <tr key={key} aria-hidden="true">
                        {[56, 180, 110, 150, 88, 80, 76].map((w, j) => (
                          <td key={j}>
                            <Skeleton width={w} />
                          </td>
                        ))}
                      </tr>
                    ))
                  : shown.map((c) => (
                      <tr
                        key={c.case_id}
                        tabIndex={0}
                        aria-selected={c.case_id === caseId}
                        data-case={c.case_id}
                        onClick={() => onCase(c.case_id)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onCase(c.case_id);
                          }
                        }}
                      >
                        <td className="case-id">{c.case_id}</td>
                        <td>
                          <div className="entity">{c.entity_label}</div>
                          <div className="entity-sub">{c.entity_sub}</div>
                        </td>
                        <td>{c.program_label}</td>
                        <td>{c.primary_signal_label}</td>
                        <td>
                          <RiskBadge score={c.risk_score} band={c.risk_band} />
                        </td>
                        <td>
                          <StatusLabel status={c.status} assignee={c.assignee} user={user} closedToday={c.closedToday} />
                        </td>
                        <td className="money">{money(c.payment_value)}</td>
                      </tr>
                    ))}
              </tbody>
            </table>
            {!loading && visible.length === 0 && <EmptyQueue tab={tab} filtered={filtersActive(filters)} onClear={() => setFilters(DEFAULT_FILTERS)} onAll={() => onTab('all')} />}
          </div>
        )}

        <div className="table-foot">
          <span aria-live="polite">
            {loading
              ? 'Loading the governed queue…'
              : visible.length > PAGE
                ? `Showing ${current * PAGE + 1}–${current * PAGE + shown.length} of ${plural(visible.length, 'case')}`
                : `Showing ${plural(visible.length, 'case')}`}
            {caseStates.error && ' · Case status could not be refreshed'}
          </span>
          {pages > 1 && (
            <span className="pager">
              <button type="button" className="button small" disabled={current === 0} onClick={() => setPage(current - 1)}>
                Previous
              </button>
              <span className="mono">
                {current + 1} / {pages}
              </span>
              <button type="button" className="button small" disabled={current >= pages - 1} onClick={() => setPage(current + 1)}>
                Next
              </button>
            </span>
          )}
          <span>Last model refresh: {pipeline ? clock(pipeline.scored_ts) : '–'}</span>
        </div>
      </section>

      {caseId && (
        <CaseDrawer
          key={caseId}
          caseId={caseId}
          item={selected}
          loadingQueue={loading}
          caseStates={caseStates}
          onClose={() => onCase(null)}
        />
      )}
    </main>
  );
}

function Metric({ label, value, foot }: { label: string; value: string | null; foot: React.ReactNode }) {
  return (
    <article className="metric">
      <span className="metric-label">{label}</span>
      {value == null ? <Skeleton width={72} height={30} /> : <strong className="metric-value">{value}</strong>}
      <span className="metric-foot">{foot}</span>
    </article>
  );
}

function EmptyQueue({ tab, filtered, onClear, onAll }: { tab: QueueTab; filtered: boolean; onClear: () => void; onAll: () => void }) {
  if (filtered) {
    return (
      <div className="empty">
        <strong>No cases match these filters</strong>
        <p>Search looks across case references, entity names and signals. Widen the risk band or program, or clear the filters.</p>
        <button type="button" className="button small" onClick={onClear}>
          Clear filters
        </button>
      </div>
    );
  }
  const copy: Record<QueueTab, [string, string]> = {
    all: ['The queue is clear', 'Every case the model raised has an outcome. New cases arrive when the scoring job next runs.'],
    unassigned: ['Nothing is waiting for an investigator', 'Every open case is in review with someone on the team.'],
    review: ['No cases are in review', 'Open a case from the queue and choose “Assign to me” to start a review.'],
    mine: ['You have no cases in review', 'Open a case and choose “Assign to me”. Cases you hold appear here until you record an outcome.'],
    closed: ['No outcomes recorded today', 'Cleared and escalated cases appear here for the rest of the day they were decided.'],
  };
  const [title, body] = copy[tab];
  return (
    <div className="empty">
      <strong>{title}</strong>
      <p>{body}</p>
      {tab !== 'all' && (
        <button type="button" className="button small" onClick={onAll}>
          Show all open cases
        </button>
      )}
    </div>
  );
}
