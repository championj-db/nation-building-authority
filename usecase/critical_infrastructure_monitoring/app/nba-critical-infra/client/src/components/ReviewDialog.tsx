import { sql } from '@databricks/appkit-ui/js';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useAnalyticsQuery, useScope } from '../lib/data';
import { formatAge, formatHour, formatMetric, formatPeople, formatTime, toDate } from '../lib/format';
import { CONSEQUENCE_FLOOR, FACTOR_HELP, FACTOR_LABELS, HAZARD_LABELS, STATUS_LABELS, contributions } from '../lib/model';
import { isTrue, type DisruptionRow, type ImpactRow, type IncidentRow, type TelemetryRow } from '../lib/rows';
import { HazardIcon, SectorBadge } from './icons';
import { EmptyState, ErrorState, Icon, Skeleton } from './primitives';

type Disposition = 'dispatch' | 'notify' | 'monitor';

interface Props {
  incident: IncidentRow | null;
  impacts: ImpactRow[];
  disruption: DisruptionRow | null;
  now: Date;
  onClose: () => void;
  onDecided: (message: string) => void;
}

export function ReviewDialog({ incident, impacts, disruption, now, onClose, onDecided }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (incident && !dialog.open) dialog.showModal();
    if (!incident && dialog.open) dialog.close();
  }, [incident]);

  return (
    <dialog
      ref={ref}
      aria-labelledby="review-title"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      {incident ? <ReviewBody key={String(incident.incident_id)} incident={incident} impacts={impacts} disruption={disruption} now={now} onClose={onClose} onDecided={onDecided} /> : null}
    </dialog>
  );
}

