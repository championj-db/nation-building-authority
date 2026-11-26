import { useEffect, useMemo, useState } from 'react';
import { precision, reasonLabel } from '../../../shared/contracts';
import type { PipelineSummary } from '../App';
import type { CaseStates } from '../lib/caseState';
import { useBaseParams, useRows } from '../lib/data';
import { clock, dateTime, int, pct, personName, plural } from '../lib/format';
import { ErrorNotice, Skeleton } from './primitives';

interface HistoryRow {
  primary_signal: string;
  primary_signal_label: string;
  risk_band: string;
  outcome: string;
  decided: number;
}
interface SignalEvalRow {
  primary_signal: string;
  primary_signal_label: string;
  cases: number;
  true_improper: number;
  precision: number;
}
interface ModelEvalRow {
  metric: string;
  value: number;
  model_version: string;
}
interface LiveSummary {
  enabled: boolean;
  groups: { primary_signal: string; risk_band: string; outcome: string; decided: number }[];
  recent: {
    case_id: string;
    outcome: string;
    reason_code: string;
    primary_signal: string;
    risk_band: string;
    risk_score: number;
    decided_by: string;
    decided_at: string;
  }[];
}

interface Tally {
  key: string;
  label: string;
  escalated: number;
  cleared: number;
  live: number;
  truth: number | null;
}

function useLiveSummary(version: number) {
  const [state, setState] = useState<{ data: LiveSummary | null; error: string | null }>({ data: null, error: null });
  useEffect(() => {
    let cancelled = false;
    fetch('/api/outcomes/summary')
      .then(async (r) => {
        if (!r.ok) throw new Error(`Recorded outcomes could not be loaded (${r.status})`);
        return (await r.json()) as LiveSummary;
      })
      .then((data) => !cancelled && setState({ data, error: null }))
      .catch((e: unknown) => !cancelled && setState({ data: null, error: e instanceof Error ? e.message : 'Recorded outcomes could not be loaded' }));
    return () => {
      cancelled = true;
    };
  }, [version]);
  return state;
}

const BAND_LABEL: Record<string, string> = { high: 'High risk', medium: 'Medium risk' };
const METRIC_LABEL: Record<string, string> = {
  precision_at_50: 'Precision, top 50 payments',
  precision_at_100: 'Precision, top 100 payments',
  pr_auc: 'Area under precision–recall curve',
  recall_at_threshold: 'Recall at the case threshold',
  payments_scored: 'Payments scored',
  precision_at_threshold: 'Precision at the case threshold',
  holdout_improper: 'Improper payments in the holdout',
};
const COUNT_METRICS = new Set(['payments_scored', 'holdout_improper']);
const METRIC_ORDER = ['precision_at_50', 'precision_at_100', 'precision_at_threshold', 'recall_at_threshold', 'pr_auc', 'holdout_improper', 'payments_scored'];

