import { useCallback, useEffect, useMemo, useState } from 'react';
import { Crosshair, FileText, Moon, RotateCcw, Sun } from 'lucide-react';
import { AccessMap } from './components/AccessMap';
import { AssuranceView } from './components/AssuranceView';
import { BriefDialog, type BriefMode } from './components/BriefDialog';
import { DecisionSignals } from './components/DecisionSignals';
import { EvidenceQueue } from './components/EvidenceQueue';
import { PipelineView, type MetricRow } from './components/PipelineView';
import { PolicySettings } from './components/PolicySettings';
import { ErrorNotice, ToastProvider, useToast } from './components/primitives';
import { SavedViews } from './components/SavedViews';
import { useAnalysis } from './lib/analysis';
import { briefForSettings, useBriefs } from './lib/briefs';
import { ScopeContext, useBaseParams, useRows, useScope, useSession, type Session } from './lib/data';
import { dateTime } from './lib/format';
import type { CatalogRow, RegionAccess } from './lib/model';
import {
  SERVICE_LABELS,
  samePolicy,
  settingsFromSearch,
  settingsToSearch,
  type AnalysisSettings,
  type ProposedSite,
} from './lib/settings';

type Tab = 'analysis' | 'pipeline' | 'assurance';
const TABS: { key: Tab; label: string }[] = [
  { key: 'analysis', label: 'Analysis' },
  { key: 'pipeline', label: 'Data pipeline' },
  { key: 'assurance', label: 'Assurance' },
];

export default function App() {
  const session = useSession();
  if (session.status === 'loading') {
    return (
      <div className="shell">
        <div className="workspace-head">
          <p className="muted">
            <span className="spinner" aria-hidden="true" />
            Connecting to the governed workspace…
          </p>
        </div>
      </div>
    );
  }
  if (session.status === 'error') {
    return (
      <div className="shell" style={{ paddingTop: 48 }}>
        <ErrorNotice
          title="The planner could not start"
          message={session.message}
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }
  return (
    <ScopeProvider session={session.session}>
      <ToastProvider>
        <Workspace />
      </ToastProvider>
    </ScopeProvider>
  );
}

function ScopeProvider({ session, children }: { session: Session; children: React.ReactNode }) {
  const [writes, setWrites] = useState('initial');
  const bumpWrites = useCallback(() => setWrites(String(Date.now())), []);
  const value = useMemo(
    () => ({
      catalog: session.catalog,
      schema: session.schema,
      minCount: session.minCount,
      user: session.email ?? session.preferred,
      writes,
      bumpWrites,
    }),
    [session, writes, bumpWrites]
  );
  return <ScopeContext.Provider value={value}>{children}</ScopeContext.Provider>;
}

function useTheme() {
  const [dark, setDark] = useState(() => localStorage.getItem('spatial-theme') === 'dark');
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : '';
    localStorage.setItem('spatial-theme', dark ? 'dark' : 'light');
  }, [dark]);
  return [dark, () => setDark((d) => !d)] as const;
}

