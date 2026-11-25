/**
 * Display helpers. Every time renders in the operations centre's local zone (the pipeline's
 * model zone), not the viewer's laptop zone, so a demo run from another region still reads
 * "09:42 AEDT" consistently with the data.
 */
export const OPS_TIMEZONE = 'Australia/Sydney';

type Timestamp = string | number | Date | null | undefined;

/** SQL timestamps arrive as ISO strings (sometimes without a zone, meaning UTC). */
export function toDate(value: Timestamp): Date | null {
  if (value == null || value === '') return null;
  if (value instanceof Date) return value;
  if (typeof value === 'number') return new Date(value);
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
  const date = new Date(hasZone ? value : `${value.replace(' ', 'T')}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

const timeFmt = new Intl.DateTimeFormat('en-AU', {
  timeZone: OPS_TIMEZONE,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const timeSecFmt = new Intl.DateTimeFormat('en-AU', {
  timeZone: OPS_TIMEZONE,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});
const dayFmt = new Intl.DateTimeFormat('en-AU', {
  timeZone: OPS_TIMEZONE,
  weekday: 'long',
  day: 'numeric',
  month: 'long',
});
const zoneFmt = new Intl.DateTimeFormat('en-AU', { timeZone: OPS_TIMEZONE, timeZoneName: 'short' });
const hourFmt = new Intl.DateTimeFormat('en-AU', { timeZone: OPS_TIMEZONE, hour: 'numeric', hour12: true });
const shortDateTimeFmt = new Intl.DateTimeFormat('en-AU', {
  timeZone: OPS_TIMEZONE,
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

/** "AEDT" / "AEST" for the given instant. */
export function zoneLabel(at: Date = new Date()): string {
  return zoneFmt.formatToParts(at).find((p) => p.type === 'timeZoneName')?.value ?? 'AET';
}

export const formatTime = (value: Timestamp) => {
  const d = toDate(value);
  return d ? timeFmt.format(d) : '—';
};
export const formatTimeSeconds = (value: Timestamp) => {
  const d = toDate(value);
  return d ? timeSecFmt.format(d) : '—';
};
export const formatShortDateTime = (value: Timestamp) => {
  const d = toDate(value);
  return d ? shortDateTimeFmt.format(d) : '—';
};
export const formatHour = (value: Timestamp) => {
  const d = toDate(value);
  return d ? hourFmt.format(d).replace(' ', '').toLowerCase() : '';
};

/** "Tuesday 27 October · 09:42 AEDT" */
export function formatEyebrowNow(now: Date): string {
  return `${dayFmt.format(now).replace(',', '')} · ${timeFmt.format(now)} ${zoneLabel(now)}`;
}

/** Local hour (0-23) in the ops zone, for the greeting. */
export function opsHour(now: Date): number {
  return Number(new Intl.DateTimeFormat('en-AU', { timeZone: OPS_TIMEZONE, hour: 'numeric', hour12: false }).format(now)) % 24;
}

export function greeting(now: Date): string {
  const h = opsHour(now);
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

/** Compact age: "2m", "1h 05m", "3d". Never negative. */
export function formatAge(fromValue: Timestamp, now: Date): string {
  const from = toDate(fromValue);
  if (!from) return '—';
  const minutes = Math.max(0, Math.floor((now.getTime() - from.getTime()) / 60000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${String(minutes % 60).padStart(2, '0')}m`;
  return `${Math.floor(hours / 24)}d`;
}

/** Minutes as the design's "4m 12s"-style duration. */
export function formatMinutes(value: number | string | null | undefined): string {
  const n = Number(value);
  if (value == null || Number.isNaN(n)) return '—';
  const totalSeconds = Math.max(0, Math.round(n * 60));
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  return `${m}m ${String(s).padStart(2, '0')}s`;
}

export function formatSeconds(value: number | string | null | undefined): string {
  const n = Number(value);
  if (value == null || Number.isNaN(n)) return '—';
  if (n < 60) return `${n.toFixed(n < 10 ? 1 : 0)} sec`;
  return formatMinutes(n / 60);
}

export const formatInt = (value: number | string | null | undefined) =>
  value == null || Number.isNaN(Number(value)) ? '—' : Number(value).toLocaleString('en-AU');

export const formatPct = (value: number | string | null | undefined, digits = 1) =>
  value == null || Number.isNaN(Number(value)) ? '—' : `${(Number(value) * 100).toFixed(digits)}%`;

const NUMBER_WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten'];

/** "Three alerts" / "One alert" / "14 alerts" - the design's headline copy. */
export function countPhrase(count: number, noun: string, capitalise = true): string {
  const word = count <= 10 ? NUMBER_WORDS[count] : String(count);
  const text = `${word} ${noun}${count === 1 ? '' : 's'}`;
  return capitalise ? text : text.charAt(0).toLowerCase() + text.slice(1);
}

/** Factor names as officers read them. Keys match the gold_* score columns. */
export const FACTOR_LABELS: Record<string, string> = {
  rest_window_anomaly: 'Rest-window anomaly',
  night_movement: 'Night movement',
  recent_pattern: 'Recent pattern',
  route_variance: 'Route variance',
  mass_variance: 'Mass variance',
  defect_history: 'Defect history',
};

export const RISK_TYPE_LABELS: Record<string, string> = {
  fatigue: 'Fatigue',
  roadworthiness: 'Roadworthiness',
  mass: 'Over-mass',
  route: 'Route variance',
};

export const SOURCE_LABELS: Record<string, string> = {
  anpr_camera: 'ANPR camera',
  weigh_in_motion: 'Weigh-in-motion',
  gps_gateway: 'GPS gateway',
};
