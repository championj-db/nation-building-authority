import { useMemo, useState } from 'react';
import { formatAge, formatTime } from '../lib/format';
import type { AlertRow } from '../lib/rows';
import { EmptyState, ErrorState, Icon, Skeleton } from './primitives';

const PAGE = 8;

interface Props {
  now: Date;
  alerts: AlertRow[] | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  onRefresh: () => void;
  onReview: (row: AlertRow) => void;
}

const STATUS_LABEL: Record<string, { text: string; className: string }> = {
  routed: { text: 'Routed to field', className: 'pill success' },
  monitoring: { text: 'Monitoring', className: 'pill' },
};

export function AlertQueue({ now, alerts, loading, refreshing, error, onRefresh, onReview }: Props) {
  const [query, setQuery] = useState('');
  const [risk, setRisk] = useState('all');
  const [status, setStatus] = useState('open');
  const [showAll, setShowAll] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (alerts ?? []).filter((row) => {
      const matchesQuery = !q || `${row.registration_plate} ${row.operator_name}`.toLowerCase().includes(q);
      const matchesRisk = risk === 'all' || row.risk_type === risk;
      const matchesStatus = status === 'all' || (status === 'open' ? row.status === 'open' : row.status !== 'open');
      return matchesQuery && matchesRisk && matchesStatus;
    });
  }, [alerts, query, risk, status]);

  const visible = showAll ? filtered : filtered.slice(0, PAGE);
  const filtersActive = query.trim() !== '' || risk !== 'all' || status !== 'open';

  return (
    <section className="section" id="queue" aria-labelledby="queue-heading">
      <div className="container">
        <div className="row-between section-heading">
          <div>
            <p className="eyebrow">Priority work</p>
            <h2 id="queue-heading">Alerts requiring review</h2>
            <p className="lead">Ranked by priority band, then by most recent sighting.</p>
          </div>
          <button className="btn btn-secondary" onClick={onRefresh} disabled={refreshing || loading}>
            <Icon.Refresh spinning={refreshing} />
            {refreshing ? 'Refreshing…' : 'Refresh queue'}
          </button>
        </div>

        <div className="toolbar" role="search" aria-label="Alert filters">
          <input
            className="input"
            type="search"
            placeholder="Search registration or operator"
            aria-label="Search alerts"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setShowAll(false);
            }}
          />
          <select className="select" aria-label="Filter by risk type" value={risk} onChange={(e) => setRisk(e.target.value)}>
            <option value="all">All risk types</option>
            <option value="fatigue">Fatigue</option>
            <option value="roadworthiness">Roadworthiness</option>
            <option value="mass">Over-mass</option>
            <option value="route">Route variance</option>
          </select>
          <select className="select" aria-label="Filter by decision status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">Awaiting decision</option>
            <option value="decided">Decided this shift</option>
            <option value="all">All alerts</option>
          </select>
          <span className="meta" aria-live="polite">
            {loading ? 'Loading alerts…' : `${filtered.length} alert${filtered.length === 1 ? '' : 's'} shown`}
          </span>
        </div>

        {error && !alerts ? (
          <ErrorState title="The alert queue could not load" message={error} action={<button className="btn btn-secondary" onClick={onRefresh}>Try again</button>} />
        ) : loading ? (
          <div className="alert-list" aria-busy="true">
            {[0, 1, 2].map((i) => (
              <div className="alert-row" key={i}>
                <Skeleton width={56} height={36} />
                <Skeleton width="70%" height={36} />
                <Skeleton width="85%" height={36} />
                <Skeleton width="75%" height={36} />
                <Skeleton width={120} height={44} />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          filtersActive ? (
            <EmptyState
              title="No alerts match these filters"
              action={
                <button
                  className="btn btn-secondary"
                  onClick={() => {
                    setQuery('');
                    setRisk('all');
                    setStatus('open');
                  }}
                >
                  Clear filters
                </button>
              }
            />
          ) : (
            <EmptyState title="No open alerts">Every alert in this run has a recorded decision. New alerts appear after the next risk engine run.</EmptyState>
          )
        ) : (
          <>
            <div className="alert-list">
              {visible.map((row, index) => {
                const decided = row.status !== 'open';
                const badge = STATUS_LABEL[String(row.status)];
                return (
                  <article className={`alert-row${decided ? ' decided' : ''}`} key={String(row.alert_id)} aria-label={`${row.registration_plate}, ${row.alert_title}, risk score ${row.risk_score}`}>
                    <div className="score-badge">
                      <span className="score" aria-label={`Risk score ${row.risk_score}`}>{row.risk_score}</span>
                      <span className={`sev ${row.severity}`}>{row.severity}</span>
                    </div>
                    <div>
                      <div className="alert-title">{row.registration_plate}</div>
                      <p className="alert-copy">{row.operator_name}</p>
                    </div>
                    <div>
                      <strong>{row.alert_title}</strong>
                      <p className="alert-copy">
                        {String(row.alert_summary).replace(' - ', ' · ')}
                      </p>
                    </div>
                    <div>
                      <span className="meta">Last seen</span>
                      <div>
                        {row.last_seen_location} · <span className="num">{formatAge(row.last_seen_ts, now)}</span> ago
                      </div>
                    </div>
                    <div className="row-actions">
                      {badge ? (
                        <span className={badge.className} title={`${row.decided_by ?? ''} at ${formatTime(row.decided_ts)}`}>
                          {badge.text}
                        </span>
                      ) : null}
                      <button className={`btn ${index === 0 && !decided ? 'btn-primary' : 'btn-secondary'}`} onClick={() => onReview(row)}>
                        {decided ? 'View decision' : 'Review alert'}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
            {filtered.length > PAGE ? (
              <div className="list-footer">
                <button className="btn btn-ghost" onClick={() => setShowAll((v) => !v)}>
                  {showAll ? 'Show fewer' : `Show all ${filtered.length} alerts`}
                </button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
