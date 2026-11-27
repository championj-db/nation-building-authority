import { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Ask } from './components/Ask';
import { DecisionLog } from './components/DecisionLog';
import { Intake } from './components/Intake';
import { Overview } from './components/Overview';
import { Performance } from './components/Performance';
import { QueueView, type QueueMode } from './components/QueueView';
import { Register } from './components/Register';
import { Review } from './components/Review';
import { Sidebar, Topbar, type View } from './components/Shell';
import { ErrorNotice } from './components/primitives';
import {
  DataVersionContext,
  DecisionsContext,
  postJson,
  SessionContext,
  useBaseParams,
  useDecisions,
  useDecisionsContext,
  useRows,
  useSession,
  useSessionInfo,
  type Session,
} from './lib/data';
import { openItems } from './lib/queue';
import type { IntakeRow, PipelineStatus, QueueRow, RegisterRow } from './lib/types';

const VIEWS: View[] = ['overview', 'queue', 'review', 'intake', 'ask', 'register', 'performance', 'log'];
const CRUMBS: Record<View, string> = {
  overview: 'Overview',
  queue: 'Review queue',
  review: 'Review',
  intake: 'Intake',
  ask: 'Ask the AP data',
  register: 'Document register',
  performance: 'Performance',
  log: 'Decision log',
};

interface Route {
  view: View;
  doc: string | null;
  mode: QueueMode;
}

function readRoute(): Route {
  const p = new URLSearchParams(window.location.search);
  const doc = p.get('doc');
  const v = p.get('view') as View | null;
  const mode = (p.get('filter') as QueueMode | null) ?? 'all';
  if (doc && /^DOC-\d{6}$/.test(doc)) return { view: 'review', doc, mode };
  return { view: v && VIEWS.includes(v) && v !== 'review' ? v : 'overview', doc: null, mode };
}

function writeRoute(r: Route, replace = false) {
  const p = new URLSearchParams();
  if (r.view === 'review' && r.doc) p.set('doc', r.doc);
  else if (r.view !== 'overview') p.set('view', r.view);
  if (r.view === 'queue' && r.mode !== 'all') p.set('filter', r.mode);
  const url = `${window.location.pathname}${p.toString() ? `?${p}` : ''}`;
  if (replace) window.history.replaceState(null, '', url);
  else window.history.pushState(null, '', url);
}

export default function App() {
  const state = useSession();
  const [dark, setDark] = useState(() => localStorage.getItem('daw-theme') === 'dark');
  useEffect(() => {
    if (dark) document.documentElement.dataset.theme = 'dark';
    else delete document.documentElement.dataset.theme;
    localStorage.setItem('daw-theme', dark ? 'dark' : 'light');
  }, [dark]);

  if (state.status === 'loading') return <div className="content" aria-busy="true" />;
  if (state.status === 'error') {
    return (
      <div className="content">
        <ErrorNotice
          message={`The workbench could not start: ${state.message}`}
          onRetry={() => window.location.reload()}
        />
      </div>
    );
  }
  return <Workbench session={state.session} dark={dark} onTheme={() => setDark((d) => !d)} />;
}

function Workbench({ session, dark, onTheme }: { session: Session; dark: boolean; onTheme: () => void }) {
  const decisions = useDecisions();
  const [version, setVersion] = useState(0);
  const bump = useCallback(() => setVersion((v) => v + 1), []);
  return (
    <SessionContext.Provider value={session}>
      <DecisionsContext.Provider value={decisions}>
        <DataVersionContext.Provider value={{ version, bump }}>
          <Screens key={version} dark={dark} onTheme={onTheme} />
        </DataVersionContext.Provider>
      </DecisionsContext.Provider>
    </SessionContext.Provider>
  );
}

type Ingest = { running: boolean; runId: number | null; label: string | null };

