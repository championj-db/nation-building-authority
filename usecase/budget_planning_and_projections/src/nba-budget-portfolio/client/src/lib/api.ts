export async function postJson<T = Record<string, unknown>>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  });
  const payload = (await response.json().catch(() => ({}))) as T & { error?: string };
  if (!response.ok) throw new Error(payload.error ?? `Request failed (${response.status})`);
  return payload;
}

export type RunStatus = {
  run_id: number;
  life_cycle_state?: string;
  result_state?: string;
  state_message?: string;
  start_time?: number;
  end_time?: number;
  run_page_url?: string;
  tasks?: Array<{ task_key?: string; state?: string; result?: string }>;
};

export async function getRun(runId: number): Promise<RunStatus> {
  const response = await fetch(`/api/runs/${runId}`);
  const payload = (await response.json().catch(() => ({}))) as RunStatus & { error?: string };
  if (!response.ok) throw new Error(payload.error ?? 'Run status unavailable');
  return payload;
}

export const TERMINAL = ['TERMINATED', 'SKIPPED', 'INTERNAL_ERROR'];
