import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  AlertDescription,
  GenieChat,
  LineChart,
  Skeleton,
  useAnalyticsQuery,
} from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import {
  BarChart3,
  Bot,
  Check,
  ChevronRight,
  CircleGauge,
  Download,
  FileCheck2,
  LayoutDashboard,
  Menu,
  Plus,
  Scale,
  SlidersHorizontal,
  X,
} from 'lucide-react';

type PageId = 'overview' | 'scenarios' | 'capacity' | 'variance' | 'assurance';
type ScenarioId = 'BASE' | 'CAP_BAL' | 'ACCEL' | 'ENDORSED';
type PriceBasis = 'nominal' | 'real';

type Identity = {
  email?: string | null;
  user?: string | null;
};

type PortfolioAttentionRow = {
  rank: number;
  program_name: string;
  sector: string;
  projects: number;
  assurance_rating: string;
  plan_aud_m: number;
  forecast_aud_m: number;
  variance_aud_m: number;
  capacity_driver: string;
  confidence_pct: number;
  requires_attention: boolean;
};

const NAV_ITEMS: Array<{
  id: PageId;
  label: string;
  group: 'Planning' | 'Governance';
  icon: typeof LayoutDashboard;
}> = [
  { id: 'overview', label: 'Portfolio overview', group: 'Planning', icon: LayoutDashboard },
  { id: 'scenarios', label: 'Scenario studio', group: 'Planning', icon: SlidersHorizontal },
  { id: 'capacity', label: 'Market capacity', group: 'Planning', icon: BarChart3 },
  { id: 'variance', label: 'Variance & actuals', group: 'Planning', icon: CircleGauge },
  { id: 'assurance', label: 'Assurance register', group: 'Governance', icon: FileCheck2 },
];

const SCENARIO_LABELS: Record<ScenarioId, string> = {
  BASE: 'Working baseline',
  CAP_BAL: 'Capacity balanced',
  ACCEL: 'Accelerated delivery',
  ENDORSED: 'Endorsed plan',
};

const SECTORS = [
  ['ALL', 'National portfolio'],
  ['Transport', 'Transport'],
  ['Energy', 'Energy'],
  ['Water', 'Water'],
  ['Social', 'Social infrastructure'],
] as const;

function numberValue(value: number | string | null | undefined): number {
  return Number(value ?? 0);
}

function currencyBn(valueAudM: number | string | null | undefined, signed = false): string {
  const value = numberValue(valueAudM) / 1000;
  const sign = signed && value > 0 ? '+' : '';
  return `${sign}$${value.toFixed(1)}bn`;
}

