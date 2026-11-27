import { useContext, useMemo, useState } from 'react';
import { DataVersionContext, useBaseParams, useDecisionsContext, useRows } from '../lib/data';
import { day, money } from '../lib/format';
import type { PipelineStatus } from '../lib/types';
import { Empty, ErrorNotice, PanelHead, Skeleton, SkeletonRows } from './primitives';

interface Week {
  week: string;
  invoices_paid: number;
  late_current: number;
  late_2027: number;
  interest_current: number;
  value_paid: number;
  median_business_days_to_pay: number;
  pct_late_current: number;
  pct_late_2027: number;
}
interface Accuracy {
  field: string;
  label: string;
  scanned: boolean;
  fields: number;
  matches_truth: number;
  routed_to_review: number;
  mean_routing_confidence: number;
  reviewed: number;
  corrected_by_reviewer: number;
  wrong_but_not_routed: number;
  accuracy_pct: number;
}
interface Detection {
  defect: string;
  documents: number;
  caught: number;
  false_alarms: number;
  to_exception: number;
  to_review: number;
  to_ready: number;
}

const DEFECT_LABELS: Record<string, string> = {
  none: 'Clean invoices (none should be sent back)',
  no_receipt: 'Delivery not acknowledged',
  missing_po: 'No purchase order quoted',
  wrong_po: 'Purchase order does not match',
  gst_error: 'GST miscalculated',
  invalid_abn: 'ABN fails check digits',
  abn_mismatch: 'ABN differs from vendor master',
  wrong_recipient: 'Addressed to another entity',
  missing_recipient: 'Recipient not shown',
  over_po_value: 'Exceeds remaining order value',
  duplicate: 'Duplicate of an earlier invoice',
  not_tax_invoice: 'Not identified as a tax invoice',
};

