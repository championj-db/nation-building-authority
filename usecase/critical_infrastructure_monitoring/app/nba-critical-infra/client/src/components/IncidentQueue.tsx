import { useMemo, useState } from 'react';
import { formatAge, formatPeople, formatTime } from '../lib/format';
import { SECTORS, SECTOR_LABELS, STATUS_LABELS } from '../lib/model';
import type { IncidentRow } from '../lib/rows';
import { SectorBadge } from './icons';
import { EmptyState, ErrorState, Icon, Skeleton } from './primitives';

const PAGE = 8;

interface Props {
  now: Date;
  incidents: IncidentRow[] | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  sector: string;
  onSectorChange: (sector: string) => void;
  onRefresh: () => void;
  onReview: (row: IncidentRow) => void;
}

export function IncidentQueue({ now, incidents, loading, refreshing, error, sector, onSectorChange, onRefresh, onReview }: Props) {
  const [query, setQuery] = useState('');
  const [rating, setRating] = useState('all');
  const [status, setStatus] = useState('open');
  const [showAll, setShowAll] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (incidents ?? []).filter((row) => {
      const text = `${row.asset_name} ${row.asset_code} ${row.operator_name} ${row.locality} ${row.incident_title}`.toLowerCase();
      return (
        (!q || text.includes(q)) &&
        (sector === 'all' || row.sector === sector) &&
        (rating === 'all' || row.risk_rating === rating) &&
        (status === 'all' || (status === 'open' ? row.status === 'open' : row.status !== 'open'))
      );
    });
  }, [incidents, query, sector, rating, status]);

  const visible = showAll ? filtered : filtered.slice(0, PAGE);
  const filtersActive = query.trim() !== '' || sector !== 'all' || rating !== 'all' || status !== 'open';
  const firstOpen = visible.find((r) => r.status === 'open')?.incident_id;

  return (
    <section className="section" id="queue" aria-labelledby="queue-heading">
      <div className="container">
        <div className="row-between section-heading">
          <div>
            <p className="eyebrow">Priority work</p>
            <h2 id="queue-heading">Incidents requiring action</h2>
            <p className="lead">Ranked by risk: likelihood of failure, scaled by the people who rely on the asset and everything downstream of it.</p>
          </div>
          <button className="btn btn-secondary" onClick={onRefresh} disabled={refreshing || loading}>
            <Icon.Refresh spinning={refreshing} />
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        <div className="toolbar" role="search" aria-label="Incident filters">
          <input
            className="input"
            type="search"
            placeholder="Search asset, operator or place"
            aria-label="Search incidents"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setShowAll(false);
            }}
          />
          <select className="select" aria-label="Filter by sector" value={sector} onChange={(e) => onSectorChange(e.target.value)}>
            <option value="all">All sectors</option>
            {SECTORS.map((s) => (
              <option key={s} value={s}>
                {SECTOR_LABELS[s]}
              </option>
            ))}
          </select>
          <select className="select" aria-label="Filter by risk rating" value={rating} onChange={(e) => setRating(e.target.value)}>
            <option value="all">All ratings</option>
            <option value="extreme">Extreme</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
          </select>
          <select className="select" aria-label="Filter by decision status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="open">Awaiting decision</option>
            <option value="decided">Decided this shift</option>
            <option value="all">All incidents</option>
          </select>
          <span className="meta" aria-live="polite">
            {loading ? 'Loading incidents…' : `${filtered.length} incident${filtered.length === 1 ? '' : 's'} shown`}
          </span>
        </div>

        {error && !incidents ? (
          <ErrorState title="The incident queue could not load" message={error} action={<button className="btn btn-secondary" onClick={onRefresh}>Try again</button>} />
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
              title="No incidents match these filters"
              action={
                <button
                  className="btn btn-secondary"
                  onClick={() => {
                    setQuery('');
                    setRating('all');
                    setStatus('open');
                    onSectorChange('all');
                  }}
                >
                  Clear filters
                </button>
              }
            />
          ) : (
            <EmptyState title="No open incidents">Every incident in this run has a recorded decision. New incidents appear after the next risk engine run.</EmptyState>
          )
        ) : (
          <>
            <div className="alert-list">
              {visible.map((row) => {
                const decided = row.status !== 'open';
                const sev = row.risk_rating === 'extreme' ? 'critical' : String(row.risk_rating);
                return (
                  <article className={`alert-row${decided ? ' decided' : ''}`} key={String(row.incident_id)} aria-label={`${row.asset_name}, ${row.incident_title}, ${row.risk_rating} risk ${row.risk_score}`}>
                    <div className="score-badge">
                      <span className="score" aria-label={`Risk score ${row.risk_score}`}>
                        {row.risk_score}
                      </span>
                      <span className={`sev ${sev}`}>{row.risk_rating}</span>
                    </div>
                    <div>
                      <SectorBadge sector={String(row.sector)} />
                      <div className="asset-title">{row.asset_name}</div>
                      <p className="alert-copy">{row.operator_name}</p>
                    </div>
                    <div>
                      <strong>{row.incident_title}</strong>
                      <p className="alert-copy">{row.evidence_summary}</p>
                    </div>
                    <div>
                      <span className="meta">
                        {row.locality}, {row.state} · raised <span className="num">{formatAge(row.created_ts, now)}</span> ago
                      </span>
                      <div className="impact-line">
                        {Number(row.downstream_assets) > 0
                          ? `${row.impact_summary} · ${formatPeople(row.people_affected)} people`
                          : `${formatPeople(row.people_served)} people served`}
                      </div>
                    </div>
                    <div className="row-actions">
                      {decided ? (
                        <span className={row.status === 'dispatched' ? 'pill success' : 'pill'} title={`${row.decided_by ?? ''} at ${formatTime(row.decided_ts)}`}>
                          {STATUS_LABELS[String(row.status)]}
                        </span>
                      ) : null}
                      <button className={`btn ${row.incident_id === firstOpen ? 'btn-primary' : 'btn-secondary'}`} onClick={() => onReview(row)}>
                        {decided ? 'View decision' : 'Review'}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
            {filtered.length > PAGE ? (
              <div className="list-footer">
                <button className="btn btn-ghost" onClick={() => setShowAll((v) => !v)}>
                  {showAll ? 'Show fewer' : `Show all ${filtered.length} incidents`}
                </button>
              </div>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
