import { useState } from 'react';
import { Skeleton } from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import { useQuery } from '../lib/query';
import { Loader2, MessageSquarePlus, Sparkles } from 'lucide-react';
import { Waterfall } from '../components/charts';
import { Empty, KpiCard, ListSkeleton, LoadingCards, Modal, QueryError, Segmented, StatusBadge } from '../components/common';
import { postJson } from '../lib/api';
import { bn, date, dateTime, money, num, personName, tone } from '../lib/format';
import { useAppState } from '../lib/state';
import { SECTORS } from './OverviewPage';

type Period = 'YTD' | 'CURRENT_FY' | 'HORIZON';
const REASONS = ['Contractor claim or variation', 'Productivity below plan', 'Latent site conditions', 'Market escalation above index', 'Timing of payments', 'Ledger coding or data error', 'Unapproved scope', 'Other'];

type Explain = { projectId: string; projectName: string; programName: string; unexplained: number; variance: number };

export function VariancePage({ onReviewAssumptions }: { onReviewAssumptions: () => void }) {
  const { dataVersion, setDrill } = useAppState();
  const [period, setPeriod] = useState<Period>('CURRENT_FY');
  const [sector, setSector] = useState('ALL');
  const [explain, setExplain] = useState<Explain | null>(null);
  const [showAll, setShowAll] = useState(false);
  const v = sql.string(dataVersion);
  const summary = useQuery('overview_summary', { scenario_id: sql.string('BASE'), sector: sql.string('ALL'), data_version: v });
  const bridge = useQuery('variance_bridge', { period: sql.string(period), data_version: v });
  const projects = useQuery('variance_projects', { period: sql.string(period), sector: sql.string(sector), data_version: v });
  const commentary = useQuery('variance_commentary', { period: sql.string(period), data_version: v });
  const row = summary.data?.[0];
  const b = bridge.data ?? [];
  const plan = num(b[0]?.plan_aud_m);
  const steps = b.map((d) => ({ label: String(d.driver), value: num(d.amount_aud_m) }));
  const periodLabel = String(b[0]?.period_label ?? '');
  const rows = projects.data ?? [];
  const unattributed = rows.reduce((a, r) => a + Math.max(0, Math.abs(num(r.unexplained_aud_m)) - Math.abs(num(r.attributed_aud_m))), 0);

  return (
    <section className="page active" aria-labelledby="variance-title">
      <div className="page-head">
        <div>
          <p className="eyebrow">Variance & actuals · Working baseline</p>
          <h1 id="variance-title">Why the forecast moved</h1>
          <p className="subtitle">Forecast against endorsed plan, broken into recorded drivers. Anything no recorded driver explains lands in Unexplained and needs an owner's attribution.</p>
        </div>
        <div className="freshness"><strong>Actuals through {date(row?.actuals_through)}</strong>Closed months only · synthetic ledger</div>
      </div>
      <div className="filters">
        <Segmented label="Period" value={period} onChange={setPeriod} options={[['YTD', 'Year to date'], ['CURRENT_FY', row?.current_fy_label ? `${row.current_fy_label} full year` : 'Current FY'], ['HORIZON', 'FY27–31 horizon']]} />
        <select className="select" aria-label="Sector" value={sector} onChange={(e) => setSector(e.target.value)}>
          {SECTORS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
      {summary.loading && !row && <LoadingCards />}
      {summary.error && <QueryError message={`Variance summary could not load: ${summary.error}`} />}
      {row && (
        <div className="grid kpis">
          <KpiCard label="YTD actual" value={bn(row.ytd_actual_aud_m)} detail={<>vs {bn(row.ytd_plan_aud_m)} plan · <span className={`delta ${tone(num(row.ytd_actual_aud_m) - num(row.ytd_plan_aud_m))}`}>{bn(num(row.ytd_actual_aud_m) - num(row.ytd_plan_aud_m), true)}</span></>} />
          <KpiCard label={`${row.current_fy_label} forecast`} value={bn(row.current_fy_forecast_aud_m)} detail={<>vs {bn(row.current_fy_plan_aud_m)} plan · <span className={`delta ${tone(num(row.current_fy_forecast_aud_m) - num(row.current_fy_plan_aud_m))}`}>{bn(num(row.current_fy_forecast_aud_m) - num(row.current_fy_plan_aud_m), true)}</span></>} />
          <KpiCard label="Schedule variance" value={`+${num(row.schedule_variance_months).toFixed(1)} mo`} detail="forecast-weighted average approved slip" />
          <KpiCard label="Unexplained, not yet attributed" value={money(unattributed)} detail={<>gross across {rows.filter((r) => Math.abs(num(r.unexplained_aud_m)) >= 1).length} projects{period === 'CURRENT_FY' ? ` · net ${money(row.current_fy_unexplained_aud_m, true)} in ${row.current_fy_label}` : ''} · <StatusBadge tone={unattributed > 50 ? 'risk' : 'good'}>{unattributed > 50 ? 'Needs attribution' : 'Attributed'}</StatusBadge></>} />
        </div>
      )}

      <article className="card">
        <div className="card-head">
          <div><h2>{periodLabel || 'Variance'} bridge: endorsed plan to forecast</h2><p>Recorded drivers in the order they are applied · nominal · synthetic</p></div>
          <button className="button" onClick={onReviewAssumptions}>Review assumptions</button>
        </div>
        {bridge.loading && b.length === 0 && <Skeleton className="chart-skeleton" />}
        {bridge.error && <QueryError message={`Variance bridge could not load: ${bridge.error}`} />}
        {b.length > 0 && <Waterfall start={plan} startLabel="Endorsed plan" steps={steps} endLabel="Forecast" />}
      </article>

      <div className="grid two-one detail-grid">
        <article className="card">
          <div className="card-head"><div><h2>Projects outside tolerance</h2><p>Variance beyond tolerance, flagged for attention, or with material unexplained variance · select a project to drill in</p></div></div>
          {projects.loading && rows.length === 0 && <ListSkeleton rows={6} />}
          {projects.error && <QueryError message={`Projects could not load: ${projects.error}`} />}
          {!projects.loading && rows.length === 0 && !projects.error && <Empty>No project is outside tolerance for this period.</Empty>}
          {rows.length > 0 && (
            <div className="table-wrap"><table className="compact"><thead><tr><th>Project</th><th className="num">Variance</th><th className="num">Tolerance</th><th>Main driver</th><th className="num">Unexplained</th><th /></tr></thead><tbody>
              {(showAll ? rows : rows.slice(0, 12)).map((r) => {
                const remaining = Math.abs(num(r.unexplained_aud_m)) - Math.abs(num(r.attributed_aud_m));
                return (
                  <tr key={String(r.project_id)}>
                    <td><button className="link-button strong" onClick={() => setDrill({ kind: 'project', id: String(r.project_id), name: String(r.project_name) })}>{r.project_name}</button><small className="table-subtitle">{r.program_name} · {r.attention_reasons || r.gateway_rating}</small></td>
                    <td className="num"><span className={`delta ${tone(r.variance_aud_m)}`}>{money(r.variance_aud_m, true)}</span><small className="table-subtitle">{num(r.variance_pct).toFixed(1)}%</small></td>
                    <td className="num">±{money(r.tolerance_aud_m)}</td>
                    <td>{r.primary_driver}</td>
                    <td className="num">{money(r.unexplained_aud_m, true)}{num(r.commentary_count) > 0 && <small className="table-subtitle">{remaining > 1 ? `${money(remaining)} left` : 'attributed'}</small>}</td>
                    <td><button className="button small" onClick={() => setExplain({ projectId: String(r.project_id), projectName: String(r.project_name), programName: String(r.program_name), unexplained: num(r.unexplained_aud_m) - Math.sign(num(r.unexplained_aud_m)) * Math.abs(num(r.attributed_aud_m)), variance: num(r.variance_aud_m) })}><MessageSquarePlus size={14} /> Explain</button></td>
                  </tr>
                );
              })}
            </tbody></table></div>
          )}
          {rows.length > 12 && <button className="button small show-more" onClick={() => setShowAll(!showAll)}>{showAll ? 'Show top 12' : `Show all ${rows.length}`}</button>}
        </article>
        <article className="card">
          <div className="card-head"><div><h2>Variance commentary</h2><p>Attributions recorded by program and portfolio offices · {periodLabel}</p></div></div>
          {commentary.loading && !commentary.data && <ListSkeleton rows={3} />}
          {commentary.data?.length === 0 && <Empty>No commentary recorded for this period yet.</Empty>}
          <ol className="history">
            {commentary.data?.map((c) => (
              <li key={String(c.commentary_id)}>
                <strong>{c.scope_name}</strong> · {c.reason_code} {num(c.amount_aud_m) !== 0 && <>· {money(c.amount_aud_m, true)}</>}
                <p>{String(c.commentary)}</p>
                <small>{personName(String(c.actor))} · {dateTime(c.created_at)}{c.source === 'ai_draft' ? ' · drafted with AI, reviewed by author' : ''}</small>
              </li>
            ))}
          </ol>
        </article>
      </div>
      {explain && <ExplainModal period={period} target={explain} onClose={() => setExplain(null)} />}
    </section>
  );
}

function ExplainModal({ period, target, onClose }: { period: Period; target: Explain; onClose: () => void }) {
  const { notify, refresh, identity } = useAppState();
  const [reason, setReason] = useState(REASONS[0]);
  const [amount, setAmount] = useState(String(Math.round(target.unexplained)));
  const [text, setText] = useState('');
  const [source, setSource] = useState<'user' | 'ai_draft'>('user');
  const [drafting, setDrafting] = useState(false);
  const [saving, setSaving] = useState(false);

  const draft = async () => {
    setDrafting(true);
    try {
      const r = await postJson<{ draft: string }>('/api/ai/variance-draft', { period, scope_level: 'project', scope_id: target.projectId });
      setText(r.draft);
      setSource('ai_draft');
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Draft failed', 'bad');
    } finally {
      setDrafting(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await postJson('/api/commentary', { period, scope_level: 'project', scope_id: target.projectId, reason_code: reason, amount_aud_m: Number(amount) || 0, commentary: text, source });
      notify(`Commentary recorded for ${target.projectName}`, 'good');
      refresh(3000);
      onClose();
    } catch (e) {
      notify(e instanceof Error ? e.message : 'Could not save', 'bad');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={`Explain variance · ${target.projectName}`} eyebrow={`${target.programName} · ${money(target.variance, true)} total, ${money(target.unexplained, true)} not yet attributed`} onClose={onClose} wide>
      <div className="form-grid">
        <div className="field"><label htmlFor="ex-reason">Reason</label><select id="ex-reason" value={reason} onChange={(e) => setReason(e.target.value)}>{REASONS.map((r) => <option key={r}>{r}</option>)}</select></div>
        <div className="field"><label htmlFor="ex-amount">Amount attributed (AUD m)</label><input id="ex-amount" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></div>
      </div>
      <div className="field">
        <div className="field-row"><label htmlFor="ex-text">Commentary</label>
          <button className="button small" onClick={draft} disabled={drafting}>{drafting ? <><Loader2 size={14} className="spin" /> Drafting</> : <><Sparkles size={14} /> Draft from the data</>}</button>
        </div>
        <textarea id="ex-text" className="textarea" rows={6} value={text} onChange={(e) => setText(e.target.value)} placeholder="What caused the variance, what evidence supports it, and what happens next." />
        {source === 'ai_draft' && <p className="muted-small">Drafted from this project's variance drivers and approved change register. Check it against the evidence and edit before saving — it will be recorded as yours.</p>}
      </div>
      <p className="muted-small">Recorded against {period.replace('_', ' ').toLowerCase()} variance as {identity?.email ?? 'you'}. Commentary does not change the forecast; it explains it.</p>
      <div className="modal-actions"><button className="button" onClick={onClose}>Cancel</button><button className="button primary" onClick={save} disabled={saving || !text.trim()}>{saving ? 'Saving…' : 'Record commentary'}</button></div>
    </Modal>
  );
}