function Screens({ dark, onTheme }: { dark: boolean; onTheme: () => void }) {
  const session = useSessionInfo();
  const decisions = useDecisionsContext();
  const base = useBaseParams();
  const [route, setRoute] = useState<Route>(readRoute);
  const [toast, setToast] = useState<string | null>(null);
  const [ingest, setIngest] = useState<Ingest>(() => {
    const saved = sessionStorage.getItem('daw-ingest-run');
    return saved
      ? { running: true, runId: Number(saved), label: 'Processing new documents' }
      : { running: false, runId: null, label: null };
  });
  const dialog = useRef<HTMLDialogElement>(null);
  const mainRef = useRef<HTMLElement>(null);

  const queue = useRows<QueueRow>('open_queue', base);
  const status = useRows<PipelineStatus>('pipeline_status', base);
  const intake = useRows<IntakeRow>('intake', base);
  const register = useRows<RegisterRow>('register', base, { autoStart: route.view === 'register' });

  const open = useMemo(
    () => (queue.data ? openItems(queue.data, decisions.byDoc) : null),
    [queue.data, decisions.byDoc]
  );
  const intakeOpen = useMemo(
    () => (intake.data ? intake.data.filter((r) => r.in_live_window && !decisions.byDoc.has(r.doc_id)).length : null),
    [intake.data, decisions.byDoc]
  );

  useEffect(() => {
    const onPop = () => setRoute(readRoute());
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const go = useCallback((next: Partial<Route>) => {
    setRoute((r) => {
      const n = { ...r, ...next } as Route;
      if (n.view !== 'review') n.doc = null;
      writeRoute(n);
      return n;
    });
    window.scrollTo({ top: 0 });
    requestAnimationFrame(() => mainRef.current?.focus({ preventScroll: true }));
  }, []);
  const openDoc = useCallback((doc: string) => go({ view: 'review', doc }), [go]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4200);
    return () => clearTimeout(t);
  }, [toast]);

  // Ingestion: start the arrivals job, then poll until the new documents are processed.
  const dataVersion = useContext(DataVersionContext);
  useEffect(() => {
    if (!ingest.running || ingest.runId == null) return;
    let stop = false;
    const tick = async () => {
      try {
        const r = await fetch(`/api/ingest/${ingest.runId}`);
        const body = (await r.json()) as {
          lifecycle: string | null;
          result: string | null;
          tasks: { key: string; state: string }[];
        };
        if (stop) return;
        if (body.lifecycle === 'TERMINATED' || body.lifecycle === 'INTERNAL_ERROR' || body.lifecycle === 'SKIPPED') {
          sessionStorage.removeItem('daw-ingest-run');
          setIngest({ running: false, runId: null, label: null });
          if (body.result === 'SUCCESS') {
            setToast('New documents parsed, classified, extracted and checked. The queue is up to date.');
            dataVersion.bump();
          } else setToast('Ingestion did not complete. Check the arrivals job run in the workspace.');
          return;
        }
        const active = body.tasks.find((t) => t.state === 'RUNNING' || t.state === 'PENDING');
        const label =
          {
            arrivals: 'Landing new mail',
            process_documents: 'Parsing and extracting',
            sync_decisions: 'Syncing decisions',
            assess: 'Running the checks',
          }[active?.key ?? ''] ?? 'Starting';
        setIngest((s) => ({ ...s, label }));
      } catch {
        /* transient; keep polling */
      }
      if (!stop) setTimeout(() => void tick(), 8000);
    };
    const t = setTimeout(() => void tick(), 2000);
    return () => {
      stop = true;
      clearTimeout(t);
    };
  }, [ingest.running, ingest.runId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function startIngest() {
    dialog.current?.close();
    try {
      const { runId } = await postJson<{ runId: number | null }>('/api/ingest');
      if (runId != null) sessionStorage.setItem('daw-ingest-run', String(runId));
      setIngest({ running: runId != null, runId, label: 'Starting' });
      setToast(
        'Synthetic supplier mail is arriving. New documents appear in the queue once they are checked, usually within a few minutes.'
      );
    } catch (e) {
      setToast(e instanceof Error ? e.message : 'Could not start ingestion');
    }
  }

  const v = route.view;
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <Sidebar
        view={v}
        onNavigate={(view) => go({ view, mode: 'all' })}
        counts={{ queue: open ? open.length : null, intake: intakeOpen }}
      />
      <main className="main" id="main" ref={mainRef} tabIndex={-1} style={{ outline: 'none' }}>
        <Topbar
          crumb={CRUMBS[v]}
          dark={dark}
          onTheme={onTheme}
          onIngest={() => dialog.current?.showModal()}
          ingest={{ enabled: session.ingestEnabled, running: ingest.running, label: ingest.label }}
        />
        {v === 'overview' && (
          <Overview
            email={session.email}
            rows={open}
            loading={queue.loading}
            error={queue.error}
            status={status.data?.[0] ?? null}
            decisionsRecorded={decisions.decisions.length}
            onOpen={openDoc}
            onQueue={(mode) => go({ view: 'queue', mode })}
            onRetry={dataVersion.bump}
          />
        )}
        {v === 'queue' && (
          <QueueView
            rows={open}
            loading={queue.loading}
            error={queue.error}
            mode={route.mode}
            onMode={(mode) => go({ view: 'queue', mode })}
            onOpen={openDoc}
            onRetry={dataVersion.bump}
          />
        )}
        {v === 'review' && route.doc && (
          <Review
            docId={route.doc}
            onBack={() => (window.history.length > 1 ? window.history.back() : go({ view: 'queue' }))}
            onOpen={openDoc}
            onDecided={setToast}
          />
        )}
        {v === 'intake' && (
          <Intake
            rows={intake.data}
            loading={intake.loading}
            error={intake.error}
            onRetry={dataVersion.bump}
            onOpen={openDoc}
            onDecided={setToast}
          />
        )}
        {v === 'ask' && <Ask enabled={session.genieEnabled} email={session.email} />}
        {v === 'register' && (
          <Register
            rows={register.data}
            loading={register.loading || !register.data}
            error={register.error}
            onRetry={dataVersion.bump}
            onOpen={openDoc}
          />
        )}
        {v === 'performance' && <Performance status={status.data?.[0] ?? null} />}
        {v === 'log' && <DecisionLog onOpen={openDoc} />}
      </main>

      <dialog ref={dialog} className="dialog" aria-labelledby="ingest-title">
        <h2 id="ingest-title">Ingest documents</h2>
        <p>
          This lands a batch of new synthetic supplier mail in the governed inbox volume and processes only the new
          arrivals:
        </p>
        <ol>
          <li>Auto Loader detects the new files in the Unity Catalog volume.</li>
          <li>
            ai_parse_document renders and parses each page; ai_classify sorts invoices from statements, letters and
            quotes.
          </li>
          <li>
            ai_extract reads typed fields with citations; the correctly rendered checks and the payment clock run.
          </li>
        </ol>
        <p style={{ marginTop: 0, marginBottom: 'var(--space-6)' }}>
          No real documents are accepted. Nothing is written to a finance system.
        </p>
        <div className="dialog-actions">
          <button className="button" onClick={() => dialog.current?.close()}>
            Cancel
          </button>
          <button className="button primary" onClick={() => void startIngest()}>
            Land new mail
          </button>
        </div>
      </dialog>
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