function ReviewBody({ incident, impacts, disruption, now, onClose, onDecided }: Props & { incident: IncidentRow }) {
  const { catalog, schema, refresh } = useScope();
  const metric = incident.trigger_metric ? String(incident.trigger_metric) : '';
  const params = useMemo(
    () => ({
      catalog: sql.string(catalog),
      schema: sql.string(schema),
      refresh: sql.string(refresh),
      asset_id: sql.bigint(Number(incident.asset_id)),
      metric: sql.string(metric),
    }),
    [catalog, schema, refresh, incident.asset_id, metric],
  );
  const telemetry = useAnalyticsQuery('asset_telemetry', params);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState<Disposition | null>(null);
  const [error, setError] = useState<string | null>(null);

  const parts = contributions(incident);
  const likelihood = Number(incident.likelihood);
  const consequence = Number(incident.consequence_score);
  const multiplier = Number(incident.consequence_multiplier);
  const decided = incident.status !== 'open';
  const sev = incident.risk_rating === 'extreme' ? 'danger' : 'warn';

  async function decide(disposition: Disposition) {
    setSubmitting(disposition);
    setError(null);
    const evidenceViewed = [
      'risk_score',
      'contributing_factors',
      ...(telemetry.data?.length ? ['telemetry_trend'] : []),
      ...(impacts.length || incident.route_name ? ['downstream_impact'] : []),
      ...(incident.hazard_title ? ['hazard_context'] : []),
    ];
    try {
      const response = await fetch('/api/reviews', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ incidentId: incident.incident_id, disposition, evidenceViewed, notes }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? `Decision was not recorded (${response.status})`);
      }
      const verb = { dispatch: 'Crew dispatched to', notify: `${incident.operator_name} notified about`, monitor: 'Continuing to monitor' }[disposition];
      onDecided(`${verb} ${incident.asset_name}. Decision recorded.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Decision was not recorded');
      setSubmitting(null);
    }
  }

  const byHop = [1, 2].map((hop) => impacts.filter((i) => Number(i.hop) === hop)).filter((g) => g.length);

  return (
    <>
      <div className="dialog-head">
        <div>
          <p className="eyebrow">
            Incident review · <SectorBadge sector={String(incident.sector)} />
          </p>
          <h2 id="review-title" tabIndex={-1} autoFocus>
            {incident.asset_name}
          </h2>
          <p className="alert-copy">
            {incident.incident_title} · {incident.operator_name} · {incident.locality}, {incident.state} · raised {formatAge(incident.created_ts, now)} ago
          </p>
        </div>
        <button className="btn btn-ghost" onClick={onClose} aria-label="Close review">
          Close
        </button>
      </div>

      <div className="dialog-body stack">
        <div className="row-between score-row">
          <div>
            <span className="meta">Risk score</span>
            <div className="stat-num num" style={{ marginTop: 4 }}>
              {incident.risk_score}
            </div>
            <p className="meta" style={{ margin: '6px 0 0' }}>
              Likelihood {likelihood.toFixed(2)} × consequence {multiplier.toFixed(2)}
            </p>
          </div>
          {decided ? (
            <span className={incident.status === 'dispatched' ? 'pill success' : 'pill'}>
              <span className={`status-dot${incident.status === 'dispatched' ? '' : ' muted'}`} />
              {STATUS_LABELS[String(incident.status)]} · {formatTime(incident.decided_ts)}
            </span>
          ) : (
            <span className={`pill ${sev}`}>
              <span className={`status-dot ${sev}`} />
              {String(incident.risk_rating).replace(/^./, (c) => c.toUpperCase())} · open
            </span>
          )}
        </div>

        <div className="card card-rule">
          <h3>Why this was flagged</h3>
          <p className="lead">Likelihood of failure is a weighted sum of four factors, each scaled from normal (0) to clear evidence (1).</p>
          <div className="stack" style={{ marginTop: 16 }}>
            {parts.map((p, i) => (
              <div className={`factor${i === 0 ? ' primary' : ''}`} key={p.factor} title={FACTOR_HELP[p.factor]}>
                <span>
                  {FACTOR_LABELS[p.factor]}
                  <div className="weight">
                    weight {Math.round(p.weight * 100)}% · adds <span className="num">{p.share.toFixed(2)}</span>
                  </div>
                </span>
                <div className="factor-bar" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={Number(p.value.toFixed(2))} aria-label={FACTOR_LABELS[p.factor]}>
                  <div className="factor-fill" style={{ width: `${Math.round(p.value * 100)}%` }} />
                </div>
                <span className="num">{p.value.toFixed(2)}</span>
              </div>
            ))}
          </div>
          <p className="meta" style={{ marginTop: 14, marginBottom: 0 }}>
            Consequence {consequence.toFixed(2)} is the larger of two readings. People {Number(incident.people_consequence_score).toFixed(2)}:{' '}
            {formatPeople(incident.people_affected)} people relying on this asset
            {Number(incident.downstream_assets) ? ` and the ${incident.downstream_assets} assets downstream of it` : ''}.
            {incident.route_name ? ` Network ${Number(incident.network_consequence_score).toFixed(2)}: what its loss does to the ${incident.route_name}.` : ''} It scales
            likelihood between {CONSEQUENCE_FLOOR} and 1.
          </p>
        </div>

        {metric ? (
          <div className="card card-rule">
            <h3>{incident.trigger_metric_label}, last 24 hours</h3>
            {telemetry.error ? (
              <ErrorState title="Telemetry unavailable" message={telemetry.error} />
            ) : telemetry.loading || !telemetry.data ? (
              <Skeleton height={160} style={{ marginTop: 12 }} />
            ) : telemetry.data.length < 2 ? (
              <EmptyState title="Not enough readings in the last 24 hours" />
            ) : (
              <TelemetryChart rows={telemetry.data} />
            )}
          </div>
        ) : null}

        {incident.hazard_title ? (
          <div className="hazard-context">
            <span className={`hazard-glyph sev-${incident.hazard_severity}`}>
              <HazardIcon type={String(incident.hazard_type)} size={18} />
            </span>
            <div>
              <strong>{incident.hazard_title}</strong>
              <div className="meta">
                {HAZARD_LABELS[String(incident.hazard_type)]} warning · {incident.hazard_severity} · this asset is inside the warning area
              </div>
            </div>
          </div>
        ) : null}

        {incident.route_name ? (
          <div className="card card-rule">
            <h3>Network impact</h3>
            <p className="network-headline">
              <span className={`pill ${isTrue(incident.no_alternative) ? 'danger' : 'warn'}`}>
                {incident.network_effect === 'restriction' ? 'Restriction' : 'Closure'}
              </span>{' '}
              <strong>{incident.route_name}</strong>
              {incident.route_no ? <span className="meta"> ({incident.route_no})</span> : null}
            </p>
            <dl className="network-facts">
              {disruption?.section_from || disruption?.section_to ? (
                <div>
                  <dt>Affected section</dt>
                  <dd>
                    {disruption.section_from && disruption.section_from === disruption.section_to
                      ? `Near ${disruption.section_from}`
                      : `${disruption.section_from ?? 'junction'} to ${disruption.section_to ?? 'junction'}`}
                    {disruption.section_km ? ` · ${Math.round(Number(disruption.section_km))} km between junctions` : ''}
                  </dd>
                </div>
              ) : null}
              {isTrue(incident.no_alternative) ? (
                <div>
                  <dt>Way round</dt>
                  <dd>
                    No alternative on the key freight network
                    {incident.localities_cut ? (incident.network_mode === 'rail' ? `: cuts the freight rail link to ${incident.localities_cut}` : `: cuts off ${incident.localities_cut}`) : ''}
                  </dd>
                </div>
              ) : (
                <div>
                  <dt>Detour</dt>
                  <dd>
                    {Number(incident.detour_extra_km) < 5
                      ? 'Alternative route available with little extra distance'
                      : `${Math.round(Number(incident.detour_extra_km))} km extra${incident.detour_via ? ` via ${incident.detour_via}` : ''}`}
                  </dd>
                </div>
              )}
            </dl>
            <p className="meta" style={{ margin: 0 }}>
              Detours run along key freight routes only, so they are an upper bound on the real diversion.
            </p>
          </div>
        ) : null}

        <div className="card card-rule">
          <h3>If this fails</h3>
          {byHop.length === 0 ? (
            <p className="alert-copy">No other monitored asset depends on this one. Impact is limited to the {formatPeople(incident.people_served)} people it serves directly.</p>
          ) : (
            byHop.map((group) => (
              <div key={String(group[0].hop)} className="impact-group">
                <span className="meta">{Number(group[0].hop) === 1 ? 'Directly supplied' : 'Then, through those'}</span>
                <ul className="impact-list">
                  {group.map((d) => (
                    <li key={String(d.downstream_asset_id)}>
                      <SectorBadge sector={String(d.sector)} />
                      <span className="impact-name">
                        {d.asset_name}
                        <span className="meta"> · {d.dependency_type}</span>
                      </span>
                      <span className="num">{formatPeople(d.people_served)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))
          )}
        </div>

        <div className="grid-2">
          <div className="card">
            <span className="meta">Recommended first action</span>
            <h3 style={{ marginTop: 8 }}>{incident.recommended_action}</h3>
            <p style={{ color: 'var(--ioc-muted)', marginBottom: 0 }}>Responsible operator: {incident.operator_name}.</p>
          </div>
          <div className="card">
            <span className="meta">Decision record</span>
            <h3 style={{ marginTop: 8 }}>{decided ? 'Decision recorded' : 'Officer judgement required'}</h3>
            <p style={{ color: 'var(--ioc-muted)', marginBottom: 0 }}>
              {decided
                ? `${incident.decided_by ?? 'An officer'} recorded this at ${formatTime(incident.decided_ts)}. A new decision is added to the record, never overwritten.`
                : 'Your identity, time, evidence viewed and disposition are retained in the governed audit table.'}
            </p>
          </div>
        </div>

        <label className="field" style={{ display: 'grid', gap: 6 }}>
          <span className="meta">Officer notes (optional)</span>
          <textarea className="textarea" maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Context for the operator, the crew or the next watch" />
        </label>

        <div className="trust-note">
          <Icon.Shield />
          <span>Transparent likelihood × consequence model over synthetic telemetry. Decision support only: no action is taken without an officer’s decision.</span>
        </div>
        {error ? (
          <p className="inline-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>

      <div className="dialog-actions">
        <span className="meta">Recorded under your Unity Catalog identity</span>
        <button className="btn btn-secondary" disabled={submitting != null} onClick={() => void decide('monitor')}>
          {submitting === 'monitor' ? 'Recording…' : 'Continue monitoring'}
        </button>
        <button className="btn btn-secondary" disabled={submitting != null} onClick={() => void decide('notify')}>
          {submitting === 'notify' ? 'Recording…' : 'Notify operator'}
        </button>
        <button className="btn btn-primary" disabled={submitting != null} onClick={() => void decide('dispatch')}>
          {submitting === 'dispatch' ? 'Recording…' : 'Dispatch crew'}
        </button>
      </div>
    </>
  );
}

/** 24-hour line of the triggering metric against its warning and alarm limits (zero-based where sensible). */
function TelemetryChart({ rows }: { rows: TelemetryRow[] }) {
  const W = 640, H = 170, L = 44, R = 12, T = 12, B = 24;
  const pts = rows.map((r) => ({ t: toDate(r.event_ts)?.getTime() ?? 0, v: Number(r.value) })).filter((p) => p.t);
  const warn = Number(rows[0].warn_limit), alarm = Number(rows[0].alarm_limit), unit = String(rows[0].unit);
  const values = [...pts.map((p) => p.v), warn, alarm];
  // fit the range to the readings and both limits (a temperature line needs no zero baseline;
  // both limit lines always stay in frame), keeping zero when readings sit near it
  const vMin = Math.min(...values), vMax = Math.max(...values), pad = (vMax - vMin) * 0.12 || 1;
  const lo = vMin - pad <= 0 || vMin < (vMax - vMin) * 0.25 ? Math.min(0, vMin) : vMin - pad, hi = vMax + pad;
  const t0 = pts[0].t, t1 = pts[pts.length - 1].t;
  const x = (t: number) => L + ((t - t0) / Math.max(1, t1 - t0)) * (W - L - R);
  const y = (v: number) => T + (1 - (v - lo) / Math.max(1e-9, hi - lo)) * (H - T - B);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.t).toFixed(1)} ${y(p.v).toFixed(1)}`).join(' ');
  const last = pts[pts.length - 1];
  const ticks = [t0, t0 + (t1 - t0) / 2, t1];
  return (
    <svg className="telemetry-chart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`${rows[0].metric_label} over 24 hours: now ${formatMetric(last.v, unit)}, warning ${formatMetric(warn, unit)}, alarm ${formatMetric(alarm, unit)}`}>
      <line x1={L} x2={W - R} y1={y(alarm)} y2={y(alarm)} className="limit alarm" />
      <text x={L - 6} y={y(alarm) + 4} className="axis" textAnchor="end">alarm</text>
      <line x1={L} x2={W - R} y1={y(warn)} y2={y(warn)} className="limit warn" />
      <text x={L - 6} y={y(warn) + 4} className="axis" textAnchor="end">warn</text>
      <line x1={L} x2={W - R} y1={y(lo)} y2={y(lo)} className="baseline" />
      <path d={line} className="series" />
      <circle cx={x(last.t)} cy={y(last.v)} r={4} className="series-end" />
      <text x={Math.min(W - R - 4, x(last.t) - 6)} y={y(last.v) - 10} className="value-label" textAnchor="end">{formatMetric(last.v, unit)}</text>
      {ticks.map((t, i) => (
        <text key={t} x={x(t)} y={H - 6} className="axis" textAnchor={i === 0 ? 'start' : i === 2 ? 'end' : 'middle'}>
          {formatHour(new Date(t))}
        </text>
      ))}
    </svg>
  );
}
