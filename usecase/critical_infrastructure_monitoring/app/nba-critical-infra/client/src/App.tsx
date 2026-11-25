import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AssetRegister } from './components/AssetRegister';
import { Handover } from './components/Handover';
import { IncidentQueue } from './components/IncidentQueue';
import { NetworkMap } from './components/NetworkMap';
import { Hero, SectorTiles } from './components/Overview';
import { EmptyState, ErrorState, Icon, Skeleton, Toast } from './components/primitives';
import { ReviewDialog } from './components/ReviewDialog';
import { identity, ScopeContext, useAnalyticsQuery, useScopeParams, useSession, useSticky, type QueryScope, type Session } from './lib/data';
import type { Sector } from './lib/model';
import { impactsByIncident, type IncidentRow } from './lib/rows';

const AUTO_REFRESH_MS = 5 * 60 * 1000;

const NAV = [
  { id: 'overview', label: 'Overview' },
  { id: 'queue', label: 'Incidents' },
  { id: 'map', label: 'Network map' },
  { id: 'assets', label: 'Assets' },
  { id: 'assurance', label: 'Shift handover' },
] as const;

export default function App() {
  const state = useSession();
  const [refresh, setRefresh] = useState(() => String(Date.now()));

  if (state.status === 'loading') {
    return (
      <Shell>
        <main className="container" style={{ paddingBlock: 48 }} aria-busy="true">
          <Skeleton width={260} height={14} />
          <Skeleton width="60%" height={48} style={{ marginTop: 16 }} />
          <Skeleton width="40%" height={20} style={{ marginTop: 16 }} />
        </main>
      </Shell>
    );
  }
  if (state.status === 'error') {
    return (
      <Shell>
        <main className="container" style={{ paddingBlock: 48 }}>
          <ErrorState title="The operations centre could not start" message={state.message} action={<button className="btn btn-secondary" onClick={() => window.location.reload()}>Reload</button>} />
        </main>
      </Shell>
    );
  }
  const scope: QueryScope = { catalog: state.session.catalog, schema: state.session.schema, refresh };
  return (
    <ScopeContext.Provider value={scope}>
      <OperationsCentre session={state.session} onRefresh={() => setRefresh(String(Date.now()))} />
    </ScopeContext.Provider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <>
      <header className="topnav">
        <div className="container topnav-inner">
          <span className="brand">
            <span className="brand-mark" aria-hidden="true">
              <Icon.Brand />
            </span>
            <span className="brand-text">Infrastructure Operations Centre</span>
          </span>
        </div>
      </header>
      {children}
    </>
  );
}

function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** Highlights the nav item for the section in view: the last section whose top has passed the
 * sticky nav (the design only set it on click). At the page bottom, the final section. */