export function PrecisionView({ caseStates, pipeline }: { caseStates: CaseStates; pipeline: PipelineSummary | null }) {
  const base = useBaseParams();
  const history = useRows('outcome_history', base);
  const signalEval = useRows('signal_eval', base);
  const modelEval = useRows('model_eval', base);
  const live = useLiveSummary(caseStates.outcomesTotal);

  const historyRows = useMemo(() => (history.data ?? []) as HistoryRow[], [history.data]);
  const evalRows = useMemo(() => (signalEval.data ?? []) as SignalEvalRow[], [signalEval.data]);
  const modelRows = (modelEval.data ?? []) as ModelEvalRow[];
  const liveGroups = useMemo(() => live.data?.groups ?? [], [live.data]);

  const labels = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of evalRows) m.set(r.primary_signal, r.primary_signal_label);
    for (const r of historyRows) m.set(r.primary_signal, r.primary_signal_label);
    return m;
  }, [evalRows, historyRows]);

  const { bySignal, byBand, totals } = useMemo(() => {
    const tally = (map: Map<string, Tally>, key: string, label: string, outcome: string, n: number, isLive: boolean) => {
      const t = map.get(key) ?? { key, label, escalated: 0, cleared: 0, live: 0, truth: null };
      if (outcome === 'escalated') t.escalated += n;
      else if (outcome === 'cleared') t.cleared += n;
      if (isLive) t.live += n;
      map.set(key, t);
    };
    const s = new Map<string, Tally>();
    const b = new Map<string, Tally>();
    for (const r of historyRows) {
      tally(s, r.primary_signal, r.primary_signal_label, r.outcome, r.decided, false);
      tally(b, r.risk_band, BAND_LABEL[r.risk_band] ?? r.risk_band, r.outcome, r.decided, false);
    }
    for (const r of liveGroups) {
      tally(s, r.primary_signal, labels.get(r.primary_signal) ?? r.primary_signal, r.outcome, Number(r.decided), true);
      tally(b, r.risk_band, BAND_LABEL[r.risk_band] ?? r.risk_band, r.outcome, Number(r.decided), true);
    }
    for (const r of evalRows) {
      const t = s.get(r.primary_signal);
      if (t) t.truth = r.precision;
    }
    const all = [...s.values()];
    const sum = (k: 'escalated' | 'cleared' | 'live') => all.reduce((n, t) => n + t[k], 0);
    const order = (a: Tally, b: Tally) => b.escalated + b.cleared - (a.escalated + a.cleared) || a.label.localeCompare(b.label);
    return {
      bySignal: all.sort(order),
      byBand: [...b.values()].sort((x, y) => x.key.localeCompare(y.key)),
      totals: { escalated: sum('escalated'), cleared: sum('cleared'), live: sum('live') },
    };
  }, [historyRows, liveGroups, evalRows, labels]);

  const decided = totals.escalated + totals.cleared;
  const p = precision(totals.escalated, totals.cleared);
  const p100 = modelRows.find((m) => m.metric === 'precision_at_100')?.value ?? null;
  const loading = history.loading && !history.data;

  return (
    <main className="workspace" id="main">
      <section className="page-head" aria-labelledby="page-title">
        <div>
          <h1 id="page-title">Precision monitoring</h1>
          <p className="lede">
            How many flags held up once investigated. Measured from recorded outcomes, not from how many cases the model raised.
          </p>
        </div>
        <div className="status-note">
          <strong>Synthetic demonstration data</strong>
          <br />
          Rates here say nothing about real-world performance.
        </div>
      </section>

      <section className="summary-grid" aria-label="Precision summary">
        <Metric label="Outcomes recorded" value={loading ? null : int(decided)} foot={`${int(totals.live)} in this workbench · ${int(decided - totals.live)} seeded history`} />
        <Metric label="Held up at triage" value={loading ? null : pct(p)} foot="Escalated for assessment" />
        <Metric label="Cleared after review" value={loading ? null : pct(p == null ? null : 1 - p)} foot="Indicator did not hold up" />
        <Metric label="Model precision, top 100" value={modelEval.loading && !modelEval.data ? null : pct(p100)} foot="Against seeded ground truth" />
      </section>

      {history.error && !history.data && (
        <div style={{ marginBottom: 16 }}>
          <ErrorNotice title="Outcome history could not be loaded" message={history.error} onRetry={() => window.location.reload()} />
        </div>
      )}

      <div className="precision-grid">
        <section className="panel" aria-labelledby="by-signal-h">
          <div className="panel-head">
            <div>
              <h2 id="by-signal-h">By primary signal</h2>
              <span className="sub">Share of investigated cases escalated, by the signal that ranked them</span>
            </div>
          </div>
          <div className="panel-body">
            <Legend />
            {loading ? <MeterSkeleton rows={6} /> : <Meters rows={bySignal} withTruth />}
          </div>
        </section>

        <div style={{ display: 'grid', gap: 16 }}>
          <section className="panel" aria-labelledby="by-band-h">
            <div className="panel-head">
              <div>
                <h2 id="by-band-h">By risk band</h2>
                <span className="sub">Whether higher scores hold up more often than lower ones</span>
              </div>
            </div>
            <div className="panel-body">{loading ? <MeterSkeleton rows={2} /> : <Meters rows={byBand} />}</div>
          </section>

          <section className="panel" aria-labelledby="model-h">
            <div className="panel-head">
              <div>
                <h2 id="model-h">Model evaluation</h2>
                <span className="sub">
                  {pipeline
                    ? `${pipeline.model_name.split('.').pop()} ${pipeline.model_version} · scored ${clock(pipeline.scored_ts)}`
                    : 'Against the seeded ground truth'}
                </span>
              </div>
            </div>
            <div className="panel-body">
              {modelEval.loading && !modelEval.data ? (
                <MeterSkeleton rows={4} />
              ) : modelEval.error ? (
                <ErrorNotice title="Model evaluation could not be loaded" message={modelEval.error} />
              ) : (
                <dl className="eval-list">
                  {[...modelRows].sort((a, b) => METRIC_ORDER.indexOf(a.metric) - METRIC_ORDER.indexOf(b.metric)).map((m) => (
                    <div key={m.metric}>
                      <dt>{METRIC_LABEL[m.metric] ?? m.metric.replace(/_/g, ' ')}</dt>
                      <dd>{COUNT_METRICS.has(m.metric) ? int(m.value) : pct(m.value)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </section>
        </div>
      </div>

      <section className="panel" aria-labelledby="recent-h">
        <div className="panel-head">
          <div>
            <h2 id="recent-h">Recorded in this workbench</h2>
            <span className="sub">Most recent investigator decisions, read live from the case store</span>
          </div>
        </div>
        {live.error ? (
          <div style={{ padding: 16 }}>
            <ErrorNotice title="Recorded outcomes could not be loaded" message={live.error} />
          </div>
        ) : !live.data ? (
          <div className="panel-body">
            <MeterSkeleton rows={3} />
          </div>
        ) : !live.data.enabled ? (
          <div className="empty">
            <strong>Outcome capture is not connected</strong>
            <p>Connect the Lakebase case store to record outcomes from the review queue. Until then, precision comes from the seeded history only.</p>
          </div>
        ) : live.data.recent.length === 0 ? (
          <div className="empty">
            <strong>No outcomes recorded yet</strong>
            <p>Open a case in the review queue and clear or escalate it. The decision appears here straight away and counts towards the figures above.</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th scope="col">Case</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Signal</th>
                  <th scope="col">Score</th>
                  <th scope="col">Decided by</th>
                  <th scope="col">When</th>
                </tr>
              </thead>
              <tbody>
                {live.data.recent.map((r) => (
                  <tr key={r.case_id}>
                    <td className="case-id">
                      <a href={`?case=${r.case_id}&tab=closed`}>{r.case_id}</a>
                    </td>
                    <td>
                      <span className={`outcome-tag ${r.outcome}`}>{r.outcome === 'escalated' ? 'Escalated' : 'Cleared'}</span>
                    </td>
                    <td>{reasonLabel(r.reason_code)}</td>
                    <td>{labels.get(r.primary_signal) ?? r.primary_signal}</td>
                    <td className="mono">{r.risk_score}</td>
                    <td>{personName(r.decided_by)}</td>
                    <td className="mono xs">{dateTime(r.decided_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="table-foot">
          <span>
            Seeded history covers {plural(decided - totals.live, 'synthetic decision')} made before this queue. Ground-truth precision is known only
            because the data is synthetic.
          </span>
        </div>
      </section>
    </main>
  );
}

function Metric({ label, value, foot }: { label: string; value: string | null; foot: string }) {
  return (
    <article className="metric">
      <span className="metric-label">{label}</span>
      {value == null ? <Skeleton width={72} height={30} /> : <strong className="metric-value">{value}</strong>}
      <span className="metric-foot">{foot}</span>
    </article>
  );
}

function Legend() {
  return (
    <div className="legend" style={{ marginBottom: 12 }}>
      <span>
        <span className="key-bar" aria-hidden="true" />
        Held up at triage (escalated)
      </span>
      <span>
        <span className="key-tick" aria-hidden="true" />
        Model precision against ground truth
      </span>
    </div>
  );
}

/** One single-series meter per row: the bar is the share escalated; the tick is ground truth. */
function Meters({ rows, withTruth = false }: { rows: Tally[]; withTruth?: boolean }) {
  if (rows.length === 0) return <p className="muted">No outcomes have been recorded yet.</p>;
  return (
    <ul className="meters">
      {rows.map((r) => {
        const n = r.escalated + r.cleared;
        const share = precision(r.escalated, r.cleared);
        const tip = `${int(r.escalated)} escalated · ${int(r.cleared)} cleared${r.live ? ` · ${int(r.live)} recorded here` : ''}${
          withTruth && r.truth != null ? ` · model ${pct(r.truth)} on ground truth` : ''
        }`;
        return (
          <li
            key={r.key}
            className="meter-row"
            tabIndex={0}
            aria-label={`${r.label}: ${pct(share)} held up of ${plural(n, 'decision')}. ${tip}.`}
          >
            <div className="meter-name">
              {r.label}
              <span className="meter-count">{plural(n, 'decision')}</span>
              <span className="meter-detail" aria-hidden="true">
                {int(r.escalated)} escalated · {int(r.cleared)} cleared{r.live ? ` · ${int(r.live)} here` : ''}
              </span>
            </div>
            <div className="meter-track" aria-hidden="true">
              <div className="meter-fill" style={{ width: `${(share ?? 0) * 100}%` }} />
              {withTruth && r.truth != null && <div className="meter-tick" style={{ left: `${r.truth * 100}%` }} />}
            </div>
            <div className="meter-value" aria-hidden="true">
              {pct(share)}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function MeterSkeleton({ rows }: { rows: number }) {
  return (
    <div className="stack" aria-busy="true">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height={14} width={`${92 - i * 7}%`} />
      ))}
    </div>
  );
}
