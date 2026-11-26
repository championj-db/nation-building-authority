import { useCallback, useEffect, useMemo, useState } from 'react';
import { Moon, Sun } from 'lucide-react';
import { ErrorNotice, ToastProvider } from './components/primitives';
import { PrecisionView } from './components/PrecisionView';
import { QueueView } from './components/QueueView';
import { useCaseStates } from './lib/caseState';
import { ScopeContext, useBaseParams, useRows, useScope, useSession, type Session } from './lib/data';
import { personName } from './lib/format';
import type { QueueTab } from './lib/queue';

export type View = 'queue' | 'precision';
const TABS: QueueTab[] = ['all', 'unassigned', 'review', 'mine', 'closed'];

export interface PipelineSummary {
  scored_ts: string;
  model_name: string;
  model_version: string;
  source_records: number;
  entities_resolved: number;
  payments_scored: number;
  cases_open: number;
}

export default function App() {
  const session = useSession();
  if (session.status === 'loading') {
    return (
      <div className="boot">
        <p className="muted row">
          <span className="spinner" aria-hidden="true" />
          Connecting to the governed workspace…
        </p>
      </div>
    );
  }
  if (session.status === 'error') {
    return (
      <div className="boot">
        <ErrorNotice title="The workbench could not start" message={session.message} onRetry={() => window.location.reload()} />
      </div>
    );
  }
  return (
    <ScopeProvider session={session.session}>
      <ToastProvider>
        <Workbench />
      </ToastProvider>
    </ScopeProvider>
  );
}

function ScopeProvider({ session, children }: { session: Session; children: React.ReactNode }) {
  const value = useMemo(
    () => ({
      catalog: session.catalog,
      schema: session.schema,
      user: session.email ?? session.preferred,
      outcomesEnabled: session.outcomesEnabled,
    }),
    [session],
  );
  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

function useTheme() {
  const [dark, setDark] = useState(() => localStorage.getItem('ipw-theme') === 'dark');
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    localStorage.setItem('ipw-theme', dark ? 'dark' : 'light');
  }, [dark]);
  return [dark, () => setDark((d) => !d)] as const;
}

interface Route {
  view: View;
  tab: QueueTab;
  caseId: string | null;
}

function readRoute(search: string): Route {
  const p = new URLSearchParams(search);
  const tab = p.get('tab') as QueueTab | null;
  return {
    view: p.get('view') === 'precision' ? 'precision' : 'queue',
    tab: tab && TABS.includes(tab) ? tab : 'all',
    caseId: /^IP-\d{4,6}$/.test(p.get('case') ?? '') ? p.get('case') : null,
  };
}

function writeRoute(r: Route) {
  const p = new URLSearchParams();
  if (r.view !== 'queue') p.set('view', r.view);
  if (r.view === 'queue' && r.tab !== 'all') p.set('tab', r.tab);
  if (r.view === 'queue' && r.caseId) p.set('case', r.caseId);
  const q = p.toString();
  return q ? `?${q}` : window.location.pathname;
}

function Workbench() {
  const [route, setRoute] = useState<Route>(() => readRoute(window.location.search));
  const [dark, toggleTheme] = useTheme();
  const caseStates = useCaseStates();
  const base = useBaseParams();
  const summary = useRows('pipeline_summary', base);
  const pipeline = ((summary.data ?? []) as PipelineSummary[])[0] ?? null;

  const navigate = useCallback((next: Partial<Route>, push = false) => {
    setRoute((current) => {
      const r = { ...current, ...next };
      const url = writeRoute(r);
      if (push) window.history.pushState(null, '', url);
      else window.history.replaceState(null, '', url);
      return r;
    });
  }, []);

  useEffect(() => {
    const onPop = () => setRoute(readRoute(window.location.search));
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  useEffect(() => {
    document.title = route.view === 'precision' ? 'Precision monitoring · Improper Payments Workbench' : 'Payment review queue · Improper Payments Workbench';
  }, [route.view]);

  return (
    <div className="shell">
      <TopBar view={route.view} onView={(view) => navigate({ view, caseId: null }, true)} dark={dark} onTheme={toggleTheme} />
      {route.view === 'queue' ? (
        <QueueView
          tab={route.tab}
          onTab={(tab) => navigate({ tab })}
          caseId={route.caseId}
          onCase={(caseId) => navigate({ caseId }, caseId != null)}
          caseStates={caseStates}
          pipeline={pipeline}
          onPrecision={() => navigate({ view: 'precision', caseId: null }, true)}
        />
      ) : (
        <PrecisionView caseStates={caseStates} pipeline={pipeline} />
      )}
    </div>
  );
}

function TopBar({ view, onView, dark, onTheme }: { view: View; onView: (v: View) => void; dark: boolean; onTheme: () => void }) {
  const { user } = useScope();
  const link = (target: View, label: string) => (
    <a
      href={target === 'queue' ? window.location.pathname : '?view=precision'}
      aria-current={view === target ? 'page' : undefined}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        onView(target);
      }}
    >
      {label}
    </a>
  );
  return (
    <header className="topbar">
      <div className="topbar-inner">
        <div className="topbar-start">
          <div className="brand">
            <span className="brand-mark" aria-hidden="true">
              IP
            </span>
            <span>Improper Payments Workbench</span>
          </div>
          <nav className="app-nav" aria-label="Workbench">
            {link('queue', 'Review queue')}
            {link('precision', 'Precision')}
          </nav>
        </div>
        <div className="top-actions">
          <div className="identity">
            <strong>{personName(user)}</strong>Integrity operations · Daily review
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={onTheme}
            aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
            title={dark ? 'Light theme' : 'Dark theme'}
          >
            {dark ? <Sun className="icon" aria-hidden="true" /> : <Moon className="icon" aria-hidden="true" />}
          </button>
        </div>
      </div>
    </header>
  );
}
