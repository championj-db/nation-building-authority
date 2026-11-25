import { formatTime } from './format';
import type { OpsStatusRow } from './rows';

/** A run older than this is shown as stale rather than "current". */
export const STALE_AFTER_MINUTES = 90;

export function feedHealth(ops: OpsStatusRow | null | undefined) {
  if (!ops) return { current: false, label: 'Checking feeds', tone: 'muted' as const };
  const minutes = Number(ops.minutes_since_run);
  if (Number.isFinite(minutes) && minutes <= STALE_AFTER_MINUTES) return { current: true, label: 'All feeds current', tone: 'ok' as const };
  return { current: false, label: `Data as of ${formatTime(ops.run_ts)}`, tone: 'warn' as const };
}


/** Turn warehouse/UC errors into something an officer (or a demo audience) can act on. */
export function friendlyError(message: string): string {
  if (/TABLE_OR_VIEW_NOT_FOUND|SCHEMA_NOT_FOUND/i.test(message)) {
    return 'The governed gold tables were not found. Run the critical infrastructure monitoring pipeline job, then refresh.';
  }
  if (/PERMISSION_DENIED|INSUFFICIENT_PERMISSIONS|does not have/i.test(message)) {
    return 'Your account does not have access to this data in Unity Catalog. Ask the data owner for SELECT on the operations schema.';
  }
  if (/timeout|timed out/i.test(message)) return 'The SQL warehouse took too long to respond. Try refreshing in a moment.';
  return message;
}

