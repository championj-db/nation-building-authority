import { useEffect, useMemo } from 'react';

import { sql } from '@databricks/appkit-ui/js';
import { useQuery } from '../lib/query';
import { ArrowLeft, X } from 'lucide-react';
import { PhasingChart } from './charts';
import { Empty, ListSkeleton, QueryError, StatusBadge, statusTone } from './common';
import { bn, date, money, months, num, pct, tone, yes } from '../lib/format';
import { useAppState, type Drill } from '../lib/state';

export function DrillDrawer() {
  const { drill, setDrill } = useAppState();
  useEffect(() => {
    if (!drill) return;
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setDrill(null);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drill, setDrill]);
  if (!drill) return null;
  return (
    <>
      <button className="drawer-scrim" aria-label="Close details" onClick={() => setDrill(null)} />
      <aside className="drawer" aria-label="Details">
        {drill.kind === 'program' && <ProgramDetail drill={drill} />}
        {drill.kind === 'project' && <ProjectDetail drill={drill} />}
        {drill.kind === 'capacity' && <CapacityDetail drill={drill} />}
      </aside>
    </>
  );
}

function DrawerHead({ eyebrow, title, back }: { eyebrow: string; title: string; back?: Drill }) {
  const { setDrill } = useAppState();
  return (
    <div className="drawer-head">
      <div>
        {back && <button className="link-button" onClick={() => setDrill(back)}><ArrowLeft size={14} /> Back</button>}
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
      </div>
      <button className="button icon-button" aria-label="Close details" onClick={() => setDrill(null)}><X size={18} /></button>
    </div>
  );
}

function ProgramDetail({ drill }: { drill: Extract<Drill, { kind: 'program' }> }) {
  const { scenarioId, dataVersion, setDrill } = useAppState();
  const projects = useQuery('program_projects', {
    program_id: sql.string(drill.id),
    scenario_id: sql.string(scenarioId),
    data_version: sql.string(dataVersion),
  });
  const rows = projects.data ?? [];
  const totals = rows.reduce((acc, r) => ({ plan: acc.plan + num(r.plan_aud_m), forecast: acc.forecast + num(r.forecast_aud_m) }), { plan: 0, forecast: 0 });
  const first = rows[0];
  return (
    <>
      <DrawerHead eyebrow={`Program · ${scenarioId === 'BASE' ? 'Working baseline' : scenarioId}`} title={drill.name} />
      {first && <p className="drawer-sub">{first.program_executive} · {first.delivery_agency}</p>}
      {projects.error && <QueryError message={`Projects could not load: ${projects.error}`} />}
      {projects.loading && <ListSkeleton rows={6} />}
      {rows.length > 0 && (
        <>
          <div className="stat-row">
            <div><span>Plan FY27–31</span><strong>{bn(totals.plan)}</strong></div>
            <div><span>Forecast</span><strong>{bn(totals.forecast)}</strong></div>
            <div><span>Variance</span><strong className={`delta ${tone(totals.forecast - totals.plan)}`}>{money(totals.forecast - totals.plan, true)}</strong></div>
            <div><span>Projects</span><strong>{rows.length}</strong></div>
          </div>
          <div className="table-wrap"><table className="compact"><thead><tr><th>Project</th><th>Gateway</th><th className="num">Forecast</th><th className="num">Variance</th><th className="num">Slip</th><th className="num">Confidence</th></tr></thead><tbody>
            {rows.map((r) => (
              <tr key={r.project_id} className="clickable-row" tabIndex={0} onClick={() => setDrill({ kind: 'project', id: String(r.project_id), name: String(r.project_name) })}
                onKeyDown={(e) => e.key === 'Enter' && setDrill({ kind: 'project', id: String(r.project_id), name: String(r.project_name) })}>
                <td><strong>{String(r.project_name).replace(`${drill.name} - `, '')}</strong><small className="table-subtitle">{r.jurisdiction} · {r.lifecycle_stage} · {r.schedule_flexibility}</small></td>
                <td><StatusBadge tone={statusTone(String(r.gateway_rating))}>{r.gateway_rating}</StatusBadge></td>
                <td className="num">{money(r.forecast_aud_m)}</td>
                <td className="num"><span className={`delta ${tone(r.variance_aud_m)}`}>{money(r.variance_aud_m, true)}</span></td>
                <td className="num">{months(r.slip_months)}</td>
                <td className="num">{pct(r.confidence_pct)}</td>
              </tr>
            ))}
          </tbody></table></div>
        </>
      )}
      {!projects.loading && !projects.error && rows.length === 0 && <Empty>No projects found for this program.</Empty>}
    </>
  );
}

