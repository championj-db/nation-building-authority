const AUD = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD', minimumFractionDigits: 2 });
const AUD0 = new Intl.NumberFormat('en-AU', { style: 'currency', currency: 'AUD', maximumFractionDigits: 0 });

export function money(v: unknown, whole = false): string {
  const n = typeof v === 'number' ? v : Number(v);
  if (v == null || v === '' || Number.isNaN(n)) return '-';
  return (whole ? AUD0 : AUD).format(n);
}

export function toDate(v: unknown): Date | null {
  if (!v) return null;
  const s = typeof v === 'string' ? v : v instanceof Date ? v.toISOString() : String(v as number);
  const d = /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(`${s}T00:00:00`) : new Date(s.replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? null : d;
}

export function day(v: unknown, withYear = false): string {
  const d = toDate(v);
  if (!d) return '-';
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', ...(withYear ? { year: 'numeric' } : {}) });
}

export function weekday(v: unknown): string {
  const d = toDate(v);
  return d ? d.toLocaleDateString('en-AU', { weekday: 'short', day: 'numeric', month: 'short' }) : '-';
}

export function timeOfDay(v: unknown): string {
  const d = toDate(v);
  return d ? d.toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit' }) : '';
}

/** "today", "yesterday", "3 days ago", or a date, relative to the local calendar. */
export function received(v: unknown): string {
  const d = toDate(v);
  if (!d) return '-';
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((start(new Date()) - start(d)) / 86_400_000);
  if (diff <= 0) return `today ${timeOfDay(d)}`;
  if (diff === 1) return 'yesterday';
  if (diff < 7) return `${diff} days ago`;
  return day(d);
}

export function pct(v: unknown, digits = 0): string {
  const n = Number(v);
  if (v == null || Number.isNaN(n)) return '-';
  return `${(n * 100).toFixed(digits)}%`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString('en-AU')} ${n === 1 ? one : many}`;
}

export function firstName(email: string | null | undefined): string | null {
  if (!email) return null;
  const local = email.split('@')[0] ?? '';
  const part = local.split(/[._-]/)[0];
  if (!part || part === 'local') return null;
  return part.charAt(0).toUpperCase() + part.slice(1);
}

export function greeting(now = new Date()): string {
  const h = now.getHours();
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
}
