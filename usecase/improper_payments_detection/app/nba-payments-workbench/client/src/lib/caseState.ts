import { useCallback, useEffect, useRef, useState } from 'react';
import type { CaseEvent, CaseState, OutcomeInput } from '../../../shared/contracts';
import { postJson } from './data';

interface StateResponse {
  enabled: boolean;
  states: CaseState[];
  outcomesTotal: number;
}

export interface CaseStates {
  enabled: boolean;
  states: CaseState[];
  outcomesTotal: number;
  loading: boolean;
  error: string | null;
  refresh: () => void;
  assign: (caseId: string) => Promise<CaseState>;
  release: (caseId: string) => Promise<CaseState>;
  recordOutcome: (caseId: string, input: OutcomeInput) => Promise<CaseState>;
}

const POLL_MS = 30_000;

/**
 * Case workflow state from Lakebase, shared by the queue and the drawer. Polls so a colleague's
 * assignment shows up without a reload; every write replaces the case's state with the server's
 * answer, so the screen never shows a state the store refused.
 */
export function useCaseStates(): CaseStates {
  const [data, setData] = useState<StateResponse>({ enabled: true, states: [], outcomesTotal: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);

  const load = useCallback(async () => {
    try {
      const response = await fetch('/api/case-state');
      if (!response.ok) throw new Error(`Case status could not be loaded (${response.status})`);
      const next = (await response.json()) as StateResponse;
      if (alive.current) {
        setData(next);
        setError(null);
      }
    } catch (e) {
      if (alive.current) setError(e instanceof Error ? e.message : 'Case status could not be loaded');
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void load();
    const timer = window.setInterval(() => document.visibilityState === 'visible' && void load(), POLL_MS);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [load]);

  const put = useCallback((state: CaseState, countOutcome = false) => {
    setData((d) => ({
      ...d,
      states: [...d.states.filter((s) => s.case_id !== state.case_id), state],
      outcomesTotal: d.outcomesTotal + (countOutcome ? 1 : 0),
    }));
    return state;
  }, []);

  return {
    ...data,
    loading,
    error,
    refresh: () => void load(),
    assign: async (caseId) => put(await postJson<CaseState>(`/api/cases/${caseId}/assign`)),
    release: async (caseId) => put(await postJson<CaseState>(`/api/cases/${caseId}/release`)),
    recordOutcome: async (caseId, input) => put(await postJson<CaseState>(`/api/cases/${caseId}/outcome`, input), true),
  };
}

export interface CaseHistory {
  events: CaseEvent[];
  outcome: { outcome: string; reason_code: string; notes: string; decided_by: string; decided_at: string } | null;
}

export function useCaseHistory(caseId: string | null, version: string, enabled: boolean) {
  const key = `${caseId ?? ''}|${version}`;
  const [state, setState] = useState<{ key: string; data: CaseHistory | null; error: string | null } | null>(null);
  useEffect(() => {
    if (!caseId || !enabled) return undefined;
    let cancelled = false;
    fetch(`/api/cases/${caseId}/history`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`History could not be loaded (${r.status})`);
        return (await r.json()) as CaseHistory;
      })
      .then((data) => !cancelled && setState({ key, data, error: null }))
      .catch((e: unknown) => !cancelled && setState({ key, data: null, error: e instanceof Error ? e.message : 'History could not be loaded' }));
    return () => {
      cancelled = true;
    };
  }, [caseId, key, enabled]);
  // Keep showing the previous history while a newer version loads.
  return { data: state?.data ?? null, loading: state?.key !== key, error: state?.key === key ? state.error : null };
}
