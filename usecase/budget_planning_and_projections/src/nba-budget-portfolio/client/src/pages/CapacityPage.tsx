import { useMemo } from 'react';
import { Skeleton } from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import { useQuery } from '../lib/query';
import { Heatmap, type HeatCell } from '../components/charts';
import { Empty, KpiCard, LoadingCards, QueryError } from '../components/common';
import { bn, num, pct } from '../lib/format';
import { useAppState } from '../lib/state';

export function CapacityPage({ scenarioName, scenarioSelect }: { scenarioName: string; scenarioSelect: React.ReactNode }) {
  const { scenarioId, dataVersion, drill, setDrill } = useAppState();
  const v = sql.string(dataVersion);
  const summary = useQuery('overview_summary', { scenario_id: sql.string(scenarioId), sector: sql.string('ALL'), data_version: v });
  const heat = useQuery('capacity_heatmap', { scenario_id: sql.string(scenarioId), data_version: v });
  const row = summary.data?.[0];
  const cells: HeatCell[] = useMemo(
    () => (heat.data ?? []).map((c) => ({
      categoryId: String(c.category_id), category: String(c.capacity_category), fy: String(c.financial_year), utilisation: num(c.utilisation_pct),
      baseline: num(c.baseline_utilisation_pct), status: String(c.status), unit: String(c.unit), gapValue: num(c.gap_value_aud_m),
    })),
    [heat.data],
  );
  const years = [...new Set(cells.map((c) => c.fy))].sort();
  const breaches = cells.filter((c) => c.utilisation > 100);
  const worst = [...breaches].sort((a, b) => b.utilisation - a.utilisation)[0];
  const selected = drill?.kind === 'capacity' ? `${drill.categoryId}|${drill.financialYear}` : undefined;

  return (
    <section className="page active" aria-labelledby="capacity-title">
      <div className="page-head">
        <div>
          <p className="eyebrow">Market capacity</p>
          <h1 id="capacity-title">Can the market deliver it?</h1>
          <p className="subtitle">Portfolio demand for twelve delivery inputs as a share of modelled supply. Select a cell to see the projects driving it and which of them could move.</p>
        </div>
        <div className="freshness"><strong>{row?.capacity_model_version ?? 'Capacity model'}</strong>{scenarioName}</div>
      </div>
      <div className="filters">{scenarioSelect}</div>
      {summary.loading && !row && <LoadingCards />}
      {summary.error && <QueryError message={`Capacity summary could not load: ${summary.error}`} />}
      {row && (
        <div className="grid kpis">
          <KpiCard label="Capacity breaches" value={String(breaches.length)} detail={breaches.length ? `input-years above 100% · worst ${worst?.category} ${worst?.fy}` : 'No input exceeds modelled supply'} />
          <KpiCard label="Peak demand / capacity" value={pct(row.peak_demand_capacity_pct)} detail={`${row.peak_fy} · ${row.peak_category}`} />
          <KpiCard label={`Peak capacity gap · ${row.peak_capacity_gap_fy}`} value={bn(row.peak_capacity_gap_aud_m)} detail={`${num(row.projects_affected)} heavy-user projects across ${num(row.programs_affected)} programs in breached years`} />
          <KpiCard
            label="Baseline gap resolvable by sequencing"
            value={row.resolvable_by_sequencing_aud_m === null ? '—' : bn(row.resolvable_by_sequencing_aud_m)}
            detail="Working baseline peak-year gap removed by capacity-aware sequencing, without cutting scope"
          />
        </div>
      )}
      <article className="card">
        <div className="card-head"><div><h2>Utilisation by delivery input and year</h2><p>Demand ÷ modelled available supply · ▲▼ change vs Working baseline · thresholds: constrained ≥90%, breach &gt;100%</p></div></div>
        {heat.loading && cells.length === 0 && <Skeleton className="table-skeleton" />}
        {heat.error && <QueryError message={`Capacity data could not load: ${heat.error}`} />}
        {!heat.loading && !heat.error && cells.length === 0 && <Empty>No capacity results for this scenario yet. It may still be recomputing.</Empty>}
        {cells.length > 0 && (
          <Heatmap cells={cells} years={years} selected={selected}
            onSelect={(c) => setDrill({ kind: 'capacity', financialYear: c.fy, categoryId: c.categoryId, categoryName: c.category, utilisation: c.utilisation })} />
        )}
      </article>
    </section>
  );
}
