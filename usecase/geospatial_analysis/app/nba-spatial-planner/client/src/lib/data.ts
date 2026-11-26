import { sql } from '@databricks/appkit-ui/js';
import { useAnalyticsQuery } from '@databricks/appkit-ui/react';
import { createContext, useContext, useEffect, useMemo, useState } from 'react';

export interface Session {
  email: string | null;
  preferred: string | null;
  authenticated: boolean;
  catalog: string;
  schema: string;
  minCount: number;
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
      .then(async (response) => {
        if (!response.ok) throw new Error(`Session lookup failed (${response.status})`);
        return (await response.json()) as Session;
      })
      .then((session) => !cancelled && setState({ status: 'ready', session }))
      .catch(
        (error: unknown) =>
          !cancelled &&
          setState({ status: 'error', message: error instanceof Error ? error.message : 'Session lookup failed' })
      );
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}

/** The governed schema every query reads, plus a token bumped after each write. */
export interface QueryScope {
  catalog: string;
  schema: string;
  minCount: number;
  user: string | null;
  writes: string;
  bumpWrites: () => void;
}

export const ScopeContext = createContext<QueryScope | null>(null);

export function useScope(): QueryScope {
  const scope = useContext(ScopeContext);
  if (!scope) throw new Error('ScopeContext missing');
  return scope;
}

export function useBaseParams() {
  const { catalog, schema } = useScope();
  return useMemo(() => ({ catalog: sql.string(catalog), schema: sql.string(schema) }), [catalog, schema]);
}

/**
 * Keep the previous result on screen while new parameters load (with a `refreshing` flag), so a
 * threshold change dims the panels instead of flashing them back to skeletons.
 */
export function useSticky<T>(result: { data: T | null; loading: boolean; error: string | null }) {
  const [last, setLast] = useState<T | null>(null);
  if (result.data != null && result.data !== last) setLast(result.data);
  const data = result.data ?? last;
  return {
    data,
    loading: result.loading && data == null,
    refreshing: result.loading && data != null,
    error: result.error,
  };
}

/** Rows of an Arrow table as plain objects. */
export function arrowRows<T>(table: { toArray(): unknown[] } | null | undefined): T[] {
  if (!table) return [];
  return table.toArray().map((row) => {
    const r = row as { toJSON?: () => unknown };
    return (typeof r.toJSON === 'function' ? r.toJSON() : row) as T;
  });
}

export async function postJson<T>(url: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await fetch(url, {
    method,
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
  return (response.status === 204 ? undefined : await response.json()) as T;
}

/**
 * The JSON transport delivers every column as a string ("45", "3053.0", "false"), whatever the
 * generated types say. Normalise once at the boundary: booleans and numbers become real values,
 * while identifier-like columns (codes, ids, postcodes, names) always stay strings.
 */
const KEEP_STRING =
  /(_code|_id|^ra_class|postcode|_abbr|name|label|title|note|step|status|officer|_by|question|basis|audience|settings|findings|detail|metric|dataset|url|attribution|licence|publisher|address|suburb|description|ts|_at)$/;
const NUMERIC = /^-?\d+(\.\d+)?([eE][-+]?\d+)?$/;

export function normalizeRow(row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(row)) {
    if (value === 'true' || value === 'false') out[key] = value === 'true';
    else if (typeof value === 'string' && !KEEP_STRING.test(key) && NUMERIC.test(value)) out[key] = Number(value);
    else out[key] = value;
  }
  return out;
}

type QueryArgs = Parameters<typeof useAnalyticsQuery>;

/** useAnalyticsQuery for JSON results, with rows normalised (see normalizeRow). */
export function useRows(key: QueryArgs[0], parameters: QueryArgs[1], options?: { autoStart?: boolean }) {
  const result = useAnalyticsQuery(key, parameters, options);
  const raw = result.data as unknown;
  const data = useMemo<unknown[] | null>(
    () => (Array.isArray(raw) ? (raw as Record<string, unknown>[]).map(normalizeRow) : null),
    [raw]
  );
  return { ...result, data };
}

export { sql, useAnalyticsQuery };
