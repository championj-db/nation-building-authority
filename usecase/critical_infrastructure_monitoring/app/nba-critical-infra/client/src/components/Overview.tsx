import { countPhrase, formatEyebrowNow, formatInt, formatMinutes, formatPct, formatSeconds, formatTime, formatTimeSeconds, greeting, zoneLabel } from '../lib/format';
import { SECTORS, SECTOR_LABELS, type Sector } from '../lib/model';
import type { OpsStatusRow, SectorRow } from '../lib/rows';
import { feedHealth } from '../lib/status';
import { SectorIcon } from './icons';
import { ErrorState, Skeleton } from './primitives';

interface HeroProps {
  now: Date;
  firstName: string;
  openCount: number | null;
  sectorsAffected: number;
  ops: OpsStatusRow | null;
  opsLoading: boolean;
  opsError: string | null;
}

export function Hero({ now, firstName, openCount, sectorsAffected, ops, opsLoading, opsError }: HeroProps) {
  const health = feedHealth(ops);
  const headline =
    openCount == null
      ? `${greeting(now)}, ${firstName}.`
      : openCount === 0
        ? `${greeting(now)}, ${firstName}. No incidents need action.`
        : `${greeting(now)}, ${firstName}. ${countPhrase(openCount, 'incident')} ${openCount === 1 ? 'needs' : 'need'} action across ${countPhrase(sectorsAffected, 'sector', false)}.`;

  return (
    <section className="section hero" id="overview" aria-labelledby="overview-heading">
      <div className="container hero-split">
        <div>
          <p className="eyebrow">National operating picture · {formatEyebrowNow(now)}</p>
          <h1 id="overview-heading">{headline}</h1>
          <p className="lead">One view across roads, rail, water and energy: active hazards, assets under stress, and the services that depend on them.</p>
        </div>
        <div className="system-status" aria-live="polite">
          <div className="row-between">
            <strong>Feed status</strong>
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
          <StatusLine label="Latest reading" loading={opsLoading} value={ops ? formatTimeSeconds(ops.latest_reading_ts) : '—'} />
          <StatusLine label="Sensors reporting" loading={opsLoading} value={ops ? `${formatInt(ops.sensors_reporting)} of ${formatInt(ops.sensors_total)}` : '—'} />
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

interface SectorTilesProps {
  sectors: SectorRow[] | null;
  ops: OpsStatusRow | null;
  loading: boolean;
  error: string | null;
  /** Open incident counts per sector after officer decisions (the gold table counts the run). */
  openBySector: Record<string, number> | null;
  onSelect: (sector: Sector) => void;
}

export function SectorTiles({ sectors, ops, loading, error, openBySector, onSelect }: SectorTilesProps) {
  const bySector = new Map((sectors ?? []).map((s) => [String(s.sector), s]));
  const prevSensors = ops?.prev_sensors_reporting == null ? null : Number(ops.prev_sensors_reporting);
  const prevDetect = ops?.prev_median_detection_minutes == null ? null : Number(ops.prev_median_detection_minutes);
  return (
    <section className="section" aria-label="Sector health">
      <div className="container">
        {error && !sectors ? (
          <ErrorState title="Sector status could not load" message={error} />
        ) : (
          <div className="grid-4 sector-grid">
            {SECTORS.map((sector) => {
              const s = bySector.get(sector);
              const open = openBySector?.[sector] ?? (s ? Number(s.open_incidents) : null);
              const extreme = s ? Number(s.extreme_incidents) : 0;
              return (
                <button
                  type="button"
                  className={`card sector-tile sector-${sector}`}
                  key={sector}
                  onClick={() => onSelect(sector)}
                  aria-label={`${SECTOR_LABELS[sector]}: ${open ?? 'loading'} open incidents. Show ${SECTOR_LABELS[sector].toLowerCase()} incidents`}
                >
                  <div className="row-between">
                    <span className="sector-name">
                      <span className="sector-glyph">
                        <SectorIcon sector={sector} size={16} />
                      </span>
                      {SECTOR_LABELS[sector]}
                    </span>
                    {extreme ? <span className="sev critical">{extreme} extreme</span> : <span className="tag">No extreme</span>}
                  </div>
                  {loading || open == null ? (
                    <Skeleton width="40%" height={32} style={{ marginTop: 16 }} />
                  ) : (
                    <div className="stat-num num">{formatInt(open)}</div>
                  )}
                  <p className="stat-label">Open incidents</p>
                  <dl className="sector-facts">
                    <div>
                      <dt>Assets</dt>
                      <dd className="num">{s ? formatInt(s.assets) : '—'}</dd>
                    </div>
                    <div>
                      <dt>In alarm</dt>
                      <dd className="num">{s ? formatInt(s.assets_in_alarm) : '—'}</dd>
                    </div>
                    <div>
                      <dt>Not reporting</dt>
                      <dd className="num">{s ? formatInt(s.assets_not_reporting) : '—'}</dd>
                    </div>
                    <div>
                      <dt>Dependants at risk</dt>
                      <dd className="num">{s ? formatInt(s.dependants_at_risk) : '—'}</dd>
                    </div>
                  </dl>
                </button>
              );
            })}
          </div>
        )}
        {ops ? (
          <p className="meta feed-line">
            <span>
              {formatInt(ops.readings_today)} readings today · {formatInt(ops.sensors_reporting)} of {formatInt(ops.sensors_total)} sensors reporting
              {prevSensors != null ? ` (${formatInt(prevSensors)} previous run)` : ''}
            </span>
            <span>
              Median detection {formatMinutes(ops.median_detection_minutes)}
              {prevDetect != null ? ` (${formatMinutes(prevDetect)} previous run)` : ''} · {formatPct(ops.quarantine_rate, 2)} of readings quarantined · {formatInt(ops.late_readings)} arrived late
            </span>
          </p>
        ) : null}
      </div>
    </section>
  );
}
