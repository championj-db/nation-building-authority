export function num(value: unknown): number {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

/** AUD millions -> "$1.2bn"; values that round to zero never show a sign ("$0.0bn", not "−$0.0bn"). */
export function bn(valueAudM: unknown, signed = false): string {
  const value = num(valueAudM) / 1000;
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return '$0.0bn';
  const sign = rounded < 0 ? '−' : signed ? '+' : '';
  return `${sign}$${Math.abs(rounded).toFixed(1)}bn`;
}

/** AUD millions -> "$240m" below $1bn, otherwise "$1.2bn". */
export function money(valueAudM: unknown, signed = false): string {
  const value = num(valueAudM);
  if (Math.abs(value) >= 995) return bn(value, signed);
  const rounded = Math.round(value);
  if (rounded === 0) return '$0m';
  const sign = rounded < 0 ? '−' : signed ? '+' : '';
  return `${sign}$${Math.abs(rounded).toLocaleString('en-AU')}m`;
}

export function pct(value: unknown, digits = 0): string {
  return `${num(value).toFixed(digits)}%`;
}

export function months(value: unknown): string {
  const n = Math.round(num(value));
  if (n === 0) return 'on time';
  return `${n > 0 ? '+' : '−'}${Math.abs(n)} mo`;
}

export function date(value: unknown): string {
  if (!value) return '—';
  const text = String(value);
  const parsed = new Date(text.length <= 10 ? `${text}T00:00:00` : text);
  if (Number.isNaN(parsed.getTime())) return text;
  return new Intl.DateTimeFormat('en-AU', { day: 'numeric', month: 'short', year: 'numeric' }).format(parsed);
}

export function dateTime(value: unknown): string {
  if (!value) return '—';
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat('en-AU', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' }).format(parsed);
}

export function monthLabel(value: unknown): string {
  if (!value) return '';
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  return new Intl.DateTimeFormat('en-AU', { month: 'short', year: '2-digit' }).format(parsed);
}

export function tone(value: unknown, inverse = false): 'bad' | 'good' | '' {
  const n = num(value);
  if (Math.abs(n) < 0.5) return '';
  return (n > 0) !== inverse ? 'bad' : 'good';
}

export function initials(email?: string | null): string {
  if (!email) return 'AP';
  return email
    .split('@')[0]
    .split(/[._-]/)
    .map((part) => part[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
}

export function personName(email?: string | null): string {
  if (!email) return 'Unknown user';
  if (!email.includes('@')) return email;
  return email
    .split('@')[0]
    .split(/[._-]/)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export const LEVER_LABELS: Record<string, string> = {
  defer_months: 'Defer',
  accelerate_months: 'Accelerate',
  escalation_delta_pp: 'Escalation',
  capacity_uplift_pct: 'Capacity uplift',
  scope_change_aud_m: 'Scope change',
  exclude_project: 'Exclude',
};

export function leverValue(type: string, value: unknown): string {
  const n = num(value);
  switch (type) {
    case 'defer_months':
    case 'accelerate_months':
      return `${n} months`;
    case 'escalation_delta_pp':
      return `${n > 0 ? '+' : ''}${n} pp a year`;
    case 'capacity_uplift_pct':
      return `+${n}% supply`;
    case 'scope_change_aud_m':
      return money(n, true);
    default:
      return 'removed from horizon';
  }
}

/** SQL booleans can arrive as true/false or as "true"/"false" strings. */
export function yes(value: unknown): boolean {
  return value === true || value === 'true' || value === 1 || value === '1';
}

const CAUSE_WORDS: Record<string, string> = {
  defer_months: 'Deferred', accelerate_months: 'Accelerated', escalation_delta_pp: 'Escalation', capacity_uplift_pct: 'Capacity uplift',
  scope_change_aud_m: 'Scope change', exclude_project: 'Excluded',
};

/** "defer_months 12 (LV-…); optimizer defer 6 mo (FY29 Skilled civil labour at 118%)" -> readable causes. */
export function cause(text: unknown): string {
  return String(text ?? '')
    .split(';')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const lever = /^(\w+) (-?[\d.]+) \(([^)]+)\)$/.exec(part);
      if (lever && CAUSE_WORDS[lever[1]]) {
        const [, type, value] = lever;
        return `${CAUSE_WORDS[type]} ${type === 'exclude_project' ? '' : leverValue(type, value)}`.trim();
      }
      const seq = /^optimizer defer (\d+) mo \((.+)\)$/.exec(part);
      if (seq) return `Sequencer deferred ${seq[1]} mo (${seq[2]})`;
      return part;
    })
    .join(' · ');
}
