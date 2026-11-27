import { sql } from '@databricks/appkit-ui/js';
import { useAnalyticsQuery } from '@databricks/appkit-ui/react';
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { CorrectionRecord, DecisionRecord } from '../../../shared/contracts';
import { list, normalizeRow } from './rows';

export interface Session {
  email: string | null;
  preferred: string | null;
  catalog: string;
  schema: string;
  decisionsEnabled: boolean;
  genieEnabled: boolean;
  ingestEnabled: boolean;
  pagesEnabled: boolean;
}

export type SessionState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; session: Session };

export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>({ status: 'loading' });
  useEffect(() => {
    let cancelled = false;
    fetch('/api/session')
      .then(async (r) => {
        if (!r.ok) throw new Error(`Session lookup failed (${r.status})`);
        return (await r.json()) as Session;
      })
      .then((session) => !cancelled && setState({ status: 'ready', session }))
      .catch(
        (e: unknown) =>
          !cancelled && setState({ status: 'error', message: e instanceof Error ? e.message : 'Session lookup failed' })
      );
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}

export const SessionContext = createContext<Session | null>(null);
export function useSessionInfo(): Session {
  const s = useContext(SessionContext);
  if (!s) throw new Error('SessionContext missing');
  return s;
}

/** Bumped after an ingestion run completes; the app remounts its views so governed reads refetch. */
export const DataVersionContext = createContext<{ version: number; bump: () => void }>({
  version: 0,
  bump: () => undefined,
});

export function useBaseParams() {
  const { catalog, schema } = useSessionInfo();
  return useMemo(() => ({ catalog: sql.string(catalog), schema: sql.string(schema) }), [catalog, schema]);
}

export async function postJson<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = (await response.json()) as { error?: string };
      if (payload.error) message = payload.error;
    } catch {
      /* keep the status message */
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

type QueryArgs = Parameters<typeof useAnalyticsQuery>;

export function useRows<T>(key: QueryArgs[0], parameters: QueryArgs[1], options?: { autoStart?: boolean }) {
  const result = useAnalyticsQuery(key, parameters, options);
  const raw = result.data;
  const data = useMemo<T[] | null>(
    () => (Array.isArray(raw) ? ((raw as Record<string, unknown>[]).map(normalizeRow) as T[]) : null),
    [raw]
  );
  return { ...result, data };
}

/** Decisions recorded in the workbench (Lakebase), refreshed on demand. */
export function useDecisions() {
  const [state, setState] = useState<{
    enabled: boolean;
    decisions: DecisionRecord[];
    loading: boolean;
    error: string | null;
  }>({
    enabled: false,
    decisions: [],
    loading: true,
    error: null,
  });
  const fetchAll = useCallback(() => {
    fetch('/api/decisions')
      .then(async (r) => {
        const body = (await r.json()) as { enabled: boolean; decisions: DecisionRecord[]; error?: string };
        if (!r.ok) throw new Error(body.error ?? 'Could not load decisions');
        setState({ enabled: body.enabled, decisions: body.decisions, loading: false, error: null });
      })
      .catch((e: unknown) =>
        setState((s) => ({ ...s, loading: false, error: e instanceof Error ? e.message : 'Could not load decisions' }))
      );
  }, []);
  useEffect(fetchAll, [fetchAll]);
  const load = useCallback(() => {
    setState((s) => ({ ...s, loading: true }));
    fetchAll();
  }, [fetchAll]);
  const byDoc = useMemo(() => new Map(state.decisions.map((d) => [d.doc_id, d])), [state.decisions]);
  return { ...state, byDoc, reload: load };
}
export type DecisionsState = ReturnType<typeof useDecisions>;
export const DecisionsContext = createContext<DecisionsState | null>(null);
export function useDecisionsContext(): DecisionsState {
  const d = useContext(DecisionsContext);
  if (!d) throw new Error('DecisionsContext missing');
  return d;
}

export async function fetchDocumentDecision(
  docId: string
): Promise<{ decision: DecisionRecord | null; corrections: CorrectionRecord[] }> {
  const r = await fetch(`/api/documents/${docId}/decision`);
  if (!r.ok) throw new Error('Could not load the decision');
  return (await r.json()) as { decision: DecisionRecord | null; corrections: CorrectionRecord[] };
}

export { list, normalizeRow, sql };