function currencyBnCompact(valueAudM: number | string | null | undefined): string {
  const value = numberValue(valueAudM) / 1000;
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}$${Math.abs(value).toFixed(1)}bn`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return 'Not available';
  return new Intl.DateTimeFormat('en-AU', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(new Date(`${value.slice(0, 10)}T00:00:00`));
}

function initials(email?: string | null): string {
  if (!email) return 'AP';
  return email
    .split('@')[0]
    .split(/[._-]/)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
}

function QueryError({ message }: { message: string }) {
  return (
    <Alert variant="destructive" className="query-alert">
      <AlertDescription>{message} Refresh the view or try a different filter.</AlertDescription>
    </Alert>
  );
}

function LoadingCards({ count = 4 }: { count?: number }) {
  return (
    <div className="grid kpis" aria-label="Loading portfolio metrics">
      {Array.from({ length: count }, (_, index) => (
        <div className="card skeleton-card" key={index}>
          <Skeleton className="skeleton-label" />
          <Skeleton className="skeleton-value" />
          <Skeleton className="skeleton-detail" />
        </div>
      ))}
    </div>
  );
}

function StatusBadge({ children, tone = 'neutral' }: { children: React.ReactNode; tone?: 'neutral' | 'risk' | 'good' | 'warn' }) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

function App() {
  const [page, setPage] = useState<PageId>('overview');
  const [scenarioId, setScenarioId] = useState<ScenarioId>('BASE');
  const [sector, setSector] = useState('ALL');
  const [priceBasis, setPriceBasis] = useState<PriceBasis>('nominal');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [scenarioModalOpen, setScenarioModalOpen] = useState(false);
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [draftName, setDraftName] = useState('FY29 capacity response');
  const [draftPurpose, setDraftPurpose] = useState('');
  const [sessionDraft, setSessionDraft] = useState<string | null>(null);

  const scenarioLabel = sessionDraft && scenarioId === 'BASE' ? sessionDraft : SCENARIO_LABELS[scenarioId];

  useEffect(() => {
    fetch('/api/whoami')
      .then((response) => (response.ok ? response.json() : null))
      .then(setIdentity)
      .catch(() => setIdentity(null));
  }, []);

  const navigate = (nextPage: PageId) => {
    setPage(nextPage);
    setMobileNavOpen(false);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const createDraft = () => {
    const cleanName = draftName.trim();
    if (!cleanName) return;
    setSessionDraft(cleanName);
    setScenarioId('BASE');
    setScenarioModalOpen(false);
    navigate('scenarios');
  };

  return (
    <div className="shell">
      <Sidebar activePage={page} open={mobileNavOpen} onNavigate={navigate} onClose={() => setMobileNavOpen(false)} />

      <main className="main">
        <header className="topbar">
          <div className="actions topbar-context">
            <button className="button icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}>
              <Menu size={19} />
            </button>
            <span className="crumb">FY27–31 portfolio / <strong>{scenarioLabel}</strong></span>
          </div>
          <div className="actions">
            <button className="button desktop-action" onClick={() => window.print()}>
              <Download size={16} /> Export briefing
            </button>
            <button className="button primary desktop-action" onClick={() => setScenarioModalOpen(true)}>
              <Plus size={16} /> Create scenario
            </button>
            <div className="avatar" title={identity?.email ? `Signed in as ${identity.email}` : 'Signed in'}>
              {initials(identity?.email)}
            </div>
          </div>
        </header>

        <div className="content">
          {page === 'overview' && (
            <OverviewPage
              scenarioId={scenarioId}
              sector={sector}
              priceBasis={priceBasis}
              onScenarioChange={setScenarioId}
              onSectorChange={setSector}
              onPriceBasisChange={setPriceBasis}
              onViewScenarios={() => navigate('scenarios')}
            />
          )}
          {page === 'scenarios' && (
            <ScenariosPage scenarioId={scenarioId} sessionDraft={sessionDraft} onScenarioChange={setScenarioId} />
          )}
          {page === 'capacity' && <CapacityPage key={scenarioId} scenarioId={scenarioId} />}
          {page === 'variance' && <VariancePage onReviewAssumptions={() => navigate('assurance')} />}
          {page === 'assurance' && <AssurancePage />}
        </div>
      </main>

      <button className="assistant-launcher" onClick={() => setAssistantOpen(true)} aria-expanded={assistantOpen}>
        <Bot size={17} /> Ask portfolio data
      </button>
      <GeniePanel open={assistantOpen} identity={identity} onClose={() => setAssistantOpen(false)} />
      {scenarioModalOpen && (
        <ScenarioModal
          name={draftName}
          purpose={draftPurpose}
          onNameChange={setDraftName}
          onPurposeChange={setDraftPurpose}
          onClose={() => setScenarioModalOpen(false)}
          onCreate={createDraft}
        />
      )}
    </div>
  );
}

function Sidebar({ activePage, open, onNavigate, onClose }: { activePage: PageId; open: boolean; onNavigate: (page: PageId) => void; onClose: () => void }) {
  return (
    <>
      {open && <button className="nav-scrim" aria-label="Close navigation" onClick={onClose} />}
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-mark">NBA</div>
          <div><strong>Portfolio Command</strong><span>Nation Building Authority</span></div>
          <button className="button icon-button nav-close" aria-label="Close navigation" onClick={onClose}><X size={18} /></button>
        </div>
        {(['Planning', 'Governance'] as const).map((group) => (
          <div key={group}>
            <p className="nav-label">{group}</p>
            <nav className="nav" aria-label={`${group} navigation`}>
              {NAV_ITEMS.filter((item) => item.group === group).map((item) => {
                const Icon = item.icon;
                return (
                  <button className={activePage === item.id ? 'active' : ''} key={item.id} onClick={() => onNavigate(item.id)}>
                    <Icon size={18} /> {item.label}
                  </button>
                );
              })}
            </nav>
          </div>
        ))}
        <div className="sidebar-meta"><strong>Working figures</strong>Protected · Unity Catalog<br />Service principal governed</div>
      </aside>
    </>
  );
}

function OverviewPage({
  scenarioId,
  sector,
  priceBasis,
  onScenarioChange,
  onSectorChange,
  onPriceBasisChange,
  onViewScenarios,
}: {
  scenarioId: ScenarioId;
  sector: string;
  priceBasis: PriceBasis;
  onScenarioChange: (value: ScenarioId) => void;
  onSectorChange: (value: string) => void;
  onPriceBasisChange: (value: PriceBasis) => void;
  onViewScenarios: () => void;
}) {
  const summary = useAnalyticsQuery('overview_summary', {
    scenario_id: sql.string(scenarioId),
    sector: sql.string(sector),
  });
  const timeseries = useAnalyticsQuery('overview_timeseries', {
    scenario_id: sql.string(scenarioId),
    sector: sql.string(sector),
    price_basis: sql.string(priceBasis),
  });
  const exceptions = useAnalyticsQuery('priority_exceptions', { sector: sql.string(sector) });
  const attention = useAnalyticsQuery('portfolio_attention', { sector: sql.string(sector) });
  const row = summary.data?.[0];
  const chartData = useMemo(
    () => (timeseries.data ?? []).map((item) => ({
      financial_year: item.financial_year,
      Forecast: numberValue(item.forecast_aud_bn),
      Plan: numberValue(item.plan_aud_bn),
      Capacity: numberValue(item.capacity_aud_bn),
    })),
    [timeseries.data],
  );

  return (
    <section className="page active" aria-labelledby="overview-title">
      <div className="page-head">
        <div><p className="eyebrow">Portfolio overview · synthetic demonstration</p><h1 id="overview-title">National infrastructure portfolio · FY27–31</h1><p className="subtitle">Review funding, delivery capacity and forecast confidence across the active portfolio.</p></div>
        <div className="freshness"><strong>{row ? `Refreshed ${formatDate(row.as_of_date)}` : 'Refreshing portfolio data'}</strong>{row ? `Actuals through ${formatDate(row.actuals_through)} · ${row.figure_status} figures` : 'Synthetic portfolio, capacity and actuals'}</div>
      </div>
      <div className="notice"><strong>All values in this application are synthetic.</strong><span>Assumptions are versioned and traceable to scenario inputs.</span></div>
      <div className="filters" aria-label="Portfolio filters">
        <label className="sr-only" htmlFor="sector-filter">Portfolio</label>
        <select id="sector-filter" className="select" value={sector} onChange={(event) => onSectorChange(event.target.value)}>
          {SECTORS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <label className="sr-only" htmlFor="scenario-filter">Scenario</label>
        <select id="scenario-filter" className="select" value={scenarioId} onChange={(event) => onScenarioChange(event.target.value as ScenarioId)}>
          {Object.entries(SCENARIO_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <label className="sr-only" htmlFor="price-filter">Price basis</label>
        <select id="price-filter" className="select" value={priceBasis} onChange={(event) => onPriceBasisChange(event.target.value as PriceBasis)}>
          <option value="nominal">Nominal $bn</option>
          <option value="real">Real FY27 $bn</option>
        </select>
      </div>

      {summary.loading && <LoadingCards />}
      {summary.error && <QueryError message={`Portfolio metrics could not load: ${summary.error}`} />}
      {row && (
        <div className="grid kpis">
          <KpiCard label={`${sector === 'ALL' ? 'Approved portfolio' : `${sector} forecast`} · ${row.horizon_label}`} value={currencyBn(priceBasis === 'real' ? row.approved_portfolio_real_aud_m : row.approved_portfolio_aud_m)} detail={<><strong>{currencyBn(row.vs_endorsed_plan_aud_m, true)}</strong> vs endorsed plan</>} />
          <KpiCard label={`Peak capacity gap · ${row.peak_capacity_gap_fy}`} value={currencyBn(row.peak_capacity_gap_aud_m)} detail={<StatusBadge tone="risk">Deliverability risk</StatusBadge>} />
          <KpiCard label="Active projects" value={String(numberValue(row.active_projects))} detail={<><strong>{numberValue(row.attention_projects)}</strong> require executive attention</>} />
          <KpiCard label="Forecast confidence" value={`${numberValue(row.forecast_confidence_pct).toFixed(0)}%`} detail="Weighted by assurance and horizon spend" />
        </div>
      )}

      <div className="grid two-one">
        <article className="card chart-card">
          <div className="card-head"><div><h2>Forecast exceeds delivery capacity from FY28</h2><p>Plan, forecast and modelled capacity · {priceBasis === 'real' ? 'real FY27' : 'nominal'} $bn</p></div><StatusBadge>FY27–31</StatusBadge></div>
          {timeseries.loading && <Skeleton className="chart-skeleton" />}
          {timeseries.error && <QueryError message={`Expenditure series could not load: ${timeseries.error}`} />}
          {!timeseries.loading && !timeseries.error && chartData.length === 0 && <p className="empty-state">No expenditure data matches these filters.</p>}
          {chartData.length > 0 && (
            <div className="chart-frame">
              <LineChart data={chartData} xKey="financial_year" yKey={sector === 'ALL' ? ['Forecast', 'Plan', 'Capacity'] : ['Forecast', 'Plan']} />
            </div>
          )}
          <div className="legend"><span><i className="swatch forecast" />Forecast</span><span><i className="swatch plan" />Plan</span>{sector === 'ALL' && <span><i className="swatch capacity" />Modelled capacity</span>}</div>
        </article>

        <article className="card">
          <div className="card-head"><div><h2>Priority exceptions</h2><p>Ranked by financial and delivery exposure</p></div><StatusBadge tone="risk">Open</StatusBadge></div>
          {exceptions.loading && <ListSkeleton />}
          {exceptions.error && <QueryError message={`Exceptions could not load: ${exceptions.error}`} />}
          {!exceptions.loading && !exceptions.error && exceptions.data?.length === 0 && <p className="empty-state">No open exceptions for this portfolio.</p>}
          <div className="exception-list">
            {exceptions.data?.map((item) => (
              <div className="exception" key={`${item.rank}-${item.program_name}`}>
                <div className="exception-top"><strong>{item.program_name}</strong><span className={`delta ${numberValue(item.delta_value) >= 0 ? 'bad' : 'good'}`}>{item.delta_unit === 'AUD m' ? currencyBnCompact(item.delta_value) : `+${numberValue(item.delta_value).toFixed(0)} mo`}</span></div>
                <p>{item.description}</p>
              </div>
            ))}
          </div>
        </article>
      </div>

      <article className="card attention-card">
        <div className="card-head"><div><h2>Portfolio attention list</h2><p>Programs with material cost, schedule or capacity exposure</p></div><button className="button" onClick={onViewScenarios}>Compare scenarios <ChevronRight size={16} /></button></div>
        {attention.loading && <Skeleton className="table-skeleton" />}
        {attention.error && <QueryError message={`Attention list could not load: ${attention.error}`} />}
        {!attention.loading && !attention.error && attention.data?.length === 0 && <p className="empty-state">No programs match this portfolio filter.</p>}
        {attention.data && attention.data.length > 0 && <AttentionTable rows={attention.data} />}
      </article>
    </section>
  );
}

function KpiCard({ label, value, detail }: { label: string; value: string; detail: React.ReactNode }) {
  return <article className="card"><p className="kpi-label">{label}</p><div className="kpi-value">{value}</div><p className="kpi-detail">{detail}</p></article>;
}

function ListSkeleton() {
  return <div className="exception-list">{Array.from({ length: 4 }, (_, index) => <Skeleton className="list-skeleton" key={index} />)}</div>;
}

function AttentionTable({ rows }: { rows: PortfolioAttentionRow[] }) {
  return (
    <div className="table-wrap"><table><thead><tr><th>Program</th><th>Sector</th><th>Assurance</th><th className="num">Plan FY27–31</th><th className="num">Forecast</th><th className="num">Variance</th><th>Capacity driver</th></tr></thead><tbody>
      {rows.map((item) => (
        <tr key={item.program_name}><td><div className="project"><i className={`project-mark sector-${item.sector.toLowerCase()}`} /><div><strong>{item.program_name}</strong><small>Program · {numberValue(item.projects)} projects</small></div></div></td><td>{item.sector}</td><td><StatusBadge tone={item.assurance_rating.includes('Red') ? 'risk' : item.assurance_rating === 'Green' ? 'good' : 'warn'}>{item.assurance_rating}</StatusBadge></td><td className="num">{currencyBn(item.plan_aud_m)}</td><td className="num">{currencyBn(item.forecast_aud_m)}</td><td className="num"><span className={`delta ${numberValue(item.variance_aud_m) > 0 ? 'bad' : 'good'}`}>{currencyBnCompact(item.variance_aud_m)}</span></td><td>{item.capacity_driver}</td></tr>
      ))}
    </tbody></table></div>
  );
}

function ScenariosPage({ scenarioId, sessionDraft, onScenarioChange }: { scenarioId: ScenarioId; sessionDraft: string | null; onScenarioChange: (value: ScenarioId) => void }) {
  const summaries = useAnalyticsQuery('scenario_summary', {});
  const comparison = useAnalyticsQuery('scenario_comparison', { scenario_id: sql.string(scenarioId) });
  const selected = summaries.data?.find((item) => item.scenario_id === scenarioId);
  const maxForecast = Math.max(...(comparison.data ?? []).map((item) => numberValue(item.forecast_aud_m)), 1);

  return (
    <section className="page active" aria-labelledby="scenario-title">
      <div className="page-head"><div><p className="eyebrow">Scenario studio</p><h1 id="scenario-title">Allocation scenario comparison</h1><p className="subtitle">Compare project timing, funding limits and capacity assumptions with the governed working baseline.</p></div><div className="freshness"><strong>{summaries.data?.length ?? 0} governed scenarios{sessionDraft ? ' · 1 session draft' : ''}</strong>Baseline locked · session drafts are not persisted</div></div>
      {summaries.error && <QueryError message={`Scenarios could not load: ${summaries.error}`} />}
      <div className="scenario-strip">
        {summaries.loading && Array.from({ length: 3 }, (_, index) => <Skeleton className="scenario-skeleton" key={index} />)}
        {summaries.data?.filter((item) => item.scenario_id !== 'ENDORSED').map((item) => (
          <button className={`scenario-card ${scenarioId === item.scenario_id ? 'active' : ''}`} key={item.scenario_id} onClick={() => onScenarioChange(item.scenario_id as ScenarioId)}>
            <strong>{item.scenario_name}</strong><span>{currencyBn(item.total_forecast_aud_m)} · {numberValue(item.forecast_confidence_pct).toFixed(0)}% confidence · {numberValue(item.capacity_breaches)} capacity breaches</span>
          </button>
        ))}
      </div>
      {sessionDraft && <div className="notice session-notice"><strong>{sessionDraft}</strong><span>Session-only draft created from the working baseline · reload to discard</span></div>}
      <div className="grid two-one">
        <article className="card"><div className="card-head"><div><h2>Scenario impact by year</h2><p>Selected scenario forecast · nominal $bn</p></div>{selected && <StatusBadge>{selected.status} v{numberValue(selected.version)}</StatusBadge>}</div>
          {comparison.loading && <ListSkeleton />}
          {comparison.error && <QueryError message={`Scenario comparison could not load: ${comparison.error}`} />}
          <div className="bars">{comparison.data?.map((item) => <DataBar key={item.financial_year} label={item.financial_year} width={numberValue(item.forecast_aud_m) / maxForecast * 100} value={currencyBn(item.forecast_aud_m)} tone={item.status === 'Breach' ? 'risk' : item.status === 'Constrained' ? 'warn' : 'neutral'} />)}</div>
        </article>
        <article className="card"><div className="card-head"><div><h2>Baseline differences</h2><p>Funding, capacity and service changes</p></div></div>
          {selected ? <div className="exception-list">
            <ScenarioDifference label="Affordability" value={currencyBnCompact(selected.headroom_aud_m)} tone={numberValue(selected.headroom_aud_m) >= 0 ? 'good' : 'bad'} detail={selected.within_envelope ? 'Within the synthetic five-year funding envelope.' : 'Forecast exceeds the synthetic funding envelope.'} />
            <ScenarioDifference label="Deliverability" value={`${Math.abs(numberValue(selected.breaches_resolved_vs_baseline))} ${numberValue(selected.breaches_resolved_vs_baseline) >= 0 ? 'resolved' : 'added'}`} tone={numberValue(selected.breaches_resolved_vs_baseline) >= 0 ? 'good' : 'bad'} detail={`${numberValue(selected.capacity_breaches)} capacity breaches remain.`} />
            <ScenarioDifference label="Portfolio change" value={`${numberValue(selected.projects_changed)} projects`} tone="neutral" detail={`${numberValue(selected.regional_completions_deferred)} regional completions move beyond the horizon.`} />
          </div> : <p className="empty-state">Select a governed scenario to compare.</p>}
        </article>
      </div>
    </section>
  );
}

function ScenarioDifference({ label, value, tone, detail }: { label: string; value: string; tone: 'good' | 'bad' | 'neutral'; detail: string }) {
  return <div className="exception"><div className="exception-top"><strong>{label}</strong><span className={`delta ${tone}`}>{value}</span></div><p>{detail}</p></div>;
}

function DataBar({ label, width, value, tone }: { label: string; width: number; value: string; tone: 'neutral' | 'warn' | 'risk' }) {
  return <div className="bar-row"><span>{label}</span><div className="bar-track"><div className={`bar-fill ${tone}`} style={{ width: `${Math.min(Math.max(width, 0), 100)}%` }} /></div><span className="bar-value">{value}</span></div>;
}

function CapacityPage({ scenarioId }: { scenarioId: ScenarioId }) {
  const summary = useAnalyticsQuery('overview_summary', { scenario_id: sql.string(scenarioId), sector: sql.string('ALL') });
  const [selectedYear, setSelectedYear] = useState(scenarioId === 'ACCEL' || scenarioId === 'CAP_BAL' ? 'FY30' : 'FY29');
  const pressure = useAnalyticsQuery('capacity_pressure', { scenario_id: sql.string(scenarioId), financial_year: sql.string(selectedYear) });
  const row = summary.data?.[0];
  const maxUtilisation = Math.max(...(pressure.data ?? []).map((item) => numberValue(item.utilisation_pct)), 100);

  return <section className="page active" aria-labelledby="capacity-title">
    <div className="page-head"><div><p className="eyebrow">Market capacity</p><h1 id="capacity-title">Delivery capacity · FY27–31</h1><p className="subtitle">Compare portfolio demand with available labour, materials, equipment and engineering services.</p></div><div className="freshness"><strong>{row?.capacity_model_version ?? 'Capacity model'}</strong>Working scenario · {SCENARIO_LABELS[scenarioId]}</div></div>
    {summary.loading && <LoadingCards />}
    {summary.error && <QueryError message={`Capacity summary could not load: ${summary.error}`} />}
    {row && <div className="grid kpis"><KpiCard label="Constrained categories" value={String(numberValue(row.constrained_categories_peak_fy))} detail={`of ${numberValue(row.capacity_categories)} modelled categories`} /><KpiCard label="Peak demand / capacity" value={`${numberValue(row.peak_demand_capacity_pct).toFixed(0)}%`} detail={`${row.peak_fy} · ${row.peak_category}`} /><KpiCard label="Projects affected" value={String(numberValue(row.projects_affected))} detail={`across ${numberValue(row.programs_affected)} programs`} /><KpiCard label="Resolvable by sequencing" value={currencyBn(row.resolvable_by_sequencing_aud_m)} detail="without removing scope · synthetic" /></div>}
    <article className="card"><div className="card-head"><div><h2>Capacity pressure by delivery input</h2><p>Annual demand as a share of modelled available capacity</p></div><select className="select" aria-label="Capacity year" value={selectedYear} onChange={(event) => setSelectedYear(event.target.value)}>{['FY27', 'FY28', 'FY29', 'FY30', 'FY31'].map((year) => <option key={year}>{year}</option>)}</select></div>
      {pressure.loading && <ListSkeleton />}{pressure.error && <QueryError message={`Capacity pressure could not load: ${pressure.error}`} />}
      {!pressure.loading && !pressure.error && pressure.data?.length === 0 && <p className="empty-state">No capacity data exists for this year.</p>}
      <div className="bars">{pressure.data?.map((item) => <DataBar key={item.capacity_category} label={item.capacity_category} width={numberValue(item.utilisation_pct) / maxUtilisation * 100} value={`${numberValue(item.utilisation_pct).toFixed(0)}%`} tone={item.status === 'Breach' ? 'risk' : item.status === 'Constrained' ? 'warn' : 'neutral'} />)}</div>
    </article>
  </section>;
}

function VariancePage({ onReviewAssumptions }: { onReviewAssumptions: () => void }) {
  const summary = useAnalyticsQuery('overview_summary', { scenario_id: sql.string('BASE'), sector: sql.string('ALL') });
  const bridge = useAnalyticsQuery('variance_bridge', { period: sql.string('CURRENT_FY') });
  const row = summary.data?.[0];
  const maxAmount = Math.max(...(bridge.data ?? []).map((item) => Math.abs(numberValue(item.amount_aud_m))), 1);
  return <section className="page active" aria-labelledby="variance-title">
    <div className="page-head"><div><p className="eyebrow">Variance & actuals</p><h1 id="variance-title">Plan, forecast and actuals · {row?.current_fy_label ?? 'current FY'}</h1><p className="subtitle">Review cost and schedule variance by program, project and recorded driver.</p></div><div className="freshness"><strong>Actuals through {formatDate(row?.actuals_through)}</strong>Closed months only · synthetic ledger</div></div>
    {summary.loading && <LoadingCards />}{summary.error && <QueryError message={`Variance summary could not load: ${summary.error}`} />}
    {row && <div className="grid kpis"><KpiCard label="YTD actual" value={currencyBn(row.ytd_actual_aud_m)} detail={<>vs {currencyBn(row.ytd_plan_aud_m)} plan · <span className="delta bad">{currencyBnCompact(numberValue(row.ytd_actual_aud_m) - numberValue(row.ytd_plan_aud_m))}</span></>} /><KpiCard label={`${row.current_fy_label} forecast`} value={currencyBn(row.current_fy_forecast_aud_m)} detail={<>vs {currencyBn(row.current_fy_plan_aud_m)} plan · <span className="delta bad">{currencyBnCompact(numberValue(row.current_fy_forecast_aud_m) - numberValue(row.current_fy_plan_aud_m))}</span></>} /><KpiCard label="Schedule variance" value={`+${numberValue(row.schedule_variance_months).toFixed(1)}mo`} detail="portfolio-weighted average" /><KpiCard label="Unexplained variance" value={currencyBn(row.current_fy_unexplained_aud_m)} detail={<StatusBadge tone="risk">Needs attribution</StatusBadge>} /></div>}
    <article className="card"><div className="card-head"><div><h2>{bridge.data?.[0]?.period_label ?? 'Current year'} forecast variance drivers</h2><p>Forecast versus endorsed plan · nominal $bn · synthetic</p></div><button className="button" onClick={onReviewAssumptions}>Review assumptions <ChevronRight size={16} /></button></div>
      {bridge.loading && <ListSkeleton />}{bridge.error && <QueryError message={`Variance bridge could not load: ${bridge.error}`} />}
      <div className="bars">{bridge.data?.map((item) => <DataBar key={item.driver} label={item.driver} width={Math.abs(numberValue(item.amount_aud_m)) / maxAmount * 100} value={currencyBnCompact(item.amount_aud_m)} tone={numberValue(item.amount_aud_m) > 0 ? 'risk' : 'neutral'} />)}</div>
    </article>
  </section>;
}

function AssurancePage() {
  const assurance = useAnalyticsQuery('assurance_register', {});
  const awaiting = assurance.data?.filter((item) => item.approval_status === 'Awaiting attestation').length ?? 0;
  return <section className="page active" aria-labelledby="assurance-title">
    <div className="page-head"><div><p className="eyebrow">Assurance register</p><h1 id="assurance-title">Forecast assumptions and approvals</h1><p className="subtitle">Review evidence, ownership, confidence and approval status for material portfolio inputs.</p></div><div className="freshness"><strong>{assurance.data?.length ?? 0} governed records</strong>{awaiting} awaiting owner attestation</div></div>
    <article className="card"><div className="card-head"><div><h2>Assumption and assurance register</h2><p>Latest approval state for material portfolio inputs</p></div><StatusBadge>Read only</StatusBadge></div>
      {assurance.loading && <Skeleton className="table-skeleton" />}{assurance.error && <QueryError message={`Assurance records could not load: ${assurance.error}`} />}
      {!assurance.loading && !assurance.error && assurance.data?.length === 0 && <p className="empty-state">No governed assurance records were returned.</p>}
      {assurance.data && assurance.data.length > 0 && <div className="table-wrap"><table><thead><tr><th>Record</th><th>Type</th><th>Owner</th><th>Confidence</th><th>Approval</th><th>Last reviewed</th></tr></thead><tbody>{assurance.data.map((item) => <tr key={item.record_id}><td><strong>{item.record}</strong><small className="table-subtitle">{item.evidence_reference}</small></td><td>{item.record_type}</td><td>{item.owner}</td><td>{item.confidence}</td><td><StatusBadge tone={item.approval_status === 'Action required' ? 'risk' : item.approval_status === 'Endorsed' ? 'good' : item.approval_status === 'Awaiting attestation' ? 'warn' : 'neutral'}>{item.approval_status}</StatusBadge></td><td>{formatDate(item.last_reviewed)}</td></tr>)}</tbody></table></div>}
    </article>
  </section>;
}

function GeniePanel({ open, identity, onClose }: { open: boolean; identity: Identity | null; onClose: () => void }) {
  return <aside className={`assistant ${open ? 'open' : ''}`} aria-label="Portfolio data assistant" aria-hidden={!open}>
    <div className="assistant-head"><div><strong>Portfolio Genie</strong><div className="kpi-label">Signed in as {identity?.email ?? 'Databricks user'}</div></div><button className="button icon-button" aria-label="Close assistant" onClick={onClose}><X size={18} /></button></div>
    <div className="assistant-governance"><Scale size={15} /><span>Queries run through the governed Portfolio Genie space using the app service principal.</span></div>
    <div className="assistant-chat"><GenieChat alias="default" /></div>
    <p className="assistant-disclaimer">AI-generated from synthetic portfolio data — verify answers against the generated SQL and cited records.</p>
  </aside>;
}

function ScenarioModal({ name, purpose, onNameChange, onPurposeChange, onClose, onCreate }: { name: string; purpose: string; onNameChange: (value: string) => void; onPurposeChange: (value: string) => void; onClose: () => void; onCreate: () => void }) {
  return <div className="modal-backdrop open" role="dialog" aria-modal="true" aria-labelledby="modal-title" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="modal"><div className="modal-head"><div><p className="eyebrow">New scenario</p><h2 id="modal-title">Start from a governed baseline</h2></div><button className="button icon-button" aria-label="Close dialog" onClick={onClose}><X size={18} /></button></div>
      <div className="session-warning"><Check size={16} />This draft lives only in the current browser session and does not alter governed data.</div>
      <div className="field"><label htmlFor="scenario-name">Scenario name</label><input id="scenario-name" value={name} onChange={(event) => onNameChange(event.target.value)} autoFocus /></div>
      <div className="field"><label htmlFor="scenario-base">Start from</label><select id="scenario-base"><option>Working baseline · v12</option><option>Capacity balanced · v4</option><option>Endorsed plan · v8</option></select></div>
      <div className="field"><label htmlFor="scenario-purpose">Decision purpose</label><input id="scenario-purpose" value={purpose} onChange={(event) => onPurposeChange(event.target.value)} placeholder="e.g. Executive Budget Committee review" /></div>
      <div className="modal-actions"><button className="button" onClick={onClose}>Cancel</button><button className="button primary" disabled={!name.trim()} onClick={onCreate}>Create session draft</button></div>
    </div>
  </div>;
}

export default App;
