import { useAnalyticsQuery } from '@databricks/appkit-ui/react';
import { sql } from '@databricks/appkit-ui/js';
import { createContext, useContext, useEffect, useMemo, useState } from 'react';

export interface Session {
  email: string | null;
  preferred: string | null;
  authenticated: boolean;
  catalog: string;
  schema: string;
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
      .catch((error: unknown) => !cancelled && setState({ status: 'error', message: error instanceof Error ? error.message : 'Session lookup failed' }));
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}

/** Display name and initials from the signed-in identity ("alex.morgan@agency" -> "Alex Morgan"). */
export function identity(session: Session) {
  const raw = session.preferred || session.email || '';
  const local = raw.split('@')[0] ?? '';
  const parts = local.split(/[._-]+/).filter(Boolean);
  const words = parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1).toLowerCase());
  const fullName = words.join(' ') || 'Officer';
  const firstName = words[0] ?? 'Officer';
  const initials = (words.length > 1 ? `${words[0]?.[0]}${words.at(-1)?.[0]}` : (words[0] ?? 'O').slice(0, 2)).toUpperCase();
  return { fullName, firstName, initials };
}

/**
 * Query scope shared by every panel: the governed schema plus a refresh token. The analytics
 * cache keys on parameters, so a new token is what makes "Refresh" read fresh results.
 */
export interface QueryScope {
  catalog: string;
  schema: string;
  refresh: string;
}

export const ScopeContext = createContext<QueryScope | null>(null);

export function useScope(): QueryScope {
  const scope = useContext(ScopeContext);
  if (!scope) throw new Error('ScopeContext missing');
  return scope;
}

export function useScopeParams() {
  const { catalog, schema, refresh } = useScope();
  return useMemo(
    () => ({ catalog: sql.string(catalog), schema: sql.string(schema), refresh: sql.string(refresh) }),
    [catalog, schema, refresh],
  );
}

/**
 * Wraps useAnalyticsQuery so a refresh keeps the previous result on screen (with a
 * `refreshing` flag) instead of flashing every panel back to its skeleton.
 */
export function useSticky<T>(result: { data: T | null; loading: boolean; error: string | null }) {
  // Derive-during-render: remember the latest non-null result without an effect.
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

export { useAnalyticsQuery };