function ProjectDetail({ drill }: { drill: Extract<Drill, { kind: 'project' }> }) {
  const { scenarioId, dataVersion } = useAppState();
  const params = { project_id: sql.string(drill.id), scenario_id: sql.string(scenarioId), data_version: sql.string(dataVersion) };
  const detail = useQuery('project_detail', params);
  const monthly = useQuery('project_monthly', params);
  const exposure = useQuery('project_exposure', params);
  const d = detail.data?.[0];
  const phasing = useMemo(
    () => (monthly.data ?? []).map((m) => ({ month: String(m.month), plan: num(m.plan_aud_m), forecast: num(m.forecast_aud_m), actual: num(m.actual_aud_m), isActual: yes(m.is_actual_month) })),
    [monthly.data],
  );
  const back: Drill | undefined = d ? { kind: 'program', id: String(d.program_id), name: String(d.program_name) } : undefined;
  return (
    <>
      <DrawerHead eyebrow={d ? `${d.program_name} · ${d.jurisdiction}` : 'Project'} title={drill.name} back={back} />
      {detail.error && <QueryError message={`Project could not load: ${detail.error}`} />}
      {detail.loading && <ListSkeleton rows={3} />}
      {d && (
        <>
          <p className="drawer-sub">{d.delivery_agency} · {d.delivery_model} · {d.lifecycle_stage} · priority tier {d.priority_tier} · {d.schedule_flexibility}</p>
          <div className="stat-row">
            <div><span>EAC (forecast)</span><strong>{money(d.eac_forecast_aud_m)}</strong><small>plan {money(d.eac_plan_aud_m)}</small></div>
            <div><span>Spent to date</span><strong>{money(d.actual_to_date_aud_m)}</strong><small>{pct(num(d.percent_complete) * (num(d.percent_complete) <= 1 ? 100 : 1))} complete</small></div>
            <div><span>Finish</span><strong>{date(d.forecast_finish)}</strong><small>{months(d.slip_months)} vs plan</small></div>
            <div><span>Confidence</span><strong>{pct(d.confidence_pct)}</strong><small>Gateway {num(d.base_confidence_pct).toFixed(0)}% less {num(d.capacity_penalty_pct).toFixed(0)} pts capacity</small></div>
          </div>
        </>
      )}
      <h3 className="drawer-section">Monthly phasing</h3>
      {monthly.loading && <ListSkeleton rows={2} />}
      {monthly.error && <QueryError message={`Phasing could not load: ${monthly.error}`} />}
      {phasing.length > 0 && <PhasingChart rows={phasing} />}
      {d && (
        <>
          <h3 className="drawer-section">Forecast drivers (recorded)</h3>
          <dl className="driver-list">
            <div><dt>Approved schedule change</dt><dd>{months(d.slip_months)} · delay cost {money(d.delay_cost_aud_m)}</dd></div>
            <div><dt>Approved scope change</dt><dd>{money(d.approved_scope_aud_m, true)}</dd></div>
            <div><dt>Packaging change</dt><dd>{money(d.approved_packaging_aud_m, true)}</dd></div>
            <div><dt>Cost performance (last 12 months)</dt><dd>{num(d.cost_performance_pct) > 0 ? '+' : ''}{num(d.cost_performance_pct).toFixed(1)}% actual vs explained spend</dd></div>
            <div><dt>Pending change requests</dt><dd>{num(d.pending_changes)}</dd></div>
            <div><dt>Latest Gateway</dt><dd>{d.latest_gate_name} · <StatusBadge tone={statusTone(String(d.gateway_rating))}>{d.gateway_rating}</StatusBadge> · {date(d.gateway_report_date)}</dd></div>
            <div><dt>Cost estimate</dt><dd>P50 {money(d.tec_p50_aud_m)} · P90 {money(d.tec_p90_aud_m)} · BCR {num(d.bcr).toFixed(1)}</dd></div>
          </dl>
        </>
      )}
      <h3 className="drawer-section">Exposure to constrained inputs</h3>
      {exposure.loading && <ListSkeleton rows={2} />}
      {exposure.data && exposure.data.length === 0 && <Empty>No exposure to constrained inputs in this scenario.</Empty>}
      {exposure.data && exposure.data.length > 0 && (
        <div className="table-wrap"><table className="compact"><thead><tr><th>Year</th><th>Input</th><th className="num">Utilisation</th><th className="num">Share of demand</th><th className="num">Attributed gap</th></tr></thead><tbody>
          {exposure.data.map((e) => (
            <tr key={`${e.financial_year}-${e.capacity_category}`}><td>{e.financial_year}</td><td>{e.capacity_category}</td>
              <td className="num"><span className={num(e.utilisation_pct) > 100 ? 'delta bad' : ''}>{pct(e.utilisation_pct)}</span></td>
              <td className="num">{pct(e.share_of_demand_pct, 1)}</td><td className="num">{money(e.gap_value_aud_m)}</td></tr>
          ))}
        </tbody></table></div>
      )}
    </>
  );
}

