import { useEffect, useMemo, useState } from 'react';
import { Skeleton } from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import { useQuery } from '../lib/query';
import { Check, Loader2, Plus, Send, Trash2 } from 'lucide-react';
import { TrendChart } from '../components/charts';
import { Empty, ListSkeleton, Modal, QueryError, StatusBadge, statusTone } from '../components/common';
import { postJson } from '../lib/api';
import { bn, dateTime, LEVER_LABELS, leverValue, money, months, num, pct, personName, tone, yes, cause } from '../lib/format';
import { useAppState } from '../lib/state';
import { TERMINAL } from '../lib/api';

export type ScenarioRow = Record<string, unknown> & { scenario_id: string; scenario_name: string };

const COLORS = ['s1', 's2', 's3'];

export function ScenariosPage({ scenarios, loading, error }: { scenarios: ScenarioRow[]; loading: boolean; error: string | null }) {
  const { scenarioId, setScenarioId, dataVersion, runs } = useAppState();
  const [compare, setCompare] = useState<string[]>(['BASE', 'CAP_BAL', 'ACCEL']);
  const [builder, setBuilder] = useState<null | { revise?: ScenarioRow }>(null);
  const fy = useQuery('scenario_fy', { data_version: sql.string(dataVersion) });

  const available = scenarios.filter((s) => s.computed_version !== null && s.computed_version !== undefined);
  const compareSet = compare.filter((id) => available.some((s) => s.scenario_id === id)).slice(0, 3);
  const selected = scenarios.find((s) => s.scenario_id === scenarioId) ?? scenarios[0];

  const toggleCompare = (id: string) => {
    setCompare((current) => (current.includes(id) ? current.filter((c) => c !== id) : [...current, id].slice(-3)));
  };

  const chart = useMemo(() => {
    const rows = fy.data ?? [];
    const labels = [...new Set(rows.map((r) => String(r.financial_year)))];
    const series = compareSet.map((id, i) => ({
      key: id,
      label: scenarios.find((s) => s.scenario_id === id)?.scenario_name ?? id,
      values: labels.map((l) => {
        const r = rows.find((x) => x.scenario_id === id && x.financial_year === l);
        return r ? num(r.forecast_aud_m) / 1000 : null;
      }),
      className: COLORS[i],
    }));
    const base = rows.filter((r) => r.scenario_id === 'BASE');
    const capacity = { key: 'capacity', label: 'Deliverable capacity (baseline)', values: labels.map((l) => { const r = base.find((x) => x.financial_year === l); return r && r.capacity_aud_m !== null ? num(r.capacity_aud_m) / 1000 : null; }), className: 'capacity', dashed: true };
    const envelope = { key: 'envelope', label: 'Funding envelope', values: labels.map((l) => { const r = base.find((x) => x.financial_year === l); return r && r.envelope_aud_m !== null ? num(r.envelope_aud_m) / 1000 : null; }), className: 'envelope', dashed: true };
    return { labels, series: [...series, capacity, envelope] };
  }, [fy.data, compareSet, scenarios]);

  const pendingRun = (s: ScenarioRow) => runs.find((r) => r.scenarioId === s.scenario_id && (!r.status || !TERMINAL.includes(r.status.life_cycle_state ?? '')));

  return (
    <section className="page active" aria-labelledby="scenario-title">
      <div className="page-head">
        <div>
          <p className="eyebrow">Scenario studio</p>
          <h1 id="scenario-title">Allocation scenarios</h1>
          <p className="subtitle">Build scenarios from explicit, versioned levers. Saving one re-runs the forecast, capacity test and confidence for every scenario, so each option is compared on the same basis.</p>
        </div>
        <div className="actions"><button className="button primary" onClick={() => setBuilder({})}><Plus size={16} /> New scenario</button></div>
      </div>
      {error && <QueryError message={`Scenarios could not load: ${error}`} />}

      <div className="scenario-strip wrap">
        {loading && scenarios.length === 0 && Array.from({ length: 4 }, (_, i) => <Skeleton className="scenario-skeleton" key={i} />)}
        {scenarios.map((s) => {
          const pending = yes(s.pending_recompute);
          const run = pendingRun(s);
          const comparable = !pending || Boolean(s.computed_version);
          return (
            <div key={s.scenario_id} className={`scenario-card ${scenarioId === s.scenario_id ? 'active' : ''}`}>
              <button className="scenario-select" onClick={() => setScenarioId(s.scenario_id)}>
                <span className="scenario-title"><strong>{s.scenario_name}</strong><StatusBadge tone={statusTone(String(s.workflow_status))}>{String(s.workflow_status)}</StatusBadge></span>
                {pending ? (
                  <span className="pending"><Loader2 size={13} className="spin" /> {run ? `Recomputing · ${run.status?.life_cycle_state?.toLowerCase() ?? 'queued'}` : 'Awaiting recompute'} (v{num(s.latest_version)})</span>
                ) : (
                  <span>{bn(s.total_forecast_aud_m)} · {pct(s.forecast_confidence_pct)} confidence · {num(s.capacity_breaches)} breaches</span>
                )}
                <span className="muted-line">{s.source === 'app' ? `${personName(String(s.created_by))} · ${dateTime(s.created_at)}` : String(s.decision_purpose ?? '')}</span>
              </button>
              {comparable && s.computed_version !== null && (
                <label className="compare-toggle"><input type="checkbox" checked={compareSet.includes(s.scenario_id)} onChange={() => toggleCompare(s.scenario_id)} /> Compare</label>
              )}
            </div>
          );
        })}
      </div>

      <article className="card">
        <div className="card-head"><div><h2>Side-by-side comparison</h2><p>Up to three scenarios · five-year horizon · nominal</p></div></div>
        {compareSet.length === 0 ? <Empty>Tick Compare on up to three scenarios.</Empty> : (
          <div className="table-wrap">
            <table className="compare-table">
              <thead><tr><th>Measure</th>{compareSet.map((id, i) => <th key={id} className="num"><i className={`swatch ${COLORS[i]}`} /> {scenarios.find((s) => s.scenario_id === id)?.scenario_name}</th>)}</tr></thead>
              <tbody>
                {COMPARE_ROWS.map((m) => (
                  <tr key={m.label}><td>{m.label}<small className="table-subtitle">{m.hint}</small></td>
                    {compareSet.map((id) => { const s = scenarios.find((x) => x.scenario_id === id)!; return <td key={id} className="num">{m.render(s)}</td>; })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {fy.loading && !fy.data && <Skeleton className="chart-skeleton" />}
        {chart.labels.length > 0 && compareSet.length > 0 && <TrendChart ariaLabel="Forecast expenditure by scenario and financial year" labels={chart.labels} series={chart.series} />}
      </article>

      {selected && <ScenarioDetail scenario={selected} onRevise={() => setBuilder({ revise: selected })} />}
      {builder && <ScenarioBuilder scenarios={available} revise={builder.revise} onClose={() => setBuilder(null)} />}
    </section>
  );
}

const COMPARE_ROWS: Array<{ label: string; hint: string; render: (s: ScenarioRow) => React.ReactNode }> = [
  { label: 'Horizon forecast', hint: 'FY27–31 total', render: (s) => bn(s.total_forecast_aud_m) },
  { label: 'vs Working baseline', hint: '', render: (s) => <span className={`delta ${tone(s.vs_baseline_aud_m)}`}>{bn(s.vs_baseline_aud_m, true)}</span> },
  { label: 'Affordability', hint: 'headroom to funding envelope', render: (s) => <span className={`delta ${tone(s.headroom_aud_m, true)}`}>{bn(s.headroom_aud_m, true)}</span> },
  { label: 'P10–P90 range', hint: 'simulated, unspent work', render: (s) => `${bn(s.forecast_p10_aud_m)}–${bn(s.forecast_p90_aud_m)}` },
  { label: 'Capacity breaches', hint: 'input-years above 100%', render: (s) => <span className={num(s.capacity_breaches) > 0 ? 'delta bad' : 'delta good'}>{num(s.capacity_breaches)}</span> },
  { label: 'Peak utilisation', hint: '', render: (s) => `${pct(s.peak_utilisation_pct)} · ${s.peak_category} ${s.peak_financial_year}` },
  { label: 'Forecast confidence', hint: 'spend-weighted', render: (s) => pct(s.forecast_confidence_pct) },
  { label: 'Projects changed', hint: 'vs baseline', render: (s) => num(s.projects_changed) },
  { label: 'Spend pushed past FY31', hint: 'by deferring projects', render: (s) => bn(s.spend_beyond_horizon_aud_m) },
  { label: 'Indicative delay cost', hint: 'later completions × endorsed rate; not in forecast', render: (s) => money(s.indicative_delay_cost_aud_m) },
  { label: 'Regional completions deferred', hint: 'past the horizon', render: (s) => num(s.regional_completions_deferred) },
];

function ScenarioDetail({ scenario, onRevise }: { scenario: ScenarioRow; onRevise: () => void }) {
  const { dataVersion, role, refresh, notify } = useAppState();
  const v = sql.string(dataVersion);
  const id = sql.string(scenario.scenario_id);
  const detail = useQuery('scenario_detail', { scenario_id: id, data_version: v });
  const changes = useQuery('scenario_changes', { scenario_id: id, data_version: v });
  const decisions = useQuery('scenario_decisions', { scenario_id: id, data_version: v });
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const levers = (detail.data ?? []).filter((r) => r.record_kind === 'lever');
  const events = (detail.data ?? []).filter((r) => r.record_kind === 'event');
  const governed = ['BASE', 'ENDORSED'].includes(scenario.scenario_id);
  const status = String(scenario.workflow_status);

  const act = async (event: 'Submitted' | 'Returned' | 'Endorsed') => {
    setBusy(true);
    try {
      await postJson(`/api/scenarios/${scenario.scenario_id}/events`, { event, version: scenario.latest_version, note });
      notify(`${scenario.scenario_name}: ${event.toLowerCase()}`, 'good');
      setNote('');
      refresh(3000);
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Action failed', 'bad');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid two-one detail-grid">
      <article className="card">
        <div className="card-head">
          <div><h2>What moved and why · {scenario.scenario_name}</h2><p>Projects whose timing or cost differs from the Working baseline, with the lever or sequencing decision responsible</p></div>
        </div>
        {changes.loading && !changes.data && <ListSkeleton rows={5} />}
        {changes.error && <QueryError message={`Changes could not load: ${changes.error}`} />}
        {changes.data?.length === 0 && <Empty>{scenario.scenario_id === 'BASE' ? 'The Working baseline is the reference: nothing moves.' : 'No project differs from the baseline in this scenario.'}</Empty>}
        {changes.data && changes.data.length > 0 && (
          <div className="table-wrap"><table className="compact"><thead><tr><th>Project</th><th className="num">Horizon Δ</th><th className="num">Finish</th><th className="num">Delay cost</th><th>Cause</th></tr></thead><tbody>
            {changes.data.slice(0, 25).map((c) => (
              <tr key={String(c.project_id)}>
                <td><strong>{c.project_name}</strong><small className="table-subtitle">{c.program_name} · {c.region_type}</small></td>
                <td className="num"><span className={`delta ${tone(c.delta_aud_m)}`}>{money(c.delta_aud_m, true)}</span></td>
                <td className="num">{c.finish_shift_months === null ? '—' : months(c.finish_shift_months)}{yes(c.completion_moves_beyond_horizon) && <small className="table-subtitle">past FY31</small>}</td>
                <td className="num">{num(c.delay_cost_aud_m) > 0.5 ? money(c.delay_cost_aud_m) : '—'}</td>
                <td className="cause">{cause(c.changes)}</td>
              </tr>
            ))}
          </tbody></table></div>
        )}
        {decisions.data && decisions.data.length > 0 && (
          <>
            <h3 className="drawer-section">Sequencer decision log</h3>
            <p className="muted-small">Each step deferred one Deferrable project by six months, chosen for the largest reduction in over-utilisation per dollar moved out of the horizon, and was kept only if total over-utilisation fell.</p>
            <ol className="decision-log">
              {decisions.data.slice(0, 20).map((d) => (
                <li key={num(d.iteration)}><span className="mono-small">#{num(d.iteration)}</span> Defer <strong>{d.project_name}</strong> {num(d.defer_months)} mo (total {num(d.cumulative_defer_months)}) — {d.trigger_category} {d.trigger_financial_year} at {pct(d.trigger_utilisation_pct)}</li>
              ))}
            </ol>
          </>
        )}
      </article>

      <article className="card">
        <div className="card-head"><div><h2>Levers and decisions</h2><p>v{num(scenario.latest_version)} · {String(scenario.method).replace('_', ' ')}{scenario.base_scenario_id ? ` from ${scenario.base_scenario_id}` : ''}</p></div><StatusBadge tone={statusTone(status)}>{status}</StatusBadge></div>
        {Boolean(scenario.description) && <p className="muted-small">{String(scenario.description)}</p>}
        {detail.loading && !detail.data && <ListSkeleton rows={3} />}
        {levers.length === 0 && !detail.loading && <p className="muted-small">{scenario.method === 'auto_sequence' ? 'No manual levers: the capacity-aware sequencer chooses the deferrals.' : governed ? 'Governed reference scenario: no levers.' : 'No levers on this version.'}</p>}
        <ul className="lever-list">
          {levers.map((l) => (
            <li key={String(l.record_id)}><strong>{LEVER_LABELS[String(l.label)] ?? l.label}</strong> {l.target_name} · {leverValue(String(l.label), l.value)}{l.note && <small>{String(l.note)}</small>}</li>
          ))}
        </ul>
        {!governed && (
          <div className="workflow">
            <label className="field-label" htmlFor="scenario-note">Decision note</label>
            <textarea id="scenario-note" className="textarea" rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Recommended for EBC: resolves FY29 labour breach at $2.2bn indicative delay cost" />
            <div className="actions wrap">
              {scenario.source === 'app' && <button className="button" onClick={onRevise} disabled={busy}>Revise levers</button>}
              {['Draft', 'Returned'].includes(status) && <button className="button" onClick={() => act('Submitted')} disabled={busy || yes(scenario.pending_recompute)}><Send size={15} /> Submit for endorsement</button>}
              {status === 'Submitted' && role === 'Portfolio office' && (
                <>
                  <button className="button" onClick={() => act('Returned')} disabled={busy || !note.trim()}>Return</button>
                  <button className="button primary" onClick={() => act('Endorsed')} disabled={busy}><Check size={15} /> Endorse</button>
                </>
              )}
              {status === 'Submitted' && role !== 'Portfolio office' && <p className="muted-small">Awaiting portfolio office decision.</p>}
            </div>
          </div>
        )}
        <h3 className="drawer-section">History</h3>
        {events.length === 0 ? <p className="muted-small">{governed ? 'Maintained by the forecast pipeline.' : 'Seeded by the pipeline; no app activity yet.'}</p> : (
          <ol className="history">
            {events.map((e) => (
              <li key={String(e.record_id)}><strong>{e.label}</strong> v{num(e.version)} · {personName(String(e.actor))} · {dateTime(e.created_at)}{e.note && <small>{String(e.note)}</small>}{e.job_run_id && <small className="mono-small">forecast run {String(e.job_run_id)}</small>}</li>
            ))}
          </ol>
        )}
      </article>
    </div>
  );
}

type LeverDraft = { lever_type: string; target_type: string; target_id: string; value: string; rationale: string };

const LEVER_DEFAULTS: Record<string, { target_type: string; value: string }> = {
  defer_months: { target_type: 'program', value: '12' },
  accelerate_months: { target_type: 'program', value: '6' },
  escalation_delta_pp: { target_type: 'sector', value: '0.5' },
  capacity_uplift_pct: { target_type: 'capacity_category', value: '5' },
  scope_change_aud_m: { target_type: 'project', value: '-100' },
  exclude_project: { target_type: 'project', value: '1' },
};

const VALUE_UNITS: Record<string, string> = {
  defer_months: 'months',
  accelerate_months: 'months',
  escalation_delta_pp: 'pp a year',
  capacity_uplift_pct: '% supply',
  scope_change_aud_m: 'AUD m',
  exclude_project: '',
};

function ScenarioBuilder({ scenarios, revise, onClose }: { scenarios: ScenarioRow[]; revise?: ScenarioRow; onClose: () => void }) {
  const { dataVersion, trackRun, notify, refresh, setScenarioId, identity } = useAppState();
  const targets = useQuery('lever_targets', { data_version: sql.string(dataVersion) });
  const existing = useQuery('scenario_detail', { scenario_id: sql.string(revise?.scenario_id ?? '-'), data_version: sql.string(dataVersion) });
  const [name, setName] = useState(revise ? revise.scenario_name : 'FY29 labour capacity response');
  const [purpose, setPurpose] = useState(revise ? String(revise.decision_purpose ?? '') : 'Executive Budget Committee review');
  const [description, setDescription] = useState(revise ? String(revise.description ?? '') : '');
  const [base, setBase] = useState(revise ? String(revise.base_scenario_id ?? 'BASE') : 'BASE');
  const [method, setMethod] = useState<'levers' | 'auto_sequence'>(revise?.method === 'auto_sequence' ? 'auto_sequence' : 'levers');
  const [levers, setLevers] = useState<LeverDraft[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!revise || !existing.data) return;
    setLevers(existing.data.filter((r) => r.record_kind === 'lever').map((l) => ({
      lever_type: String(l.label), target_type: String(l.target_type), target_id: String(l.target_id ?? ''), value: String(l.value), rationale: String(l.note ?? ''),
    })));
  }, [revise, existing.data]);

  useEffect(() => {
    if (revise || levers.length > 0) return;
    setLevers([{ lever_type: 'defer_months', target_type: 'program', target_id: 'PRG-RRS', value: '12', rationale: 'Release skilled civil labour in FY29' }]);
  }, [revise, levers.length]);

  const options = (type: string) => {
    if (type === 'sector') return [['Transport', 'Transport'], ['Energy', 'Energy'], ['Water', 'Water'], ['Social', 'Social']];
    if (type === 'portfolio') return [['', 'Whole portfolio']];
    return (targets.data ?? []).filter((t) => t.target_type === type).map((t) => [String(t.target_id), `${t.target_name}${t.target_type === 'project' ? ` — ${t.detail}` : ''}`]);
  };

  const update = (i: number, patch: Partial<LeverDraft>) => setLevers((current) => current.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const setType = (i: number, lever_type: string) => {
    const d = LEVER_DEFAULTS[lever_type];
    update(i, { lever_type, target_type: d.target_type, value: d.value, target_id: d.target_type === 'sector' ? 'Transport' : '' });
  };

  const valid = name.trim() && (method === 'auto_sequence' || levers.length > 0) &&
    levers.every((l) => l.value !== '' && Number.isFinite(Number(l.value)) && (l.target_type === 'portfolio' || l.target_id));

  const save = async () => {
    setSaving(true);
    try {
      const result = await postJson<{ scenario_id: string; version: number; run_id: number | null }>('/api/scenarios', {
        scenario_id: revise?.scenario_id, name, purpose, description, base_scenario_id: base, method,
        levers: levers.map((l) => ({ ...l, value: Number(l.value), target_id: l.target_type === 'portfolio' ? null : l.target_id })),
      });
      if (result.run_id) trackRun({ runId: result.run_id, label: `${name} v${result.version}`, scenarioId: result.scenario_id });
      notify(result.run_id ? `${name} saved. Forecast recompute started (run ${result.run_id}).` : `${name} saved. Recompute is not configured for this app.`, 'good');
      setScenarioId(result.scenario_id);
      refresh(4000);
      onClose();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Scenario could not be saved', 'bad');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={revise ? `Revise ${revise.scenario_name}` : 'New allocation scenario'} eyebrow={revise ? `Creates v${num(revise.latest_version) + 1}` : 'Scenario builder'} onClose={onClose} wide>
      <div className="form-grid">
        <div className="field"><label htmlFor="sc-name">Scenario name</label><input id="sc-name" value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div className="field"><label htmlFor="sc-purpose">Decision purpose</label><input id="sc-purpose" value={purpose} onChange={(e) => setPurpose(e.target.value)} /></div>
        <div className="field"><label htmlFor="sc-base">Start from</label>
          <select id="sc-base" value={base} onChange={(e) => setBase(e.target.value)} disabled={Boolean(revise)}>
            {scenarios.filter((s) => s.scenario_id !== revise?.scenario_id).map((s) => <option key={s.scenario_id} value={s.scenario_id}>{s.scenario_name} · v{num(s.computed_version)}</option>)}
          </select>
        </div>
        <div className="field"><label htmlFor="sc-method">Method</label>
          <select id="sc-method" value={method} onChange={(e) => setMethod(e.target.value as 'levers' | 'auto_sequence')}>
            <option value="levers">Apply my levers</option>
            <option value="auto_sequence">Apply my levers, then sequence to capacity</option>
          </select>
        </div>
      </div>
      <div className="field"><label htmlFor="sc-desc">Rationale</label><input id="sc-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What question does this scenario answer?" /></div>

      <h3 className="drawer-section">Levers</h3>
      {targets.loading && !targets.data && <ListSkeleton rows={2} />}
      <div className="lever-editor">
        {levers.map((l, i) => (
          <div className="lever-row" key={i}>
            <select aria-label="Lever" value={l.lever_type} onChange={(e) => setType(i, e.target.value)}>
              {Object.entries(LEVER_LABELS).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
            <select aria-label="Applies to" value={l.target_type} onChange={(e) => update(i, { target_type: e.target.value, target_id: e.target.value === 'sector' ? 'Transport' : '' })}
              disabled={l.lever_type === 'capacity_uplift_pct' || l.lever_type === 'exclude_project'}>
              {l.lever_type === 'capacity_uplift_pct' ? <option value="capacity_category">Delivery input</option> : (
                <>
                  <option value="project">Project</option><option value="program">Program</option>
                  {l.lever_type !== 'exclude_project' && <><option value="sector">Sector</option><option value="portfolio">Portfolio</option></>}
                </>
              )}
            </select>
            <select aria-label="Target" value={l.target_id} onChange={(e) => update(i, { target_id: e.target.value })} disabled={l.target_type === 'portfolio'}>
              {l.target_type !== 'portfolio' && <option value="">Choose…</option>}
              {options(l.target_type).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            {l.lever_type !== 'exclude_project' ? (
              <div className="value-input"><input aria-label="Value" inputMode="decimal" value={l.value} onChange={(e) => update(i, { value: e.target.value })} /><span>{VALUE_UNITS[l.lever_type]}</span></div>
            ) : <span className="muted-small">Unspent work removed</span>}
            <input aria-label="Lever rationale" className="rationale" value={l.rationale} onChange={(e) => update(i, { rationale: e.target.value })} placeholder="Why (recorded with the lever)" />
            <button className="button icon-button" aria-label="Remove lever" onClick={() => setLevers((c) => c.filter((_, j) => j !== i))}><Trash2 size={16} /></button>
          </div>
        ))}
        <button className="button" onClick={() => setLevers((c) => [...c, { lever_type: 'defer_months', target_type: 'program', target_id: '', value: '12', rationale: '' }])}><Plus size={15} /> Add lever</button>
      </div>
      <div className="session-warning"><Check size={16} />Saved as a governed draft (v{revise ? num(revise.latest_version) + 1 : 1}) in Unity Catalog by {identity?.email ?? 'you'}. The forecast job then recomputes every scenario — about five minutes on serverless — and records the run against the scenario version.</div>
      <div className="modal-actions">
        <button className="button" onClick={onClose}>Cancel</button>
        <button className="button primary" disabled={!valid || saving} onClick={save}>{saving ? <><Loader2 size={15} className="spin" /> Saving</> : 'Save and recompute'}</button>
      </div>
    </Modal>
  );
}
