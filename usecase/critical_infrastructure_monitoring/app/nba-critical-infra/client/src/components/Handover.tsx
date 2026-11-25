import { countPhrase, formatMinutes, formatPct, formatShortDateTime, formatTime } from '../lib/format';
import type { AlertRow, DecisionRow, OpsStatusRow } from '../lib/rows';
import { feedHealth } from '../lib/status';
import { EmptyState, ErrorState, Icon, Skeleton } from './primitives';

interface Props {
  now: Date;
  alerts: AlertRow[] | null;
  ops: OpsStatusRow | null;
  decisions: DecisionRow[] | null;
  decisionsLoading: boolean;
  decisionsError: string | null;
}

export function Handover({ now, alerts, ops, decisions, decisionsLoading, decisionsError }: Props) {
  const open = (alerts ?? []).filter((a) => a.status === 'open');
  const routed = (alerts ?? []).filter((a) => a.status === 'routed').length;
  const monitoring = (alerts ?? []).filter((a) => a.status === 'monitoring').length;
  const oldest = open.reduce((max, a) => Math.max(max, Number(a.age_minutes) || 0), 0);
  const health = feedHealth(ops);
  const ready = alerts != null && ops != null;

  const checks = [
    {
      ok: open.length === 0,
      title: open.length === 0 ? 'No alerts unassigned' : `${countPhrase(open.length, 'alert')} unassigned`,
      meta: open.length === 0 ? 'Every alert has a recorded decision.' : `Oldest open alert: ${oldest < 120 ? `${oldest} minute${oldest === 1 ? '' : 's'}` : formatMinutes(oldest)} in the queue.`,
    },
    {
      ok: true,
      title: routed === 0 ? 'No field routes active' : `${countPhrase(routed, 'field route')} active`,
      meta: monitoring ? `${monitoring} retained for continued monitoring.` : 'No alerts retained for monitoring.',
    },
    {
      ok: health.current,
      title: health.current ? 'Feeds and integrations healthy' : 'Feed data is not current',
      meta: ops ? `Last ingest ${formatTime(ops.latest_ingest_ts)} · identity resolution ${formatPct(ops.identity_resolution_rate)}.` : 'Checking feed status…',
    },
  ];

  return (
    <section className="section" id="assurance" aria-labelledby="handover-heading">
      <div className="container assurance">
        <div>
          <p className="eyebrow">Shift handover</p>
          <h2 id="handover-heading">{open.length === 0 && ready ? 'Queue clear for the next watch.' : 'Queue ready for the next watch.'}</h2>
          <p className="lead">
            Outstanding alerts, active routes and officer decisions are current as of <span className="num">{formatTime(now)}</span>.
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
              <EmptyState title="No decisions recorded yet">Review an alert and route it or retain it for monitoring - the decision appears here.</EmptyState>
            ) : (
              <div role="list">
                {decisions.slice(0, 6).map((d) => (
                  <div className="decision" role="listitem" key={String(d.review_id)}>
                    <span className={d.disposition === 'route' ? 'pill success' : 'pill'}>{d.disposition === 'route' ? 'Routed' : 'Monitoring'}</span>
                    <div>
                      <strong className="num">{d.registration_plate}</strong> {d.alert_title ? <span className="alert-copy">· {d.alert_title}</span> : null}
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
              <div className="meta">Scores are a transparent rules engine. An officer’s judgement decides every field action.</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
