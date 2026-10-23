import { useMemo, useState } from 'react';
import { Skeleton } from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import { useQuery } from '../lib/query';
import { ChevronRight } from 'lucide-react';
import { TrendChart } from '../components/charts';
import { Empty, KpiCard, ListSkeleton, LoadingCards, QueryError, StatusBadge, statusTone } from '../components/common';
import { bn, date, num, pct, tone, yes } from '../lib/format';
import { useAppState } from '../lib/state';
import type { PageId } from '../App';

export const SECTORS = [
  ['ALL', 'National portfolio'],
  ['Transport', 'Transport'],
  ['Energy', 'Energy'],
  ['Water', 'Water'],
  ['Social', 'Social infrastructure'],
] as const;

export function OverviewPage({ scenarios, onNavigate }: { scenarios: Array<{ id: string; name: string }>; onNavigate: (page: PageId) => void }) {
  const { scenarioId, setScenarioId, dataVersion, setDrill } = useAppState();
  const [sector, setSector] = useState('ALL');
  const [priceBasis, setPriceBasis] = useState<'nominal' | 'real'>('nominal');
  const v = sql.string(dataVersion);
  const summary = useQuery('overview_summary', { scenario_id: sql.string(scenarioId), sector: sql.string(sector), data_version: v });
  const series = useQuery('overview_timeseries', { scenario_id: sql.string(scenarioId), sector: sql.string(sector), price_basis: sql.string(priceBasis), data_version: v });
  const exceptions = useQuery('priority_exceptions', { sector: sql.string(sector), data_version: v });
  const attention = useQuery('portfolio_attention', { sector: sql.string(sector), data_version: v });
  const row = summary.data?.[0];
  const points = series.data ?? [];
  const labels = points.map((p) => String(p.financial_year));
  const unit = priceBasis === 'real' ? 'real FY27 $bn' : 'nominal $bn';
  const all = sector === 'ALL';

  const headline = useMemo(() => {
    if (!all) return `${sector} forecast against endorsed plan`;
    if (points.length === 0) return 'Plan, forecast and delivery capacity';
    // A gap under $250m is inside model precision, so it does not count as exceeding capacity.
    const over = points.filter((p) => num(p.capacity_gap_aud_bn) >= 0.25);
    if (over.length === 0) return 'Forecast is within modelled delivery capacity';
    const peak = over.reduce((a, b) => (num(b.capacity_gap_aud_bn) > num(a.capacity_gap_aud_bn) ? b : a));
    const years = over.length > 1 ? `${over[0].financial_year}–${over[over.length - 1].financial_year}` : String(over[0].financial_year);
    return `Forecast exceeds what the market can deliver in ${years}; ${String(peak.binding_category).toLowerCase()} binds`;
  }, [points, all, sector]);

  const scenarioName = scenarios.find((s) => s.id === scenarioId)?.name ?? scenarioId;
  return (
    <section className="page active" aria-labelledby="overview-title">
      <div className="page-head">
        <div>
          <p className="eyebrow">Portfolio overview</p>
          <h1 id="overview-title">National infrastructure portfolio · FY27–31</h1>
          <p className="subtitle">Funding, delivery capacity and forecast confidence across the active portfolio.</p>
        </div>
        <div className="freshness">
          <strong>{row ? `Forecast as at ${date(row.as_of_date)}` : 'Loading portfolio data'}</strong>
          {row ? <>Actuals through {date(row.actuals_through)} · {row.plan_version} · {row.capacity_model_version}<br /><StatusBadge tone="warn">{row.figure_status} figures</StatusBadge> <span className="mono-small">{row.run_id}</span></> : 'Synthetic portfolio, capacity and actuals'}
        </div>
      </div>
      <div className="filters" aria-label="Portfolio filters">
        <label className="sr-only" htmlFor="sector-filter">Portfolio</label>
        <select id="sector-filter" className="select" value={sector} onChange={(event) => setSector(event.target.value)}>
          {SECTORS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <label className="sr-only" htmlFor="scenario-filter">Scenario</label>
        <select id="scenario-filter" className="select" value={scenarioId} onChange={(event) => setScenarioId(event.target.value)}>
          {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <label className="sr-only" htmlFor="price-filter">Price basis</label>
        <select id="price-filter" className="select" value={priceBasis} onChange={(event) => setPriceBasis(event.target.value as 'nominal' | 'real')}>
          <option value="nominal">Nominal $bn</option>
          <option value="real">Real FY27 $bn</option>
        </select>
      </div>

      {summary.loading && !row && <LoadingCards />}
      {summary.error && <QueryError message={`Portfolio metrics could not load: ${summary.error}`} />}
      {row && (
        <div className="grid kpis">
          <KpiCard
            label={`${all ? 'Forecast' : `${sector} forecast`} · ${row.horizon_label}`}
            value={bn(priceBasis === 'real' ? row.approved_portfolio_real_aud_m : row.approved_portfolio_aud_m)}
            detail={<><strong className={`delta ${tone(row.vs_endorsed_plan_aud_m)}`}>{bn(row.vs_endorsed_plan_aud_m, true)}</strong> vs {bn(row.endorsed_plan_aud_m)} endorsed{all && row.forecast_p10_aud_m !== null && <><br />P10–P90 {bn(row.forecast_p10_aud_m)}–{bn(row.forecast_p90_aud_m)}</>}</>}
          />
          <KpiCard
            label={`Peak capacity gap · ${row.peak_capacity_gap_fy}`}
            value={bn(row.peak_capacity_gap_aud_m)}
            detail={<>{num(row.peak_capacity_gap_aud_m) > 0 ? <StatusBadge tone="risk">Spend the market cannot deliver</StatusBadge> : <StatusBadge tone="good">Within capacity</StatusBadge>}</>}
            onClick={() => onNavigate('capacity')}
          />
          <KpiCard
            label="Active projects"
            value={String(num(row.active_projects))}
            detail={<><strong>{num(row.attention_projects)}</strong> outside tolerance or flagged for executive attention</>}
            onClick={() => onNavigate('variance')}
          />
          <KpiCard label="Forecast confidence" value={pct(row.forecast_confidence_pct)} detail="Gateway confidence less exposure to breached inputs, weighted by spend" />
        </div>
      )}

      <div className="grid two-one">
        <article className="card chart-card">
          <div className="card-head"><div><h2>{headline}</h2><p>{scenarioName} · plan, forecast{all ? ', deliverable capacity and P10–P90 range' : ''} · {unit}</p></div></div>
          {series.loading && points.length === 0 && <Skeleton className="chart-skeleton" />}
          {series.error && <QueryError message={`Expenditure series could not load: ${series.error}`} />}
          {!series.loading && !series.error && points.length === 0 && <Empty>No expenditure data matches these filters.</Empty>}
          {points.length > 0 && (
            <TrendChart
              ariaLabel="Plan, forecast and deliverable capacity by financial year"
              labels={labels}
              series={[
                { key: 'forecast', label: 'Forecast', values: points.map((p) => num(p.forecast_aud_bn)), className: 'forecast' },
                { key: 'plan', label: 'Endorsed plan', values: points.map((p) => num(p.plan_aud_bn)), className: 'plan', dashed: true },
                ...(all ? [{ key: 'capacity', label: 'Deliverable capacity', values: points.map((p) => (p.capacity_aud_bn === null ? null : num(p.capacity_aud_bn))), className: 'capacity' }] : []),
              ]}
              band={all && priceBasis === 'nominal' ? { low: points.map((p) => (p.p10_aud_bn === null ? null : num(p.p10_aud_bn))), high: points.map((p) => (p.p90_aud_bn === null ? null : num(p.p90_aud_bn))), label: 'P10–P90' } : undefined}
              gapBetween={all ? { over: 'forecast', under: 'capacity' } : undefined}
            />
          )}
        </article>

        <article className="card">
          <div className="card-head"><div><h2>Priority exceptions</h2><p>Ranked by financial and delivery exposure · select to open</p></div></div>
          {exceptions.loading && !exceptions.data && <ListSkeleton />}
          {exceptions.error && <QueryError message={`Exceptions could not load: ${exceptions.error}`} />}
          {exceptions.data?.length === 0 && <Empty>No open exceptions for this portfolio.</Empty>}
          <div className="exception-list">
            {exceptions.data?.map((item) => (
              <button className="exception clickable" key={String(item.exception_id)} onClick={() => setDrill({ kind: 'program', id: String(item.program_id), name: String(item.program_name) })}>
                <div className="exception-top">
                  <strong>{item.program_name}</strong>
                  <span className={`delta ${item.delta_unit === 'AUD m' ? tone(item.delta_value) : 'bad'}`}>{item.delta_unit === 'AUD m' ? bn(item.delta_value, true) : `+${num(item.delta_value).toFixed(0)} mo`}</span>
                </div>
                <p><StatusBadge>{item.exception_type}</StatusBadge> {item.description}</p>
              </button>
            ))}
          </div>
        </article>
      </div>

      <article className="card attention-card">
        <div className="card-head">
          <div><h2>Portfolio attention list</h2><p>Programs flagged for executive attention first, then by cost growth · select a program for its projects</p></div>
          <button className="button" onClick={() => onNavigate('scenarios')}>Compare scenarios <ChevronRight size={16} /></button>
        </div>
        {attention.loading && !attention.data && <Skeleton className="table-skeleton" />}
        {attention.error && <QueryError message={`Attention list could not load: ${attention.error}`} />}
        {attention.data?.length === 0 && <Empty>No programs match this portfolio filter.</Empty>}
        {attention.data && attention.data.length > 0 && (
          <div className="table-wrap"><table><thead><tr><th>Program</th><th>Gateway</th><th className="num">Plan FY27–31</th><th className="num">Forecast</th><th className="num">Variance</th><th className="num">Slip</th><th>Binding input</th><th className="num">Confidence</th></tr></thead><tbody>
            {attention.data.map((item) => (
              <tr key={String(item.program_id)} className="clickable-row" tabIndex={0}
                onClick={() => setDrill({ kind: 'program', id: String(item.program_id), name: String(item.program_name) })}
                onKeyDown={(e) => e.key === 'Enter' && setDrill({ kind: 'program', id: String(item.program_id), name: String(item.program_name) })}>
                <td><div className="project"><i className={`project-mark sector-${String(item.sector).toLowerCase()}`} /><div><strong>{item.program_name}</strong><small>{item.sector} · {num(item.projects)} projects{yes(item.requires_attention) ? ' · executive attention' : ''}</small></div></div></td>
                <td><StatusBadge tone={statusTone(String(item.assurance_rating))}>{item.assurance_rating}</StatusBadge></td>
                <td className="num">{bn(item.plan_aud_m)}</td>
                <td className="num">{bn(item.forecast_aud_m)}</td>
                <td className="num"><span className={`delta ${tone(item.variance_aud_m)}`}>{bn(item.variance_aud_m, true)}</span>{yes(item.outside_tolerance) && <small className="table-subtitle">outside tolerance</small>}</td>
                <td className="num">{num(item.max_slip_months) > 0 ? `+${num(item.max_slip_months)} mo` : '—'}</td>
                <td>{item.capacity_driver}{num(item.capacity_gap_aud_m) > 0.5 && <small className="table-subtitle">{bn(item.capacity_gap_aud_m)} attributed gap</small>}</td>
                <td className="num">{pct(item.confidence_pct)}</td>
              </tr>
            ))}
          </tbody></table></div>
        )}
      </article>
    </section>
  );
}
