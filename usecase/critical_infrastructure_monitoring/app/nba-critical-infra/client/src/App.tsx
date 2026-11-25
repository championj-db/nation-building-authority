import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertQueue } from './components/AlertQueue';
import { Handover } from './components/Handover';
import { Hero, Metrics } from './components/Overview';
import { EmptyState, ErrorState, Icon, Skeleton, Toast } from './components/primitives';
import { ReviewDialog } from './components/ReviewDialog';
import { RiskRegister, TrendPanel } from './components/RiskRegister';
import { identity, ScopeContext, useAnalyticsQuery, useScopeParams, useSession, useSticky, type QueryScope, type Session } from './lib/data';
import { fromAlert, fromRegister, type ReviewTarget } from './lib/rows';

const AUTO_REFRESH_MS = 5 * 60 * 1000;

const NAV = [
  { id: 'overview', label: 'Overview' },
  { id: 'queue', label: 'Alert queue' },
  { id: 'entities', label: 'Entities' },
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

/** Highlights the nav item for the section in view (the design only set it on click). */
function useActiveSection(ids: readonly string[]) {
  const [active, setActive] = useState<string>(ids[0] ?? '');
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: '-80px 0px -55% 0px', threshold: 0 },
    );
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });
    // The last section can never scroll high enough to cross the band; at the page bottom, select it.
    const onScroll = () => {
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) setActive(ids[ids.length - 1] ?? '');
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      observer.disconnect();
      window.removeEventListener('scroll', onScroll);
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
  const alerts = useSticky(useAnalyticsQuery('alert_queue', params));
  const register = useSticky(useAnalyticsQuery('risk_register', params));
  const trend = useSticky(useAnalyticsQuery('signal_trend', params));
  const decisions = useSticky(useAnalyticsQuery('recent_decisions', params));

  const opsRow = ops.data?.[0] ?? null;
  const statusByAsset = useMemo(() => new Map((alerts.data ?? []).map((a) => [String(a.asset_id), String(a.status)])), [alerts.data]);
  const openCount = alerts.data ? alerts.data.filter((a) => a.status === 'open').length : null;
  const alertThreshold = Number(register.data?.[0]?.alert_threshold ?? 70);
  const refreshing = ops.refreshing || alerts.refreshing || register.refreshing || decisions.refreshing;
  const schemaMissing = [ops.error, alerts.error].some((e) => e && /TABLE_OR_VIEW_NOT_FOUND|SCHEMA_NOT_FOUND/i.test(e));

  const [target, setTarget] = useState<ReviewTarget | null>(null);
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
        Skip to alert queue
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

        <Hero now={now} firstName={who.firstName} openCount={openCount} ops={opsRow} opsLoading={ops.loading} opsError={ops.error && !ops.data ? ops.error : null} />
        <Metrics ops={opsRow} openCount={openCount} loading={ops.loading || alerts.loading} />
        <AlertQueue
          now={now}
          alerts={alerts.data}
          loading={alerts.loading}
          refreshing={refreshing}
          error={alerts.error}
          onRefresh={doRefresh}
          onReview={(row) => setTarget(fromAlert(row))}
        />
        <section className="section" id="entities" aria-labelledby="entities-heading">
          <div className="container grid-2-1">
            <RiskRegister
              now={now}
              rows={register.data}
              loading={register.loading}
              error={register.error}
              statusByAsset={statusByAsset}
              onSelect={(row) => setTarget(fromRegister(row, alerts.data?.find((a) => String(a.asset_id) === String(row.asset_id) && a.risk_type === row.risk_type)))}
            />
            <TrendPanel rows={trend.data} loading={trend.loading} error={trend.error} />
          </div>
        </section>
        <Handover now={now} alerts={alerts.data} ops={opsRow} decisions={decisions.data} decisionsLoading={decisions.loading} decisionsError={decisions.error} />
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
        target={target}
        alertThreshold={alertThreshold}
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