function useActiveSection(ids: readonly string[]) {
  const [active, setActive] = useState<string>(ids[0] ?? '');
  useEffect(() => {
    let frame = 0;
    const update = () => {
      frame = 0;
      const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
      let current = ids[0] ?? '';
      for (const id of ids) {
        const top = document.getElementById(id)?.getBoundingClientRect().top;
        if (top != null && top <= 140) current = id;
      }
      setActive(atBottom ? (ids[ids.length - 1] ?? current) : current);
    };
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [ids]);
  return [active, setActive] as const;
}

function OperationsCentre({ session, onRefresh }: { session: Session; onRefresh: () => void }) {
  const now = useNow();
  const who = identity(session);
  const params = useScopeParams();
  const ids = useMemo(() => NAV.map((n) => n.id), []);
  const [active, setActive] = useActiveSection(ids);

  const ops = useSticky(useAnalyticsQuery('ops_status', params));
  const sectors = useSticky(useAnalyticsQuery('sector_status', params));
  const incidents = useSticky(useAnalyticsQuery('incident_queue', params));
  const impact = useSticky(useAnalyticsQuery('incident_impact', params));
  const network = useSticky(useAnalyticsQuery('network_assets', params));
  const hazards = useSticky(useAnalyticsQuery('hazards', params));
  const register = useSticky(useAnalyticsQuery('asset_register', params));
  const decisions = useSticky(useAnalyticsQuery('recent_decisions', params));

  const opsRow = ops.data?.[0] ?? null;
  const openIncidents = useMemo(() => (incidents.data ?? []).filter((i) => i.status === 'open'), [incidents.data]);
  const openCount = incidents.data ? openIncidents.length : null;
  const openBySector = useMemo(() => {
    if (!incidents.data) return null;
    const counts: Record<string, number> = { roads: 0, rail: 0, water: 0, energy: 0 };
    for (const i of openIncidents) counts[String(i.sector)] = (counts[String(i.sector)] ?? 0) + 1;
    return counts;
  }, [incidents.data, openIncidents]);
  const sectorsAffected = openBySector ? Object.values(openBySector).filter(Boolean).length : 0;
  const impacts = useMemo(() => impactsByIncident(impact.data), [impact.data]);
  const incidentsByAsset = useMemo(() => new Map((incidents.data ?? []).map((i) => [String(i.asset_id), i])), [incidents.data]);
  const refreshing = ops.refreshing || incidents.refreshing || sectors.refreshing || decisions.refreshing;
  const schemaMissing = [ops.error, incidents.error].some((e) => e && /TABLE_OR_VIEW_NOT_FOUND|SCHEMA_NOT_FOUND/i.test(e));

  const [target, setTarget] = useState<IncidentRow | null>(null);
  const [sectorFilter, setSectorFilter] = useState<string>('all');
  const [toast, setToast] = useState<{ message: string; tone: 'info' | 'error' } | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  const showToast = useCallback((message: string, tone: 'info' | 'error' = 'info') => {
    window.clearTimeout(toastTimer.current);
    setToast({ message, tone });
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  }, []);

  const doRefresh = useCallback(() => {
    onRefresh();
  }, [onRefresh]);

  // Quiet background refresh so a demo left open stays current.
  useEffect(() => {
    const id = window.setInterval(doRefresh, AUTO_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [doRefresh]);

  const scrollTo = (id: string) => {
    setActive(id);
    document.getElementById(id)?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  };

  return (
    <>
      <a href="#queue" className="sr-only">
        Skip to incidents
      </a>
      <header className="topnav">
        <div className="container topnav-inner">
          <a
            className="brand"
            href="#overview"
            aria-label="Infrastructure Operations Centre home"
            onClick={(e) => {
              e.preventDefault();
              scrollTo('overview');
            }}
          >
            <span className="brand-mark" aria-hidden="true">
              <Icon.Brand />
            </span>
            <span className="brand-text">Infrastructure Operations Centre</span>
          </a>
          <nav aria-label="Primary navigation">
            {NAV.map((n) => (
              <button key={n.id} className={`nav-link${active === n.id ? ' active' : ''}`} aria-current={active === n.id ? 'true' : undefined} onClick={() => scrollTo(n.id)}>
                {n.label}
                {n.id === 'queue' && openCount ? <span className="nav-count" aria-label={`${openCount} open`}>{openCount}</span> : null}
              </button>
            ))}
          </nav>
          <UserMenu session={session} fullName={who.fullName} initials={who.initials} />
        </div>
      </header>

      <main id="content">
        {schemaMissing ? (
          <section className="section">
            <div className="container">
              <EmptyState title="No operational data yet">
                The governed gold tables for <span className="num">{session.catalog}.{session.schema}</span> were not found. Run the critical infrastructure monitoring pipeline job, then refresh.
              </EmptyState>
            </div>
          </section>
        ) : null}

        <Hero now={now} firstName={who.firstName} openCount={openCount} sectorsAffected={sectorsAffected} ops={opsRow} opsLoading={ops.loading} opsError={ops.error && !ops.data ? ops.error : null} />
        <SectorTiles
          sectors={sectors.data}
          ops={opsRow}
          loading={sectors.loading || incidents.loading}
          error={sectors.error}
          openBySector={openBySector}
          onSelect={(sector: Sector) => {
            setSectorFilter(sector);
            scrollTo('queue');
          }}
        />
        <IncidentQueue
          now={now}
          incidents={incidents.data}
          loading={incidents.loading}
          refreshing={refreshing}
          error={incidents.error}
          sector={sectorFilter}
          onSectorChange={setSectorFilter}
          onRefresh={doRefresh}
          onReview={setTarget}
        />
        <NetworkMap
          assets={network.data}
          hazards={hazards.data}
          incidents={incidents.data}
          impacts={impacts}
          loading={network.loading}
          error={network.error}
          onReview={setTarget}
        />
        <AssetRegister rows={register.data} incidentsByAsset={incidentsByAsset} loading={register.loading} error={register.error} onReview={setTarget} />
        <Handover
          now={now}
          incidents={incidents.data}
          hazards={hazards.data}
          ops={opsRow}
          decisions={decisions.data}
          decisionsLoading={decisions.loading}
          decisionsError={decisions.error}
        />
      </main>

      <footer className="pagefoot">
        <div className="container row-between">
          <span>Infrastructure Operations Centre · built on Databricks · synthetic data for demonstration</span>
          <span className="meta">
            Decision support only ·{' '}
            <a href="#audit-log" onClick={(e) => { e.preventDefault(); scrollTo('assurance'); }} style={{ textDecoration: 'underline' }}>
              Audit log
            </a>{' '}
            · Governed by Unity Catalog
          </span>
        </div>
      </footer>

      <ReviewDialog
        incident={target}
        impacts={target ? (impacts.get(String(target.incident_id)) ?? []) : []}
        now={now}
        onClose={() => setTarget(null)}
        onDecided={(message) => {
          setTarget(null);
          showToast(message);
          doRefresh();
        }}
      />
      <Toast message={toast?.message ?? null} tone={toast?.tone ?? 'info'} />
    </>
  );
}

function UserMenu({ session, fullName, initials }: { session: Session; fullName: string; initials: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);
  return (
    <div className="user-wrap" ref={ref}>
      <button className="user" aria-label={`Signed in as ${fullName}. Open user menu`} aria-expanded={open} aria-haspopup="true" title={`${fullName} · Compliance Operations`} onClick={() => setOpen((v) => !v)}>
        {initials}
      </button>
      {open ? (
        <div className="user-menu" role="dialog" aria-label="Signed-in identity">
          <strong>{fullName}</strong>
          <div className="meta">Compliance Operations</div>
          <dl>
            <div>
              <dt>Signed in as</dt>
              <dd>{session.email ?? 'Local development identity'}</dd>
            </div>
            <div>
              <dt>Data access</dt>
              <dd>Every query and decision runs as you. Unity Catalog permissions, row filters and masks apply.</dd>
            </div>
            <div>
              <dt>Governed schema</dt>
              <dd className="num">
                {session.catalog}.{session.schema}
              </dd>
            </div>
          </dl>
        </div>
      ) : null}
    </div>
  );
}
