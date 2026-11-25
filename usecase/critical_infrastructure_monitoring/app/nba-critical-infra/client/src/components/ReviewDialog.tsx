import { sql } from '@databricks/appkit-ui/js';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useAnalyticsQuery, useScope } from '../lib/data';
import { FACTOR_LABELS, formatAge, formatShortDateTime, formatTime, RISK_TYPE_LABELS, SOURCE_LABELS } from '../lib/format';
import { contributions, severityFor } from '../lib/model';
import type { ReviewTarget } from '../lib/rows';
import { EmptyState, ErrorState, Icon, Skeleton } from './primitives';

const NEXT_STEP: Record<string, { title: string; copy: string }> = {
  fatigue: {
    title: 'Validate against field context',
    copy: 'Confirm location, available resources and any active work-diary exemptions before routing.',
  },
  roadworthiness: {
    title: 'Check open defect notices',
    copy: 'Confirm outstanding defect notices and the next scheduled inspection before routing an intercept.',
  },
  mass: {
    title: 'Confirm at the next weigh station',
    copy: 'Check permitted mass exemptions and the next static weigh site on the corridor before routing.',
  },
  route: {
    title: 'Check corridor permits',
    copy: 'Confirm route permits and any notified detours before routing.',
  },
};

interface Props {
  target: ReviewTarget | null;
  alertThreshold: number;
  now: Date;
  onClose: () => void;
  onDecided: (message: string) => void;
}

export function ReviewDialog({ target, alertThreshold, now, onClose, onDecided }: Props) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (target && !dialog.open) dialog.showModal();
    if (!target && dialog.open) dialog.close();
  }, [target]);

  return (
    <dialog
      ref={ref}
      aria-labelledby="review-title"
      onClose={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      {target ? <ReviewBody key={`${target.assetId}:${target.alert?.alertId ?? ''}`} target={target} alertThreshold={alertThreshold} now={now} onClose={onClose} onDecided={onDecided} /> : null}
    </dialog>
  );
}

