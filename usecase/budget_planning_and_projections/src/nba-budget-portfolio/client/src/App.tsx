import { useEffect, useMemo, useState } from 'react';

import { sql } from '@databricks/appkit-ui/js';
import { useQuery } from './lib/query';
import {
  BarChart3,
  Bot,
  CalendarCheck,
  CircleGauge,
  FileCheck2,
  FileText,
  LayoutDashboard,
  Loader2,
  Menu,
  RefreshCw,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { LoadingCards } from './components/common';
import { DrillDrawer } from './components/DrillDrawer';
import { GeniePanel } from './components/GeniePanel';
import { TERMINAL } from './lib/api';
import { dateTime, initials } from './lib/format';
import { AppStateProvider, useAppState, type Role } from './lib/state';
import { AssurancePage } from './pages/AssurancePage';
import { BriefingPage } from './pages/BriefingPage';
import { CapacityPage } from './pages/CapacityPage';
import { CyclePage } from './pages/CyclePage';
import { OverviewPage } from './pages/OverviewPage';
import { ScenariosPage, type ScenarioRow } from './pages/ScenariosPage';
import { VariancePage } from './pages/VariancePage';

export type PageId = 'overview' | 'scenarios' | 'capacity' | 'variance' | 'cycle' | 'assurance' | 'briefing';

const NAV_ITEMS: Array<{ id: PageId; label: string; group: 'Planning' | 'Governance'; icon: typeof LayoutDashboard }> = [
  { id: 'overview', label: 'Portfolio overview', group: 'Planning', icon: LayoutDashboard },
  { id: 'scenarios', label: 'Scenario studio', group: 'Planning', icon: SlidersHorizontal },
  { id: 'capacity', label: 'Market capacity', group: 'Planning', icon: BarChart3 },
  { id: 'variance', label: 'Variance & actuals', group: 'Planning', icon: CircleGauge },
  { id: 'cycle', label: 'Monthly forecast cycle', group: 'Governance', icon: CalendarCheck },
  { id: 'assurance', label: 'Assurance register', group: 'Governance', icon: FileCheck2 },
  { id: 'briefing', label: 'Briefing packs', group: 'Governance', icon: FileText },
];

export default function App() {
  return (
    <AppStateProvider>
      <Shell />
    </AppStateProvider>
  );
}

function Shell() {
  const { identity, scenarioId, setScenarioId, dataVersion, role, setRole, runs, toasts } = useAppState();
  const [page, setPage] = useState<PageId>(() => {
    const fromHash = window.location.hash.slice(1) as PageId;
    return NAV_ITEMS.some((item) => item.id === fromHash) ? fromHash : 'overview';
  });
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  useEffect(() => {
    const onHash = () => {
      const next = window.location.hash.slice(1) as PageId;
      if (NAV_ITEMS.some((item) => item.id === next)) setPage(next);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const scenarioQuery = useQuery('scenario_summary', { data_version: sql.string(dataVersion) });
  const actuals = useQuery('overview_summary', { scenario_id: sql.string('BASE'), sector: sql.string('ALL'), data_version: sql.string(dataVersion) });
  const scenarios = (scenarioQuery.data ?? []) as unknown as ScenarioRow[];
  const computed = useMemo(
    () => scenarios.filter((s) => s.computed_version !== null && s.computed_version !== undefined).map((s) => ({ id: s.scenario_id, name: s.scenario_name })),
    [scenarios],
  );
  const scenarioName = scenarios.find((s) => s.scenario_id === scenarioId)?.scenario_name ?? 'Working baseline';
  // A scenario saved moments ago has no results until its forecast run completes; outside Scenario
  // studio, fall back to the Working baseline rather than show empty figures.
  useEffect(() => {
    if (page !== 'scenarios' && computed.length > 0 && !computed.some((s) => s.id === scenarioId)) setScenarioId('BASE');
  }, [page, computed, scenarioId, setScenarioId]);
  const activeRuns = runs.filter((r) => !r.status || !TERMINAL.includes(r.status.life_cycle_state ?? ''));

  const navigate = (next: PageId) => {
    setPage(next);
    if (window.location.hash !== `#${next}`) window.history.pushState(null, '', `#${next}`);
    setMobileNavOpen(false);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const scenarioSelect = (
    <>
      <label className="sr-only" htmlFor="page-scenario">Scenario</label>
      <select id="page-scenario" className="select" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
        {(computed.length ? computed : [{ id: 'BASE', name: 'Working baseline' }]).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
    </>
  );

  return (
    <div className="shell">
      {mobileNavOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)} />}
      <aside className={`sidebar ${mobileNavOpen ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-mark">NBA</div>
          <div><strong>Portfolio Command</strong><span>Nation Building Authority</span></div>
          <button className="button icon-button nav-close" aria-label="Close navigation" onClick={() => setMobileNavOpen(false)}><X size={18} /></button>
        </div>
        {(['Planning', 'Governance'] as const).map((group) => (
          <div key={group}>
            <p className="nav-label">{group}</p>
            <nav className="nav" aria-label={`${group} navigation`}>
              {NAV_ITEMS.filter((item) => item.group === group).map((item) => {
                const Icon = item.icon;
                return <button className={page === item.id ? 'active' : ''} key={item.id} onClick={() => navigate(item.id)}><Icon size={18} /> {item.label}</button>;
              })}
            </nav>
          </div>
        ))}
        <div className="sidebar-meta">
          <strong>PROTECTED · Working figures</strong>
          Synthetic demonstration data. Reads use your Unity Catalog permissions; changes are recorded with your name.
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="actions topbar-context">
            <button className="button icon-button mobile-menu" aria-label="Open navigation" onClick={() => setMobileNavOpen(true)}><Menu size={19} /></button>
            <span className="crumb">FY27–31 portfolio / <strong>{scenarioName}</strong></span>
          </div>
          <div className="actions">
            {activeRuns.length > 0 ? (
              <span className="run-chip" title={activeRuns.map((r) => `${r.label}: ${r.status?.life_cycle_state ?? 'queued'}`).join('\n')}>
                <Loader2 size={14} className="spin" /> Recomputing · {activeRuns[0].label}
              </span>
            ) : runs[0]?.status ? (
              <span className="run-chip done" title={runs[0].status.run_page_url}><RefreshCw size={14} /> Last run {runs[0].status.result_state?.toLowerCase()} · {dateTime(runs[0].status.end_time ? new Date(runs[0].status.end_time).toISOString() : null)}</span>
            ) : null}
            <label className="sr-only" htmlFor="role">Acting as</label>
            <select id="role" className="select role-select desktop-action" value={role} onChange={(e) => setRole(e.target.value as Role)} title="Demo: in production this comes from your workspace groups">
              <option value="Portfolio office">Acting as Portfolio office</option>
              <option value="Program office">Acting as Program office</option>
            </select>
            <button className="button desktop-action" onClick={() => navigate('briefing')}><FileText size={16} /> Briefing</button>
            <div className="avatar" title={identity?.email ? `Signed in as ${identity.email}` : 'Signed in'}>{initials(identity?.email)}</div>
          </div>
        </header>

        <div className="content">
          {page === 'overview' && <OverviewPage scenarios={computed} onNavigate={navigate} />}
          {page === 'scenarios' && <ScenariosPage scenarios={scenarios} loading={scenarioQuery.loading} error={scenarioQuery.error} />}
          {page === 'capacity' && <CapacityPage scenarioName={scenarioName} scenarioSelect={scenarioSelect} />}
          {page === 'variance' && <VariancePage onReviewAssumptions={() => navigate('assurance')} />}
          {page === 'cycle' && (actuals.data?.[0]?.actuals_through ? <CyclePage actualsThrough={actuals.data[0].actuals_through} /> : <LoadingCards count={5} />)}
          {page === 'assurance' && <AssurancePage />}
          {page === 'briefing' && <BriefingPage scenarios={scenarios} />}
        </div>
      </main>

      <button className="assistant-launcher" onClick={() => setAssistantOpen(true)} aria-expanded={assistantOpen}><Bot size={17} /> Ask portfolio data</button>
      <GeniePanel open={assistantOpen} page={page} email={identity?.email} onClose={() => setAssistantOpen(false)} />
      <DrillDrawer />
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.tone}`}>{t.message}</div>)}
      </div>
    </div>
  );
}
