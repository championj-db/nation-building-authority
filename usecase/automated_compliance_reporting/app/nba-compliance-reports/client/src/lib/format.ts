/**
 * Value coercion and formatting.
 *
 * The SQL Statement API returns every value as a string (or null), whatever the generated types
 * say, so `"false"` is truthy and `"12"` is not a number. Always read values through these helpers.
 */

export function bool(value: unknown): boolean {
  return value === true || value === 'true';
}

export function num(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function list(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value !== 'string' || !value) return [];
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

export function json(value: unknown): unknown {
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

const LOCALE = 'en-AU';
const dateFormat = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short', year: 'numeric' });
const dateTimeFormat = new Intl.DateTimeFormat(LOCALE, {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
});
const shortDateTimeFormat = new Intl.DateTimeFormat(LOCALE, {
  day: 'numeric',
  month: 'short',
  hour: 'numeric',
  minute: '2-digit',
});
const integer = new Intl.NumberFormat(LOCALE);
const percent = new Intl.NumberFormat(LOCALE, { style: 'percent', maximumFractionDigits: 1 });

/** Parse a DATE (`2026-10-22`) as a local calendar date, not UTC midnight. */
function toDate(value: string): Date {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
}

export function formatDate(value: unknown, fallback = '—') {
  if (!value || typeof value !== 'string') return fallback;
  const date = toDate(value);
  return Number.isNaN(date.getTime()) ? fallback : dateFormat.format(date);
}

const shortDateFormat = new Intl.DateTimeFormat(LOCALE, { day: 'numeric', month: 'short' });

export function formatShortDate(value: unknown, fallback = '—') {
  if (!value || typeof value !== 'string') return fallback;
  const date = toDate(value);
  return Number.isNaN(date.getTime()) ? fallback : shortDateFormat.format(date);
}

export function formatDateTime(value: unknown, fallback = '—') {
  if (!value || typeof value !== 'string') return fallback;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? fallback : dateTimeFormat.format(date);
}

export function formatShortDateTime(value: unknown, fallback = '—') {
  if (!value || typeof value !== 'string') return fallback;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? fallback : shortDateTimeFormat.format(date);
}

export function formatNumber(value: unknown, fallback = '—') {
  const n = num(value);
  return n === null ? fallback : integer.format(n);
}

/** `ratio` is 0..1. */
export function formatPercent(ratio: unknown, fallback = '—') {
  const n = num(ratio);
  return n === null ? fallback : percent.format(n);
}

/** Whole days from today to a DATE; negative when in the past. */
export function daysFrom(value: unknown): number | null {
  if (!value || typeof value !== 'string') return null;
  const target = toDate(value);
  if (Number.isNaN(target.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  target.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

export function relativeDays(days: number | null) {
  if (days === null) return '';
  if (days === 0) return 'today';
  if (days === 1) return 'tomorrow';
  if (days === -1) return 'yesterday';
  return days > 0 ? `in ${days} days` : `${Math.abs(days)} days ago`;
}

export function plural(count: number, one: string, many = `${one}s`) {
  return `${integer.format(count)} ${count === 1 ? one : many}`;
}

export function shortHash(value: unknown, length = 12) {
  return typeof value === 'string' && value ? value.slice(0, length) : '—';
}

/** Download rows as CSV. Values are quoted; formulas are neutralised for spreadsheet safety. */
export function downloadCsv(fileName: string, rows: Record<string, unknown>[], columns?: string[]) {
  const keys = columns ?? Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const escape = (value: unknown) => {
    let text =
      value === null || value === undefined
        ? ''
        : typeof value === 'object'
          ? JSON.stringify(value)
          : String(value as string | number | boolean);
    if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replace(/"/g, '""')}"`;
  };
  const csv = [keys.map(escape).join(','), ...rows.map((row) => keys.map((key) => escape(row[key])).join(','))].join(
    '\r\n'
  );
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = Object.assign(document.createElement('a'), { href: url, download: fileName });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function today() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}
