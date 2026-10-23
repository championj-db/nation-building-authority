import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { getRun, TERMINAL, type RunStatus } from './api';

export type Role = 'Program office' | 'Portfolio office';

export type Drill =
  | { kind: 'program'; id: string; name: string }
  | { kind: 'project'; id: string; name: string }
  | { kind: 'capacity'; financialYear: string; categoryId: string; categoryName: string; utilisation: number }
  | null;

export type TrackedRun = { runId: number; label: string; scenarioId?: string; status?: RunStatus; startedAt: number };

export type Toast = { id: number; message: string; tone: 'good' | 'bad' | 'neutral' };

type Identity = { email?: string | null; forecastJobConfigured?: boolean; draftingModel?: string | null };

type AppState = {
  identity: Identity | null;
  dataVersion: string;
  refresh: (delayMs?: number) => void;
  role: Role;
  setRole: (role: Role) => void;
  scenarioId: string;
  setScenarioId: (id: string) => void;
  drill: Drill;
  setDrill: (drill: Drill) => void;
  runs: TrackedRun[];
  trackRun: (run: Omit<TrackedRun, 'startedAt'>) => void;
  toasts: Toast[];
  notify: (message: string, tone?: Toast['tone']) => void;
};

const Ctx = createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: React.ReactNode }) {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [dataVersion, setDataVersion] = useState(() => String(Date.now()));
  const [role, setRoleState] = useState<Role>(() => (localStorage.getItem('nba-role') as Role) || 'Portfolio office');
  const [scenarioId, setScenarioId] = useState('BASE');
  const [drill, setDrill] = useState<Drill>(null);
  const [runs, setRuns] = useState<TrackedRun[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('nba-runs') ?? '[]') as TrackedRun[];
    } catch {
      return [];
    }
  });
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(0);

  useEffect(() => {
    fetch('/api/whoami')
      .then((r) => (r.ok ? r.json() : null))
      .then(setIdentity)
      .catch(() => setIdentity(null));
  }, []);

  const notify = useCallback((message: string, tone: Toast['tone'] = 'neutral') => {
    const id = ++toastId.current;
    setToasts((current) => [...current, { id, message, tone }]);
    window.setTimeout(() => setToasts((current) => current.filter((t) => t.id !== id)), 6000);
  }, []);

  // The serverless real-time warehouse can serve a pre-write snapshot for several seconds, so a write
  // refreshes immediately and twice more as the snapshot catches up.
  const refresh = useCallback((delayMs = 0) => {
    const bump = () => setDataVersion(String(Date.now()));
    bump();
    if (delayMs > 0) {
      window.setTimeout(bump, Math.max(delayMs, 4000));
      window.setTimeout(bump, Math.max(delayMs, 4000) * 2.5);
    }
  }, []);

  const setRole = useCallback((next: Role) => {
    localStorage.setItem('nba-role', next);
    setRoleState(next);
  }, []);

  const trackRun = useCallback((run: Omit<TrackedRun, 'startedAt'>) => {
    setRuns((current) => [{ ...run, startedAt: Date.now() }, ...current.filter((r) => r.runId !== run.runId)].slice(0, 6));
  }, []);

  useEffect(() => {
    localStorage.setItem('nba-runs', JSON.stringify(runs));
  }, [runs]);

  // Poll active forecast runs; when one completes, refresh every query so new results appear.
  const active = runs.filter((r) => !r.status || !TERMINAL.includes(r.status.life_cycle_state ?? ''));
  const activeKey = active.map((r) => r.runId).join(',');
  useEffect(() => {
    if (!activeKey) return;
    const poll = async () => {
      for (const run of active) {
        try {
          const status = await getRun(run.runId);
          setRuns((current) => current.map((r) => (r.runId === run.runId ? { ...r, status } : r)));
          if (TERMINAL.includes(status.life_cycle_state ?? '')) {
            const ok = status.result_state === 'SUCCESS';
            notify(ok ? `Forecast run complete: ${run.label}` : `Forecast run ${status.result_state?.toLowerCase() ?? 'failed'}: ${run.label}`, ok ? 'good' : 'bad');
            if (ok) refresh(4000);
          }
        } catch {
          // transient; next poll retries
        }
      }
    };
    void poll();
    const timer = window.setInterval(poll, 10000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeKey]);

  const value = useMemo<AppState>(
    () => ({ identity, dataVersion, refresh, role, setRole, scenarioId, setScenarioId, drill, setDrill, runs, trackRun, toasts, notify }),
    [identity, dataVersion, refresh, role, setRole, scenarioId, drill, runs, trackRun, toasts, notify],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAppState(): AppState {
  const value = useContext(Ctx);
  if (!value) throw new Error('useAppState must be used inside AppStateProvider');
  return value;
}
