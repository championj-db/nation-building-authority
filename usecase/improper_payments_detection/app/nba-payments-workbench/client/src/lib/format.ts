const integer = new Intl.NumberFormat('en-AU', { maximumFractionDigits: 0 });
const aud = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD', currencyDisplay: 'narrowSymbol', maximumFractionDigits: 0 });

export const int = (n: number | null | undefined) => (n == null ? '–' : integer.format(n));

/** $486,220 */
export const money = (n: number | null | undefined) => (n == null ? '–' : aud.format(n));

/** $1.84m / $412k: headline totals only; tables always show the full amount. */
export function moneyShort(n: number | null | undefined) {
  if (n == null) return '–';
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}m`;
  if (Math.abs(n) >= 10_000) return `$${Math.round(n / 1000)}k`;
  return aud.format(n);
}

export function pct(value: number | null | undefined, digits = 0) {
  if (value == null) return '–';
  return `${(value * 100).toFixed(digits)}%`;
}

function toDate(value: string | number | Date | null | undefined) {
  if (value == null || value === '') return null;
  const d = value instanceof Date ? value : new Date(typeof value === 'number' ? value : value.replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? null : d;
}

export function dateTime(value: string | number | Date | null | undefined) {
  const d = toDate(value);
  if (!d) return '–';
  return d.toLocaleString('en-AU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function shortDate(value: string | number | Date | null | undefined) {
  const d = toDate(value);
  if (!d) return '–';
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' });
}

/** "08:15 AEST" style clock for the model refresh, in the agency's time zone. */
export function clock(value: string | number | Date | null | undefined) {
  const d = toDate(value);
  if (!d) return '–';
  const time = d.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Australia/Sydney' });
  const day = d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', timeZone: 'Australia/Sydney' });
  const zone =
    new Intl.DateTimeFormat('en-AU', { timeZone: 'Australia/Sydney', timeZoneName: 'short' })
      .formatToParts(d)
      .find((p) => p.type === 'timeZoneName')?.value ?? '';
  return `${day}, ${time} ${zone.replace(/^GMT\+11$/, 'AEDT').replace(/^GMT\+10$/, 'AEST')}`.trim();
}

/** Whether a timestamp falls on today's date in the agency's time zone. */
export function isTodaySydney(value: string | null | undefined, now = new Date()) {
  const d = toDate(value);
  if (!d) return false;
  const day = (x: Date) => x.toLocaleDateString('en-CA', { timeZone: 'Australia/Sydney' });
  return day(d) === day(now);
}

/** "alex.morgan@agency.gov.au" -> "Alex Morgan". */
export function personName(raw: string | null | undefined) {
  if (!raw) return 'Investigator';
  const local = raw.split('@')[0] ?? raw;
  const words = local.split(/[._-]+/).filter(Boolean);
  return words.map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ') || raw;
}

export function plural(n: number, one: string, many = `${one}s`) {
  return `${integer.format(n)} ${n === 1 ? one : many}`;
}

export const days = (n: number) => plural(n, 'day');
