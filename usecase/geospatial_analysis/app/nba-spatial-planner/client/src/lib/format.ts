const integer = new Intl.NumberFormat('en-AU', { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat('en-AU', { notation: 'compact', maximumFractionDigits: 1 });

/** A suppressed count renders as "<10" (the disclosure threshold), never as a number. */
export function people(value: number | null | undefined, minCount: number, suppressed = value == null) {
  if (suppressed) return `<${minCount}`;
  return integer.format(value ?? 0);
}

export function peopleCompact(value: number | null | undefined, minCount: number) {
  if (value == null) return `<${minCount}`;
  return value >= 100_000 ? compact.format(value) : integer.format(value);
}

export function pct(value: number | null | undefined, digits = 1) {
  if (value == null) return '–';
  if (value > 0 && value < 0.001) return '<0.1%';
  return `${(value * 100).toFixed(digits)}%`;
}

/** Distances come from 1 km bands, so whole kilometres are the honest precision. */
export function km(value: number | null | undefined) {
  if (value == null) return '–';
  if (value >= 300) return '300+ km';
  return `${integer.format(value)} km`;
}

export function dateTime(value: string | number | Date | null | undefined) {
  if (value == null || value === '') return '–';
  const d = value instanceof Date ? value : new Date(typeof value === 'number' ? value : value.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return '–';
  return d.toLocaleString('en-AU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function relativeDay(value: string | number | Date | null | undefined) {
  if (value == null || value === '') return '–';
  const d = value instanceof Date ? value : new Date(typeof value === 'number' ? value : value.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return '–';
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days <= 0) return `today ${d.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' })}`;
  if (days === 1) return 'yesterday';
  if (days < 7) return `${days} days ago`;
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' });
}

/** "alex.morgan@agency.gov.au" -> "Alex Morgan". */
export function officerName(raw: string | null | undefined) {
  if (!raw) return 'Officer';
  const local = raw.split('@')[0] ?? raw;
  const words = local.split(/[._-]+/).filter(Boolean);
  return words.map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ') || raw;
}

export function plural(n: number, one: string, many = `${one}s`) {
  return `${integer.format(n)} ${n === 1 ? one : many}`;
}
