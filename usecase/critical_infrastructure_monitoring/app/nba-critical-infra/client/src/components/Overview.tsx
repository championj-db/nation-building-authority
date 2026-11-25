import { countPhrase, formatEyebrowNow, formatInt, formatMinutes, formatPct, formatSeconds, formatTime, formatTimeSeconds, greeting, zoneLabel } from '../lib/format';
import type { OpsStatusRow } from '../lib/rows';
import { feedHealth } from '../lib/status';
import { Skeleton } from './primitives';

interface HeroProps {
  now: Date;
  firstName: string;
  openCount: number | null;
  ops: OpsStatusRow | null;
  opsLoading: boolean;
  opsError: string | null;
}

export function Hero({ now, firstName, openCount, ops, opsLoading, opsError }: HeroProps) {
  const health = feedHealth(ops);
  const headline =
    openCount == null
      ? `${greeting(now)}, ${firstName}.`
      : openCount === 0
        ? `${greeting(now)}, ${firstName}. The queue is clear.`
        : `${greeting(now)}, ${firstName}. ${countPhrase(openCount, 'alert')} ${openCount === 1 ? 'needs' : 'need'} review.`;

  return (
    <section className="section hero" id="overview" aria-labelledby="overview-heading">
      <div className="container hero-split">
        <div>
          <p className="eyebrow">{formatEyebrowNow(now)}</p>
          <h1 id="overview-heading">{headline}</h1>
          <p className="lead">Prioritise alerts, review contributing signals and route field actions from one operational queue.</p>
        </div>
        <div className="system-status" aria-live="polite">
          <div className="row-between">
            <strong>Operational status</strong>
            {opsError ? (
              <span className="pill danger">
                <span className="status-dot danger" />
                Status unavailable
              </span>
            ) : (
              <span className={`pill${health.tone === 'warn' ? ' warn' : ''}`}>
                <span className={`status-dot${health.tone === 'warn' ? ' warn' : health.tone === 'muted' ? ' muted' : ''}`} />
                {health.label}
              </span>
            )}
          </div>
          <StatusLine label="Latest sighting" loading={opsLoading} value={ops ? formatTimeSeconds(ops.latest_sighting_ts) : '—'} />
          <StatusLine label="Processing lag" loading={opsLoading} value={ops ? formatSeconds(ops.processing_lag_seconds) : '—'} />
          <StatusLine label="Risk engine run" loading={opsLoading} value={ops ? `${formatTime(ops.run_ts)} ${zoneLabel(now)}` : '—'} />
        </div>
      </div>
    </section>
  );
}

function StatusLine({ label, value, loading }: { label: string; value: string; loading: boolean }) {
  return (
    <div className="row-between" style={{ marginTop: 10 }}>
      <span className="meta">{label}</span>
      {loading ? <Skeleton width={72} height={14} /> : <span className="num">{value}</span>}
    </div>
  );
}

interface MetricsProps {
  ops: OpsStatusRow | null;
  openCount: number | null;
  loading: boolean;
}

export function Metrics({ ops, openCount, loading }: MetricsProps) {
  const prevOpen = ops?.prev_open_alerts == null ? null : Number(ops.prev_open_alerts);
  const prevQueue = ops?.prev_median_queue_time_minutes == null ? null : Number(ops.prev_median_queue_time_minutes);
  const decided = ops && openCount != null ? Math.max(0, Number(ops.run_open_alerts) - openCount) : null;
  const metrics = [
    {
      label: 'Open alerts',
      tag: 'Now',
      value: openCount == null ? null : formatInt(openCount),
      copy: 'Awaiting an officer decision',
      compare: ops ? `${formatInt(ops.run_open_alerts)} raised this run${decided ? ` · ${decided} decided` : ''}${prevOpen != null ? ` · ${formatInt(prevOpen)} previous run` : ''}` : null,
    },
    {
      label: 'Sightings today',
      tag: 'Today',
      value: ops ? formatInt(ops.sightings_today) : null,
      copy: 'Resolved against known assets',
      compare: ops ? `Latest at ${formatTime(ops.latest_sighting_ts)}` : null,
    },
    {
      label: 'Identity resolution',
      tag: 'Window',
      value: ops ? formatPct(ops.identity_resolution_rate) : null,
      copy: 'Matched to asset and operator',
      compare: ops ? `${formatPct(1 - Number(ops.identity_resolution_rate))} held in quarantine` : null,
    },
    {
      label: 'Median queue time',
      tag: 'Run',
      value: ops ? formatMinutes(ops.median_queue_time_minutes) : null,
      copy: 'From last sighting to the queue',
      compare: prevQueue != null ? `${formatMinutes(prevQueue)} previous run` : ops ? 'First run - no comparison yet' : null,
    },
  ];
  return (
    <section className="section" aria-label="Operational metrics">
      <div className="container">
        <div className="grid-4">
          {metrics.map((m) => (
            <article className="card stat" key={m.label}>
              <div className="row-between">
                <span className="meta">{m.label}</span>
                <span className="tag">{m.tag}</span>
              </div>
              {loading || m.value == null ? <Skeleton width="55%" height={32} style={{ marginTop: 16 }} /> : <div className="stat-num num">{m.value}</div>}
              <p className="stat-label">{m.copy}</p>
              {m.compare ? <p className="stat-compare">{m.compare}</p> : null}
            </article>
          ))}
        </div>
        {ops ? (
          <p className="meta" style={{ margin: '12px 0 0' }}>
            Source: governed gold layer · risk engine run {formatTime(ops.run_ts)} · identity resolution over the full sighting window
          </p>
        ) : null}
      </div>
    </section>
  );
}
