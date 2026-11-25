import { FACTOR_LABELS, formatAge, formatHour, formatInt, formatTime, RISK_TYPE_LABELS, toDate } from '../lib/format';
import { severityFor } from '../lib/model';
import type { RegisterRow, TrendRow } from '../lib/rows';
import { EmptyState, ErrorState, Skeleton } from './primitives';

interface RegisterProps {
  now: Date;
  rows: RegisterRow[] | null;
  loading: boolean;
  error: string | null;
  onSelect: (row: RegisterRow) => void;
  /** Decision status by asset id, so the register agrees with the queue. */
  statusByAsset: Map<string, string>;
}

export function RiskRegister({ now, rows, loading, error, onSelect, statusByAsset }: RegisterProps) {
  const runTs = rows?.[0]?.run_ts;
  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      <div className="row-between panel-head">
        <div>
          <h2 id="entities-heading">Entity risk register</h2>
          <p className="lead">Highest-scoring assets requiring operational attention.</p>
        </div>
        <span className="tag">{runTs ? `Updated ${formatTime(runTs)}` : 'Updating…'}</span>
      </div>
      {error && !rows ? (
        <div style={{ padding: 20 }}>
          <ErrorState title="The risk register could not load" message={error} />
        </div>
      ) : loading ? (
        <div style={{ padding: 20, display: 'grid', gap: 12 }} aria-busy="true">
          {[0, 1, 2, 3, 4].map((i) => (
            <Skeleton key={i} height={22} />
          ))}
        </div>
      ) : !rows || rows.length === 0 ? (
        <div style={{ padding: 20 }}>
          <EmptyState title="No scored entities yet">Run the pipeline job to score sighted assets.</EmptyState>
        </div>
      ) : (
        <div className="ds-table-wrap">
          <table className="ds-table">
            <caption className="sr-only">Highest-scoring assets. Select a row to review contributing factors.</caption>
            <thead>
              <tr>
                <th scope="col">Asset</th>
                <th scope="col">Operator</th>
                <th scope="col">Primary factor</th>
                <th scope="col">Last seen</th>
                <th scope="col" className="num-col">
                  Risk score
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const score = Number(row.risk_score);
                const sev = severityFor(score);
                const status = statusByAsset.get(String(row.asset_id));
                return (
                  <tr
                    key={String(row.asset_id)}
                    tabIndex={0}
                    aria-label={`Review ${row.registration_plate}, risk score ${score}`}
                    onClick={() => onSelect(row)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onSelect(row);
                      }
                    }}
                  >
                    <td>
                      <strong className="num">{row.registration_plate}</strong>
                      {status === 'routed' ? <div><span className="pill success" style={{ marginTop: 4 }}>Routed</span></div> : status === 'monitoring' ? <div><span className="pill" style={{ marginTop: 4 }}>Monitoring</span></div> : null}
                    </td>
                    <td>{row.operator_name}</td>
                    <td>
                      {RISK_TYPE_LABELS[String(row.risk_type)] ?? row.risk_type}
                      <div className="meta">{FACTOR_LABELS[String(row.primary_factor)] ?? row.primary_factor}</div>
                    </td>
                    <td>
                      <span className="num">{formatAge(row.last_seen_ts, now)}</span> ago
                    </td>
                    <td className="num-col">
                      <span className="risk-score">{score}</span>
                      {score >= alertThresholdOf(row) ? <div className={`sev ${sev}`} style={{ justifyContent: 'flex-end', display: 'flex' }}>{sev}</div> : <div className="meta">below threshold</div>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface TrendProps {
  rows: TrendRow[] | null;
  loading: boolean;
  error: string | null;
}

/** Area chart of hourly sightings by alerting assets - ported from the design's SVG. */
const alertThresholdOf = (row: RegisterRow) => Number(row.alert_threshold ?? 70);

export function TrendPanel({ rows, loading, error }: TrendProps) {
  const W = 360;
  const H = 180;
  const base = 160;
  const points = (rows ?? []).map((r) => ({ t: toDate(r.hour_ts), v: Number(r.risk_sightings) || 0 })).filter((p) => p.t);
  const total = points.reduce((s, p) => s + p.v, 0);
  const last8 = points.slice(-8).reduce((s, p) => s + p.v, 0);
  const max = Math.max(1, ...points.map((p) => p.v));
  const step = points.length > 1 ? W / (points.length - 1) : W;
  const xy = points.map((p, i) => [i * step, base - (p.v / max) * 128] as const);
  const line = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  const area = xy.length ? `M0 ${base} ${xy.map(([x, y]) => `L${x.toFixed(1)} ${y.toFixed(1)}`).join(' ')} L${W} ${base} Z` : '';
  const ticks = points.length > 1 ? [0, Math.floor((points.length - 1) / 2), points.length - 1] : [];
  const peak = points.reduce((best, p) => (p.v > (best?.v ?? -1) ? p : best), points[0]);

  return (
    <aside className="card" aria-labelledby="trend-heading">
      <div className="row-between">
        <div>
          <p className="eyebrow">Last 24 hours</p>
          <h3 id="trend-heading">Incoming risk signals</h3>
        </div>
        {loading ? <Skeleton width={48} height={20} /> : <span className="num">{formatInt(total)}</span>}
      </div>
      {error && !rows ? (
        <div style={{ marginTop: 20 }}>
          <ErrorState title="Trend unavailable" message={error} />
        </div>
      ) : loading ? (
        <Skeleton height={180} style={{ marginTop: 20 }} />
      ) : points.length < 2 ? (
        <div style={{ marginTop: 20 }}>
          <EmptyState title="Not enough signal history">The trend needs at least two hours of sightings from alerting assets.</EmptyState>
        </div>
      ) : (
        <svg
          className="trend-chart"
          viewBox={`0 0 ${W} ${H + 16}`}
          role="img"
          aria-label={`Area chart of hourly sightings by alerting assets: ${formatInt(total)} in 24 hours, ${formatInt(last8)} in the last 8 hours, peaking at ${formatInt(peak?.v)} around ${formatHour(peak?.t)}`}
        >
          <path d={area} fill="var(--ioc-surface-warm)" />
          <path d={line} fill="none" stroke="var(--ioc-accent)" strokeWidth={3} strokeLinejoin="round" strokeLinecap="round" />
          <line x1={0} y1={base} x2={W} y2={base} stroke="color-mix(in oklab, var(--ioc-border), var(--ioc-muted) 15%)" />
          <line x1={0} y1={base - 128} x2={W} y2={base - 128} stroke="var(--ioc-border-soft)" strokeDasharray="3 4" />
          <text className="axis" x={0} y={base - 134}>
            {formatInt(max)} / hour
          </text>
          {ticks.map((i) => (
            <text key={i} className="axis" x={i * step} y={base + 16} textAnchor={i === 0 ? 'start' : i === points.length - 1 ? 'end' : 'middle'}>
              {formatHour(points[i]?.t)}
            </text>
          ))}
        </svg>
      )}
      <p className="meta" style={{ marginTop: 12, marginBottom: 0 }}>
        {points.length > 1 ? `${formatInt(last8)} in the last 8 hours. ` : ''}Select an entity to review contributing factors and recent movement.
      </p>
    </aside>
  );
}