function CapacityDetail({ drill }: { drill: Extract<Drill, { kind: 'capacity' }> }) {
  const { scenarioId, dataVersion, setDrill } = useAppState();
  const drivers = useQuery('capacity_drivers', {
    scenario_id: sql.string(scenarioId),
    financial_year: sql.string(drill.financialYear),
    category_id: sql.string(drill.categoryId),
    data_version: sql.string(dataVersion),
  });
  const rows = drivers.data ?? [];
  const deferrable = rows.filter((r) => r.schedule_flexibility === 'Deferrable');
  return (
    <>
      <DrawerHead eyebrow={`${drill.financialYear} · ${pct(drill.utilisation)} of modelled supply`} title={drill.categoryName} />
      <p className="drawer-sub">Projects ranked by share of portfolio demand for this input. Deferrable projects are the sequencer's candidates, lowest priority tier first.</p>
      {drivers.error && <QueryError message={`Drivers could not load: ${drivers.error}`} />}
      {drivers.loading && <ListSkeleton rows={6} />}
      {rows.length > 0 && (
        <>
          <div className="stat-row">
            <div><span>Top 5 share</span><strong>{pct(rows.slice(0, 5).reduce((a, r) => a + num(r.share_of_demand_pct), 0), 1)}</strong></div>
            <div><span>Deferrable in top 15</span><strong>{deferrable.length}</strong></div>
            <div><span>Attributed gap</span><strong>{money(rows.reduce((a, r) => a + num(r.gap_value_aud_m), 0))}</strong></div>
          </div>
          <div className="table-wrap"><table className="compact"><thead><tr><th>Project</th><th>Flexibility</th><th className="num">Spend</th><th className="num">Share</th><th className="num">Gap</th><th className="num">Confidence</th></tr></thead><tbody>
            {rows.map((r) => (
              <tr key={r.project_id} className="clickable-row" tabIndex={0} onClick={() => setDrill({ kind: 'project', id: String(r.project_id), name: String(r.project_name) })}
                onKeyDown={(e) => e.key === 'Enter' && setDrill({ kind: 'project', id: String(r.project_id), name: String(r.project_name) })}>
                <td><strong>{r.project_name}</strong><small className="table-subtitle">{r.program_name} · tier {r.priority_tier} · {r.region_type}</small></td>
                <td><StatusBadge tone={r.schedule_flexibility === 'Deferrable' ? 'good' : 'neutral'}>{r.schedule_flexibility}</StatusBadge></td>
                <td className="num">{money(r.spend_aud_m)}</td>
                <td className="num">{pct(r.share_of_demand_pct, 1)}</td>
                <td className="num">{money(r.gap_value_aud_m)}</td>
                <td className="num">{pct(r.confidence_pct)}</td>
              </tr>
            ))}
          </tbody></table></div>
        </>
      )}
    </>
  );
}