export function Performance({ status }: { status: PipelineStatus | null }) {
  const base = useBaseParams();
  const weeks = useRows<Week>('readiness', base);
  const acc = useRows<Accuracy>('accuracy', base);
  const det = useRows<Detection>('detection', base);
  const decisions = useDecisionsContext();
  const { bump: retry } = useContext(DataVersionContext);

  const recent = (weeks.data ?? []).slice(-4);
  const paid = recent.reduce((s, w) => s + w.invoices_paid, 0);
  const late2027 = recent.reduce((s, w) => s + w.late_2027, 0);
  const lateNow = recent.reduce((s, w) => s + w.late_current, 0);

  const fields = useMemo(() => {
    const by = new Map<string, { label: string; digital?: Accuracy; scanned?: Accuracy }>();
    for (const raw of acc.data ?? []) {
      // 'fields' is a count here; the row normaliser keeps *fields columns as strings.
      const r = { ...raw, fields: Number(raw.fields) };
      const e = by.get(r.field) ?? { label: r.label };
      if (r.scanned) e.scanned = r;
      else e.digital = r;
      by.set(r.field, e);
    }
    return [...by.entries()]
      .map(([field, e]) => {
        const total = (e.digital?.fields ?? 0) + (e.scanned?.fields ?? 0);
        const missed = (e.digital?.wrong_but_not_routed ?? 0) + (e.scanned?.wrong_but_not_routed ?? 0);
        const routed = (e.digital?.routed_to_review ?? 0) + (e.scanned?.routed_to_review ?? 0);
        return { field, ...e, total, missed, routed };
      })
      .sort((a, b) => b.missed - a.missed || b.routed - a.routed);
  }, [acc.data]);
  const missedTotal = fields.reduce((s, f) => s + f.missed, 0);
  const wb = decisions.decisions.filter((d) => d.decision === 'accepted' || d.decision === 'returned');
  const corrected = wb.reduce((s, d) => s + d.fields_corrected, 0);

  return (
    <div className="content">
      <div className="page-head">
        <div>
          <h1>Performance and readiness</h1>
          <p className="page-intro">
            How much work reaches a person, how often the machine is wrong without saying so, and whether today&apos;s
            handling times would meet the 10 business day terms from 1 January 2027. Measured on the synthetic corpus
            and its simulated history; none of it is a claim about real documents.
          </p>
        </div>
      </div>

      <div className="summary-grid">
        <div className="card summary-card">
          <span className="summary-label">Straight through</span>
          {status ? (
            <strong className="summary-value">{status.straight_through_pct ?? '-'}%</strong>
          ) : (
            <Skeleton width={70} height={28} />
          )}
          <span className="summary-foot">of assessed invoices needed no person before accepting</span>
        </div>
        <div className="card summary-card">
          <span className="summary-label">Wrong and not held</span>
          {acc.loading ? (
            <Skeleton width={70} height={28} />
          ) : (
            <strong className={`summary-value${missedTotal ? ' alert' : ''}`}>{missedTotal}</strong>
          )}
          <span className="summary-foot">
            extracted values that disagree with ground truth but passed the confidence gate
          </span>
        </div>
        <div className="card summary-card">
          <span className="summary-label">Late under 2027 terms</span>
          {weeks.loading ? (
            <Skeleton width={70} height={28} />
          ) : (
            <strong className={`summary-value${late2027 ? ' alert' : ''}`}>
              {paid ? Math.round((100 * late2027) / paid) : 0}%
            </strong>
          )}
          <span className="summary-foot">
            of the last four weeks&apos; payments, against {paid ? Math.round((100 * lateNow) / paid) : 0}% under
            today&apos;s terms (simulated)
          </span>
        </div>
        <div className="card summary-card">
          <span className="summary-label">Reviewer corrections</span>
          <strong className="summary-value">{corrected}</strong>
          <span className="summary-foot">
            fields changed across {wb.length} workbench {wb.length === 1 ? 'decision' : 'decisions'}
          </span>
        </div>
      </div>

      <section className="card" style={{ marginBottom: 'var(--space-6)' }} aria-labelledby="readiness-title">
        <PanelHead
          id="readiness-title"
          title="Paid late, by week"
          copy="Share of invoices paid each week that missed the pay-by date. Simulated AP history. Peppol e-invoices have 5 calendar days today and gain time under the 10 business day terms; every other invoice loses it."
        />
        {weeks.error && <ErrorNotice message={weeks.error} onRetry={retry} />}
        {weeks.loading ? (
          <div className="chart">
            <Skeleton height={240} />
          </div>
        ) : (
          <ReadinessChart weeks={weeks.data ?? []} />
        )}
      </section>

      <div className="perf-grid">
        <section className="card" aria-labelledby="accuracy-title">
          <PanelHead
            id="accuracy-title"
            title="Extraction by field"
            copy="Agreement with ground truth, born-digital and scanned, and how often each field was held for a person. Wrong values that were not held are the risk."
          />
          {acc.loading ? (
            <SkeletonRows rows={8} height={20} />
          ) : !fields.length ? (
            <Empty title="No extraction measured yet" />
          ) : (
            <div className="table-wrap">
              <table className="data numeric">
                <thead>
                  <tr>
                    <th scope="col">Field</th>
                    <th scope="col" className="num">
                      Born-digital
                    </th>
                    <th scope="col" className="num">
                      Scanned
                    </th>
                    <th scope="col" className="num">
                      Held for review
                    </th>
                    <th scope="col" className="num">
                      Wrong, not held
                    </th>
                    <th scope="col" className="num">
                      Corrected by reviewers
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {fields.map((f) => (
                    <tr key={f.field}>
                      <td>{f.label}</td>
                      <td className="num mono">{f.digital ? `${f.digital.accuracy_pct}%` : '-'}</td>
                      <td className="num mono">{f.scanned ? `${f.scanned.accuracy_pct}%` : '-'}</td>
                      <td className="num mono">{f.total ? `${Math.round((100 * f.routed) / f.total)}%` : '-'}</td>
                      <td className="num mono" style={f.missed ? { color: 'var(--danger)' } : undefined}>
                        {f.missed}
                      </td>
                      <td className="num mono">
                        {(f.digital?.corrected_by_reviewer ?? 0) + (f.scanned?.corrected_by_reviewer ?? 0)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="panel-foot">
            <span>
              Reviewer corrections reach this table when the feedback job copies decisions into Unity Catalog.
            </span>
            {status && <span>Assessed {day(status.assessed_at, true)}</span>}
          </div>
        </section>
        <section className="card" aria-labelledby="detection-title">
          <PanelHead
            id="detection-title"
            title="Did the checks catch it?"
            copy="Defects injected into the synthetic corpus, and where each invoice was routed."
          />
          {det.loading ? (
            <SkeletonRows rows={6} height={20} />
          ) : (
            <div className="table-wrap">
              <table className="data numeric">
                <thead>
                  <tr>
                    <th scope="col">Injected defect</th>
                    <th scope="col" className="num">
                      Caught
                    </th>
                    <th scope="col" className="num">
                      Reached ready
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(det.data ?? []).map((r) => (
                    <tr key={r.defect}>
                      <td>{DEFECT_LABELS[r.defect] ?? r.defect}</td>
                      <td className="num mono">
                        {r.defect === 'none' ? `${r.false_alarms} sent back` : `${r.caught} of ${r.documents}`}
                      </td>
                      <td
                        className="num mono"
                        title={
                          r.defect === 'no_receipt' && r.to_ready
                            ? 'Their delivery receipt arrived later, so the clock started and they became ready'
                            : undefined
                        }
                      >
                        {r.to_ready}
                        {r.defect === 'no_receipt' && r.to_ready > 0 && <div className="doc-meta">receipted later</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function ReadinessChart({ weeks }: { weeks: Week[] }) {
  const [hover, setHover] = useState<{ i: number; series: 'current' | '2027' } | null>(null);
  const [table, setTable] = useState(false);
  if (!weeks.length) return <Empty title="No payments in the history yet" />;
  const W = 640,
    H = 260,
    L = 40,
    R = 12,
    T = 18,
    B = 34;
  const max = Math.max(20, ...weeks.map((w) => Math.max(w.pct_late_current, w.pct_late_2027)));
  const top = Math.ceil(max / 10) * 10;
  const band = (W - L - R) / weeks.length;
  const bw = Math.min(26, (band - 18) / 2);
  const y = (v: number) => T + (H - T - B) * (1 - v / top);
  const ticks = [0, top / 2, top];
  const last = weeks.length - 1;
  const hw = hover ? weeks[hover.i] : null;

  const bar = (x: number, v: number) => {
    const h = Math.max(0, y(0) - y(v));
    const r = Math.min(4, h);
    // Rounded data end, square baseline.
    return `M${x},${y(0)} V${y(0) - h + r} Q${x},${y(0) - h} ${x + r},${y(0) - h} H${x + bw - r} Q${x + bw},${y(0) - h} ${x + bw},${y(0) - h + r} V${y(0)} Z`;
  };

  return (
    <div className="chart">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div className="legend" style={{ marginTop: 0 }}>
          <span>
            <i style={{ background: 'var(--series-current)' }} />
            Today&apos;s terms (20 calendar days)
          </span>
          <span>
            <i style={{ background: 'var(--series-2027)' }} />
            2027 terms (10 business days)
          </span>
        </div>
        <button className="button small" onClick={() => setTable((t) => !t)} aria-pressed={table}>
          {table ? 'Show chart' : 'Show table'}
        </button>
      </div>
      {table ? (
        <div className="table-wrap" style={{ marginTop: 12 }}>
          <table className="data numeric">
            <thead>
              <tr>
                <th scope="col">Week of</th>
                <th scope="col" className="num">
                  Paid
                </th>
                <th scope="col" className="num">
                  Late today
                </th>
                <th scope="col" className="num">
                  Late in 2027
                </th>
                <th scope="col" className="num">
                  Median business days
                </th>
                <th scope="col" className="num">
                  Interest
                </th>
              </tr>
            </thead>
            <tbody>
              {weeks.map((w) => (
                <tr key={w.week}>
                  <td>{day(w.week)}</td>
                  <td className="num mono">{w.invoices_paid}</td>
                  <td className="num mono">{w.pct_late_current}%</td>
                  <td className="num mono">{w.pct_late_2027}%</td>
                  <td className="num mono">{w.median_business_days_to_pay}</td>
                  <td className="num mono">{money(w.interest_current)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          <svg
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            aria-label="Share of invoices paid late each week, under today's terms and under the 2027 terms"
            style={{ marginTop: 12 }}
            onMouseLeave={() => setHover(null)}
          >
            {ticks.map((t) => (
              <g key={t}>
                <line className={t === 0 ? 'axis' : 'grid'} x1={L} x2={W - R} y1={y(t)} y2={y(t)} />
                <text x={L - 8} y={y(t) + 4} textAnchor="end">
                  {t}%
                </text>
              </g>
            ))}
            {weeks.map((w, i) => {
              const x0 = L + i * band + (band - bw * 2 - 2) / 2;
              return (
                <g key={w.week}>
                  {hover?.i === i && (
                    <rect className="crosshair" x={L + i * band + 2} y={T} width={band - 4} height={y(0) - T} rx={6} />
                  )}
                  <path className="bar-current bar-gap" d={bar(x0, w.pct_late_current)} />
                  <path className="bar-2027 bar-gap" d={bar(x0 + bw + 2, w.pct_late_2027)} />
                  {i === last && (
                    <>
                      <text className="value-label" x={x0 + bw / 2} y={y(w.pct_late_current) - 6} textAnchor="middle">
                        {Math.round(w.pct_late_current)}%
                      </text>
                      <text
                        className="value-label"
                        x={x0 + bw * 1.5 + 2}
                        y={y(w.pct_late_2027) - 6}
                        textAnchor="middle"
                      >
                        {Math.round(w.pct_late_2027)}%
                      </text>
                    </>
                  )}
                  <text x={L + i * band + band / 2} y={H - 12} textAnchor="middle">
                    {day(w.week)}
                  </text>
                  <rect
                    className="bar-hit"
                    x={L + i * band}
                    y={T}
                    width={band}
                    height={y(0) - T}
                    tabIndex={0}
                    aria-label={`Week of ${day(w.week)}: ${w.pct_late_current}% late under today's terms, ${w.pct_late_2027}% under the 2027 terms, ${w.invoices_paid} paid`}
                    onMouseEnter={() => setHover({ i, series: '2027' })}
                    onFocus={() => setHover({ i, series: '2027' })}
                    onBlur={() => setHover(null)}
                  />
                </g>
              );
            })}
          </svg>
          <p className="chart-readout" aria-live="polite">
            {hw ? (
              <>
                Week of {day(hw.week)}: <strong className="mono">{hw.invoices_paid}</strong> paid,{' '}
                <strong className="mono">{hw.pct_late_current}%</strong> late today,{' '}
                <strong className="mono">{hw.pct_late_2027}%</strong> late under 2027 terms; median{' '}
                {hw.median_business_days_to_pay} business days from clock start to payment.
              </>
            ) : (
              <span className="muted">Hover or focus a week for its detail.</span>
            )}
          </p>
        </>
      )}
    </div>
  );
}
