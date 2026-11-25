import { countPhrase, formatMinutes, formatShortDateTime, formatTime } from '../lib/format';
import { DISPOSITION_LABELS } from '../lib/model';
import type { DecisionRow, HazardRow, IncidentRow, OpsStatusRow } from '../lib/rows';
import { feedHealth } from '../lib/status';
import { SectorBadge } from './icons';
import { EmptyState, ErrorState, Icon, Skeleton } from './primitives';

interface Props {
  now: Date;
  incidents: IncidentRow[] | null;
  hazards: HazardRow[] | null;
  ops: OpsStatusRow | null;
  decisions: DecisionRow[] | null;
  decisionsLoading: boolean;
  decisionsError: string | null;
}

export function Handover({ now, incidents, hazards, ops, decisions, decisionsLoading, decisionsError }: Props) {
  const open = (incidents ?? []).filter((a) => a.status === 'open');
  const extremeOpen = open.filter((a) => a.risk_rating === 'extreme').length;
  const dispatched = (incidents ?? []).filter((a) => a.status === 'dispatched').length;
  const notified = (incidents ?? []).filter((a) => a.status === 'notified').length;
  const oldest = open.reduce((max, a) => Math.max(max, Number(a.age_minutes) || 0), 0);
  const endingSoon = (hazards ?? []).filter((h) => Number(h.hours_remaining) <= 12).length;
  const health = feedHealth(ops);
  const ready = incidents != null && ops != null;

  const checks = [
    {
      ok: extremeOpen === 0,
      title: open.length === 0 ? 'No incidents awaiting a decision' : `${countPhrase(open.length, 'incident')} awaiting a decision`,
      meta:
        open.length === 0
          ? 'Every incident has a recorded decision.'
          : `${extremeOpen ? `${extremeOpen} extreme. ` : ''}Oldest open incident: ${oldest < 120 ? `${oldest} minute${oldest === 1 ? '' : 's'}` : formatMinutes(oldest)}.`,
    },
    {
      ok: true,
      title: dispatched === 0 ? 'No crews dispatched' : `${countPhrase(dispatched, 'crew')} dispatched`,
      meta: notified ? `${notified} operator${notified === 1 ? '' : 's'} notified to act.` : 'No operators awaiting action.',
    },
    {
      ok: !endingSoon,
      title: hazards ? `${countPhrase(hazards.length, 'active warning')}` : 'Checking warnings',
      meta: hazards ? (endingSoon ? `${endingSoon} end within 12 hours - confirm stand-down with operators.` : 'None ending this watch.') : ' ',
    },
    {
      ok: health.current,
      title: health.current ? 'Telemetry feeds current' : 'Telemetry is not current',
      meta: ops ? `Last ingest ${formatTime(ops.latest_ingest_ts)} · ${ops.sensors_reporting} of ${ops.sensors_total} sensors reporting.` : 'Checking feed status…',
    },
  ];

  return (
    <section className="section" id="assurance" aria-labelledby="handover-heading">
      <div className="container assurance">
        <div>
          <p className="eyebrow">Shift handover</p>
          <h2 id="handover-heading">{open.length === 0 && ready ? 'Queue clear for the next watch.' : 'Queue ready for the next watch.'}</h2>
          <p className="lead">
            Outstanding incidents, crews, operator actions and warnings are current as of <span className="num">{formatTime(now)}</span>.
          </p>

          <div className="decision-log" id="audit-log">
            <h3>Decision record</h3>
            <p className="meta" style={{ marginTop: 0 }}>
              Every disposition is written to the governed audit table with the officer’s Unity Catalog identity, time and evidence viewed.
            </p>
            {decisionsError && !decisions ? (
              <ErrorState title="Decision record unavailable" message={decisionsError} />
            ) : decisionsLoading ? (
              <Skeleton height={120} />
            ) : !decisions || decisions.length === 0 ? (
              <EmptyState title="No decisions recorded yet">Review an incident and dispatch a crew, notify the operator or keep monitoring. The decision appears here.</EmptyState>
            ) : (
              <div role="list">
                {decisions.slice(0, 6).map((d) => (
                  <div className="decision" role="listitem" key={String(d.review_id)}>
                    <span className={d.disposition === 'dispatch' ? 'pill success' : 'pill'}>{DISPOSITION_LABELS[String(d.disposition)] ?? d.disposition}</span>
                    <div>
                      {d.sector ? <SectorBadge sector={String(d.sector)} /> : null} <strong>{d.asset_name ?? d.incident_id}</strong>
                      {d.incident_title ? <span className="alert-copy"> · {d.incident_title}</span> : null}
                      <div className="who">{d.officer_name}</div>
                    </div>
                    <span className="meta">{formatShortDateTime(d.reviewed_ts)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="checklist">
          {checks.map((c) => (
            <div className={`check ${c.ok ? 'ok' : 'attention'}`} key={c.title}>
              {c.ok ? <Icon.Check /> : <Icon.Attention />}
              <div>
                {ready ? <strong>{c.title}</strong> : <Skeleton width={180} height={18} />}
                <div className="meta">{ready ? c.meta : ' '}</div>
              </div>
            </div>
          ))}
          <div className="check">
            <Icon.Shield />
            <div>
              <strong>Decision support only</strong>
              <div className="meta">Scores come from a transparent likelihood × consequence model. An officer’s judgement decides every action.</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