function Workspace() {
  const initial = useMemo(() => settingsFromSearch(window.location.search), []);
  const [tab, setTab] = useState<Tab>(initial.tab as Tab);
  const [applied, setApplied] = useState<AnalysisSettings>(initial.settings);
  const [draft, setDraft] = useState<AnalysisSettings>(initial.settings);
  const [selected, setSelected] = useState<string | null>(null);
  const [focusToken, setFocusToken] = useState(0);
  const [resetToken, setResetToken] = useState(0);
  const [placing, setPlacing] = useState(false);
  const [noteFor, setNoteFor] = useState<RegionAccess | null>(null);
  const [briefMode, setBriefMode] = useState<BriefMode>(null);
  const [justRan, setJustRan] = useState(false);
  const [dark, toggleTheme] = useTheme();
  const toast = useToast();
  const { minCount } = useScope();
  const base = useBaseParams();

  const [hexRes, setHexRes] = useState(5);
  const analysis = useAnalysis(applied, hexRes);
  const briefs = useBriefs();
  const catalogResult = useRows('service_catalog', base);
  const catalog = (catalogResult.data ?? []) as CatalogRow[];
  const metrics = useRows('pipeline_metrics', base);
  const refreshedRaw = ((metrics.data ?? []) as MetricRow[]).find((m) => m.metric === 'Refreshed')?.value;
  const refreshed = refreshedRaw ? dateTime(refreshedRaw * 1000) : null;
  const serviceLabel =
    catalog.find((c) => c.service_type === applied.service)?.label ?? SERVICE_LABELS[applied.service];

  // URL mirrors the applied view, so any view is a shareable link.
  useEffect(() => {
    window.history.replaceState(null, '', settingsToSearch(applied, tab));
  }, [applied, tab]);

  // A selection belongs to one geography; drop it when the geography changes (derived during
  // render rather than in an effect, so there is no stale frame).
  const geographyKey = `${applied.geoLevel}|${applied.scope}`;
  const [selectionKey, setSelectionKey] = useState(geographyKey);
  if (selectionKey !== geographyKey) {
    setSelectionKey(geographyKey);
    setSelected(null);
  }

  useEffect(() => {
    if (!placing) return undefined;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setPlacing(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [placing]);

  const busy =
    analysis.access.loading || analysis.access.refreshing || analysis.summary.loading || analysis.summary.refreshing;
  useEffect(() => {
    if (!busy && justRan) {
      const t = window.setTimeout(() => setJustRan(false), 4000);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [busy, justRan]);
  const dirty = !samePolicy(draft, applied);
  const status = dirty ? 'draft' : busy ? 'updating' : justRan ? 'updated' : 'ready';

  /** Display options and proposed sites apply at once; policy settings wait for Run analysis. */
  const patchBoth = (patch: Partial<AnalysisSettings>) => {
    setApplied((a) => ({ ...a, ...patch }));
    setDraft((d) => ({ ...d, ...patch }));
  };
  const onDraftChange = (patch: Partial<AnalysisSettings>) => {
    if ('boundaries' in patch) patchBoth({ boundaries: patch.boundaries });
    const { boundaries: _ignored, ...policy } = patch;
    if (Object.keys(policy).length) setDraft((d) => ({ ...d, ...policy }));
  };
  const run = () => {
    const next = { ...applied, ...draft, boundaries: applied.boundaries, layer: applied.layer, sites: applied.sites };
    const scopeChanged = next.scope !== applied.scope;
    setApplied(next);
    setDraft(next);
    setJustRan(true);
    if (scopeChanged) setResetToken((t) => t + 1);
    toast(`Analysis updated for a ${next.threshold} km access threshold.`);
  };
  const applyView = (settings: AnalysisSettings, name: string) => {
    setApplied(settings);
    setDraft(settings);
    setTab('analysis');
    setJustRan(true);
    toast(`Opened “${name}”.`);
  };
  const focusRegion = (code: string | null) => {
    setSelected(code);
    if (code) setFocusToken((t) => t + 1);
  };
  const addSite = (site: ProposedSite) => {
    if (applied.sites.length >= 5) {
      toast('A scenario can test up to five proposed sites.', 'error');
      setPlacing(false);
      return;
    }
    patchBoth({ sites: [...applied.sites, site] });
    setPlacing(false);
  };
  const selectedRow = selected ? (analysis.access.rows.find((r) => r.region_code === selected) ?? null) : null;

  const exportBrief = () => {
    const existing = briefForSettings(briefs.rows, applied);
    if (existing) setBriefMode({ kind: 'view', briefId: existing.brief_id });
    else setBriefMode({ kind: 'prepare' });
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <Crosshair className="icon" />
          </span>
          <span>Spatial Service Planner</span>
        </div>
        <div className="top-actions">
          <SavedViews current={applied} onApply={applyView} />
          <button
            type="button"
            className="button icon-button"
            aria-label={dark ? 'Use light theme' : 'Use dark theme'}
            aria-pressed={dark}
            onClick={toggleTheme}
          >
            {dark ? <Sun className="icon" aria-hidden="true" /> : <Moon className="icon" aria-hidden="true" />}
          </button>
          <button type="button" className="button primary" aria-label="Export brief" onClick={exportBrief}>
            <FileText className="icon" aria-hidden="true" />
            <span className="label">Export brief</span>
          </button>
        </div>
      </header>

      <div className={`banner${applied.suppress ? '' : ' warn'}`} role="note">
        <span>
          <strong>Demonstration environment.</strong> Household locations and service results are wholly synthetic.
          Boundaries, population and service locations are real public data.
        </span>
        {applied.suppress ? (
          <span className="status">Governance checks active</span>
        ) : (
          <span className="status warn">Suppression off · internal analysis only</span>
        )}
      </div>

      <section className="workspace-head">
        <div>
          <h1>Plan equitable access to essential services.</h1>
          <p>
            Identify communities outside a reasonable service radius, test policy settings, and prepare evidence for a
            decision brief.
          </p>
        </div>
        <div>
          <span className={`status${metrics.error ? ' danger' : refreshed ? '' : ' idle'}`}>
            {refreshed
              ? `Data refreshed ${refreshed}`
              : metrics.error
                ? 'Refresh status unavailable'
                : 'Checking data…'}
          </span>
        </div>
      </section>

      <nav className="tabs" role="tablist" aria-label="Workspace views">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            id={`tab-${t.key}`}
            aria-controls={`view-${t.key}`}
            aria-selected={tab === t.key}
            className="tab"
            tabIndex={tab === t.key ? 0 : -1}
            onClick={() => setTab(t.key)}
            onKeyDown={(e) => {
              // ARIA tabs: arrows move between tabs, Home/End jump to the ends
              const i = TABS.findIndex((x) => x.key === t.key);
              const next =
                e.key === 'ArrowRight'
                  ? (i + 1) % TABS.length
                  : e.key === 'ArrowLeft'
                    ? (i - 1 + TABS.length) % TABS.length
                    : e.key === 'Home'
                      ? 0
                      : e.key === 'End'
                        ? TABS.length - 1
                        : -1;
              if (next < 0) return;
              e.preventDefault();
              const key = TABS[next]?.key;
              if (!key) return;
              setTab(key);
              document.getElementById(`tab-${key}`)?.focus();
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main>
        {tab === 'analysis' && (
          <section className="view" id="view-analysis" role="tabpanel" aria-labelledby="tab-analysis">
            <div className="grid">
              <PolicySettings
                draft={draft}
                applied={applied}
                catalog={catalog}
                minCount={minCount}
                running={busy && justRan}
                onChange={onDraftChange}
                onRun={run}
                onDiscard={() => setDraft(applied)}
              />
              <section className="panel" aria-labelledby="map-title">
                <div className="panel-head">
                  <div>
                    <h2 id="map-title">Access overview</h2>
                    <span className="sub">Synthetic sample · not for operational use</span>
                  </div>
                  <button
                    type="button"
                    className="button icon-button"
                    aria-label="Reset map view"
                    onClick={() => setResetToken((t) => t + 1)}
                  >
                    <RotateCcw className="icon" aria-hidden="true" />
                  </button>
                </div>
                <AccessMap
                  analysis={analysis}
                  settings={applied}
                  serviceLabel={serviceLabel}
                  selected={selected}
                  focusToken={focusToken}
                  resetToken={resetToken}
                  placing={placing}
                  onSelect={(code) => setSelected(code)}
                  onAddSite={addSite}
                  onLayer={(layer) => patchBoth({ layer })}
                  onTogglePlacing={() => setPlacing((p) => !p)}
                  onHexRes={setHexRes}
                />
              </section>
              <DecisionSignals
                analysis={analysis}
                settings={applied}
                serviceLabel={serviceLabel}
                status={status}
                selected={selectedRow}
                placing={placing}
                onFocusRegion={focusRegion}
                onClearSelection={() => setSelected(null)}
                onAddNote={setNoteFor}
                onStartPlacing={() => setPlacing(true)}
                onRemoveSite={(i) => patchBoth({ sites: applied.sites.filter((_, j) => j !== i) })}
                onClearSites={() => patchBoth({ sites: [] })}
              />
            </div>
            <EvidenceQueue
              analysis={analysis}
              settings={applied}
              serviceLabel={serviceLabel}
              selected={selected}
              onSelect={focusRegion}
              noteFor={noteFor}
              onNoteFor={setNoteFor}
            />
          </section>
        )}
        {tab === 'pipeline' && (
          <section className="view" id="view-pipeline" role="tabpanel" aria-labelledby="tab-pipeline">
            <PipelineView />
          </section>
        )}
        {tab === 'assurance' && (
          <section className="view" id="view-assurance" role="tabpanel" aria-labelledby="tab-assurance">
            <AssuranceView
              settings={applied}
              minCount={minCount}
              briefs={briefs}
              onPrepare={() => setBriefMode({ kind: 'prepare' })}
              onView={(briefId) => setBriefMode({ kind: 'view', briefId })}
            />
          </section>
        )}
      </main>

      <footer className="footer">
        <span>
          Spatial Service Planner · concept prototype · built from a pattern-based use case, no public outcome claim
        </span>
        <span>
          Boundaries and population © ABS, CC BY 4.0 · Service locations: Department of Health, Disability and Ageing;
          Geoscience Australia, CC BY 4.0
        </span>
      </footer>

      <BriefDialog
        mode={briefMode}
        analysis={analysis}
        settings={applied}
        serviceLabel={serviceLabel}
        refreshed={refreshed}
        briefs={briefs.rows}
        onClose={() => setBriefMode(null)}
        onPrepared={(briefId) => setBriefMode({ kind: 'view', briefId })}
      />
    </div>
  );
}
