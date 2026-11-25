import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useSearchParams } from 'react-router';
import { sql } from '@databricks/appkit-ui/js';

export interface RuntimeConfig {
  catalog: string | null;
  schema: string | null;
  user: string | null;
  capabilities: { generateReports: boolean; verifyChain: boolean };
}

interface ConfigState {
  config: RuntimeConfig | null;
  error: string | null;
  ready: boolean;
  parameters: { catalog: ReturnType<typeof sql.string>; schema: ReturnType<typeof sql.string> };
  /** Changes when a run finishes or a decision is recorded, so freshness-sensitive queries re-read. */
  refresh: string;
  bumpRefresh: () => void;
}

const ConfigContext = createContext<ConfigState | null>(null);

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { ...(init?.json !== undefined ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
    body: init?.json !== undefined ? JSON.stringify(init.json) : init?.body,
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { error?: string; message?: string };
      message = body.error ?? body.message ?? message;
    } catch {
      /* keep the status message */
    }
    throw new ApiError(response.status, message);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

export function ConfigProvider({ children }: { children: ReactNode }) {
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(() => String(Math.floor(Date.now() / 60_000)));

  useEffect(() => {
    api<RuntimeConfig>('/api/config')
      .then((value) => {
        if (!value.catalog || !value.schema)
          throw new Error(
            'The app is not connected to a compliance schema. Set DATABRICKS_CATALOG and DATABRICKS_SCHEMA.'
          );
        setConfig(value);
      })
      .catch((reason: Error) => setError(reason.message || 'Application configuration is unavailable.'));
  }, []);

  const parameters = useMemo(
    () => ({ catalog: sql.string(config?.catalog ?? ''), schema: sql.string(config?.schema ?? '') }),
    [config]
  );
  const bumpRefresh = useCallback(() => setRefresh(String(Date.now())), []);
  const value = useMemo(
    () => ({ config, error, ready: Boolean(config), parameters, refresh, bumpRefresh }),
    [config, error, parameters, refresh, bumpRefresh]
  );
  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>;
}

export function useConfig() {
  const value = useContext(ConfigContext);
  if (!value) throw new Error('useConfig must be used inside ConfigProvider');
  return value;
}

/** Fetch JSON from an app route, with reload. */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(path));
  const [version, setVersion] = useState(0);
  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api<T>(path)
      .then((value) => !cancelled && setData(value))
      .catch((reason: Error) => !cancelled && setError(reason.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, version, ...deps]);
  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, loading, reload };
}

/** Filter state that lives in the URL, so views can be shared, bookmarked and navigated back to. */
export function useUrlState<K extends string>(defaults: Record<K, string>) {
  const [params, setParams] = useSearchParams();
  const values = useMemo(() => {
    const result = { ...defaults };
    for (const key of Object.keys(defaults) as K[]) result[key] = params.get(key) ?? defaults[key];
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);
  const set = useCallback(
    (patch: Partial<Record<K, string>>, options?: { replace?: boolean }) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const [key, value] of Object.entries(patch) as [K, string | undefined][]) {
            if (value === undefined || value === '' || value === defaults[key]) next.delete(key);
            else next.set(key, value);
          }
          return next;
        },
        { replace: options?.replace ?? true }
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setParams]
  );
  return [values, set] as const;
}

export interface RunSummary {
  runId: number;
  lifecycle: string;
  result: string | null;
  message: string | null;
  startedAt: string | null;
  endedAt: string | null;
  url: string | null;
  params: Record<string, string>;
}

const TERMINAL = /TERMINATED|SKIPPED|INTERNAL_ERROR/;

export function isRunFinished(run: RunSummary | null) {
  return Boolean(run && (TERMINAL.test(run.lifecycle) || run.endedAt));
}

export function isRunSuccessful(run: RunSummary | null) {
  return Boolean(run && isRunFinished(run) && /SUCCESS/.test(run.result ?? ''));
}

/**
 * Track a job run started from this browser. The run ID is kept in sessionStorage so leaving and
 * returning to the screen keeps showing progress.
 */
export function useTrackedRun(job: 'report' | 'verify', onFinished?: (run: RunSummary) => void) {
  const storageKey = `nba.run.${job}`;
  const [runId, setRunId] = useState<number | null>(() => {
    const stored = sessionStorage.getItem(storageKey);
    return stored ? Number(stored) : null;
  });
  const [run, setRun] = useState<RunSummary | null>(null);
  const finishedRef = useRef(onFinished);
  useEffect(() => {
    finishedRef.current = onFinished;
  }, [onFinished]);

  useEffect(() => {
    if (!runId) return;
    let timer: ReturnType<typeof setTimeout>;
    let cancelled = false;
    const poll = async () => {
      try {
        const { run: latest } = await api<{ run: RunSummary }>(`/api/runs/${job}/${runId}`);
        if (cancelled) return;
        setRun(latest);
        if (isRunFinished(latest)) {
          sessionStorage.removeItem(storageKey);
          finishedRef.current?.(latest);
          return;
        }
      } catch {
        /* transient: keep polling */
      }
      timer = setTimeout(() => void poll(), 8000);
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [job, runId, storageKey]);

  const track = useCallback(
    (id: number) => {
      sessionStorage.setItem(storageKey, String(id));
      setRun(null);
      setRunId(id);
    },
    [storageKey]
  );
  const dismiss = useCallback(() => {
    sessionStorage.removeItem(storageKey);
    setRunId(null);
    setRun(null);
  }, [storageKey]);
  return { runId, run, track, dismiss };
}

export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const media = window.matchMedia(query);
    const listener = () => setMatches(media.matches);
    media.addEventListener('change', listener);
    return () => media.removeEventListener('change', listener);
  }, [query]);
  return matches;
}

export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · NBA Compliance Assurance`;
  }, [title]);
}