function ReviewBody({ target, alertThreshold, now, onClose, onDecided }: Props & { target: ReviewTarget }) {
  const { catalog, schema, refresh } = useScope();
  const params = useMemo(
    () => ({ catalog: sql.string(catalog), schema: sql.string(schema), refresh: sql.string(refresh), asset_id: sql.bigint(target.assetId) }),
    [catalog, schema, refresh, target.assetId],
  );
  const movement = useAnalyticsQuery('entity_movement', params);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState<'route' | 'monitor' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const parts = contributions(target.riskType, target.scores);
  const severity = severityFor(target.score);
  const step = NEXT_STEP[target.riskType] ?? NEXT_STEP.fatigue;
  const alert = target.alert;
  const decided = alert && alert.status !== 'open';

  async function decide(disposition: 'route' | 'monitor') {
    if (!alert) return;
    setSubmitting(disposition);
    setError(null);
    const evidenceViewed = ['risk_score', 'contributing_factors', ...(movement.data && movement.data.length ? ['recent_movement'] : [])];
    try {
      const response = await fetch('/api/reviews', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alertId: alert.alertId, disposition, evidenceViewed, notes }),
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? `Decision was not recorded (${response.status})`);
      }
      onDecided(
        disposition === 'route'
          ? `${target.plate} routed to the field queue. Decision recorded.`
          : `${target.plate} retained for continued monitoring. Decision recorded.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Decision was not recorded');
      setSubmitting(null);
    }
  }

  return (
    <>
      <div className="dialog-head">
        <div>
          <p className="eyebrow">{alert ? 'Alert review' : 'Entity review'}</p>
          <h2 id="review-title" tabIndex={-1} autoFocus>
            <span className="num">{target.plate}</span> · {RISK_TYPE_LABELS[target.riskType] ?? target.riskType} risk
          </h2>
          <p className="alert-copy">
            {target.operator}
            {target.lastSeenLocation ? ` · last seen ${target.lastSeenLocation}, ${formatAge(target.lastSeenTs, now)} ago` : ''}
          </p>
        </div>
        <button className="btn btn-ghost" onClick={onClose} aria-label="Close review">
          Close
        </button>
      </div>

      <div className="dialog-body stack">
        <div className="row-between">
          <div>
            <span className="meta">Risk score</span>
            <div className={`stat-num num risk-score ${severity}`} style={{ marginTop: 4 }}>
              {target.score}
            </div>
          </div>
          {alert ? (
            decided ? (
              <span className={alert.status === 'routed' ? 'pill success' : 'pill'}>
                <span className={`status-dot${alert.status === 'routed' ? '' : ' muted'}`} />
                {alert.status === 'routed' ? 'Routed to field' : 'Monitoring'} · {formatTime(alert.decidedTs)}
              </span>
            ) : (
              <span className={`pill ${severity === 'critical' ? 'danger' : 'warn'}`}>
                <span className={`status-dot ${severity === 'critical' ? 'danger' : 'warn'}`} />
                Open · priority {alert.priority}
              </span>
            )
          ) : (
            <span className="pill">
              <span className="status-dot muted" />
              Below alert threshold ({alertThreshold})
            </span>
          )}
        </div>

        <div className="card card-rule">
          <h3>Why this was flagged</h3>
          <p className="lead">Each bar is a normalised factor; the points are its weighted contribution to the score.</p>
          <div className="stack" style={{ marginTop: 20 }}>
            {parts.map((p, i) => (
              <div className={`factor${i === 0 ? ' primary' : ''}`} key={p.factor}>
                <span>
                  {FACTOR_LABELS[p.factor]}
                  <div className="weight">
                    weight {Math.round(p.weight * 100)}% · <span className="num">{p.points.toFixed(0)}</span> pts
                  </div>
                </span>
                <div className="factor-bar" role="meter" aria-valuemin={0} aria-valuemax={1} aria-valuenow={Number(p.value.toFixed(2))} aria-label={FACTOR_LABELS[p.factor]}>
                  <div className="factor-fill" style={{ width: `${Math.round(p.value * 100)}%` }} />
                </div>
                <span className="num">{p.value.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card card-rule">
          <h3>Recent movement</h3>
          {movement.error ? (
            <ErrorState title="Movement history unavailable" message={movement.error} />
          ) : movement.loading || !movement.data ? (
            <div className="stack" style={{ gap: 8, marginTop: 12 }} aria-busy="true">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} height={20} />
              ))}
            </div>
          ) : movement.data.length === 0 ? (
            <EmptyState title="No recent sightings" />
          ) : (
            <div className="movement" style={{ marginTop: 8 }}>
              {movement.data.map((m) => (
                <div className="movement-row" key={String(m.sighting_id)}>
                  <span className="num">{formatShortDateTime(m.event_ts)}</span>
                  <span>
                    {m.road_name}, {m.locality} {m.state}
                    <div className="meta">
                      {SOURCE_LABELS[String(m.source_type)] ?? m.source_type} · {Number(m.speed_kph).toFixed(0)} km/h
                      {m.resolution_method !== 'exact' ? ` · plate read "${m.sighted_plate_raw}" resolved (${m.resolution_method})` : ''}
                    </div>
                  </span>
                  <span className="flags">
                    {m.is_rest_window ? <span className="tag">Rest window</span> : m.is_night ? <span className="tag">Night</span> : null}
                    {Number(m.mass_ratio) > 1.05 ? <span className="tag">Mass {Math.round(Number(m.mass_ratio) * 100)}%</span> : null}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="grid-2">
          <div className="card">
            <span className="meta">Recommended next step</span>
            <h3 style={{ marginTop: 8 }}>{alert ? step.title : 'Continue monitoring'}</h3>
            <p style={{ color: 'var(--ioc-muted)', marginBottom: 0 }}>{alert ? step.copy : 'This entity is below the alert threshold. It stays on the register for awareness only.'}</p>
          </div>
          <div className="card">
            <span className="meta">Decision record</span>
            <h3 style={{ marginTop: 8 }}>{decided ? 'Decision recorded' : 'Officer judgement required'}</h3>
            <p style={{ color: 'var(--ioc-muted)', marginBottom: 0 }}>
              {decided
                ? `${alert?.decidedBy ?? 'An officer'} recorded this at ${formatTime(alert?.decidedTs)}. A new decision is added to the record, never overwritten.`
                : 'Your identity, time, evidence viewed and disposition will be retained in the governed audit table.'}
            </p>
          </div>
        </div>

        {alert ? (
          <label className="field" style={{ display: 'grid', gap: 6 }}>
            <span className="meta">Officer notes (optional)</span>
            <textarea className="textarea" maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Context for the field team or the next watch" />
          </label>
        ) : null}

        <div className="trust-note">
          <Icon.Shield />
          <span>Transparent rules engine over synthetic telemetry. Decision support only - the score does not direct enforcement without an officer’s decision.</span>
        </div>
        {error ? (
          <p className="inline-error" role="alert">
            {error}
          </p>
        ) : null}
      </div>

      <div className="dialog-actions">
        {alert ? (
          <>
            <span className="meta">Recorded under your Unity Catalog identity</span>
            <button className="btn btn-secondary" disabled={submitting != null} onClick={() => void decide('monitor')}>
              {submitting === 'monitor' ? 'Recording…' : 'Continue monitoring'}
            </button>
            <button className="btn btn-primary" disabled={submitting != null} onClick={() => void decide('route')}>
              {submitting === 'route' ? 'Recording…' : 'Route to field queue'}
            </button>
          </>
        ) : (
          <button className="btn btn-secondary" onClick={onClose}>
            Done
          </button>
        )}
      </div>
    </>
  );
}
