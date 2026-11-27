import type { DecisionRecord } from '../../../shared/contracts';
import { list } from './rows';
import type { QueueRow } from './types';

export const FILTERS = [
  { key: 'all', label: 'All open' },
  { key: 'needs_review', label: 'Needs review' },
  { key: 'exception', label: 'To return' },
  { key: 'awaiting_delivery', label: 'Awaiting delivery' },
  { key: 'ready', label: 'Ready' },
] as const;
export type FilterKey = (typeof FILTERS)[number]['key'];

/** Open items: the gold queue minus anything already decided in the workbench. */
export function openItems(rows: QueueRow[], decided: Map<string, DecisionRecord>): QueueRow[] {
  return rows.filter((r) => !decided.has(r.doc_id));
}

export function applyFilter(rows: QueueRow[], filter: FilterKey, search = ''): QueueRow[] {
  const q = search.trim().toLowerCase();
  return rows.filter(
    (r) =>
      (filter === 'all' || r.status === filter) &&
      (!q ||
        [r.supplier_name, r.invoice_number, r.po_number_quoted, r.doc_id].some((v) =>
          (v ?? '').toLowerCase().includes(q)
        ))
  );
}

export function counts(rows: QueueRow[]): Record<FilterKey, number> {
  const c = { all: rows.length, needs_review: 0, exception: 0, awaiting_delivery: 0, ready: 0 } as Record<
    FilterKey,
    number
  >;
  for (const r of rows) if (r.status in c) c[r.status as FilterKey] += 1;
  return c;
}

export interface Summary {
  dueSoon: number;
  dueSoonValue: number;
  overdue: number;
  interest: number;
  needsReview: number;
  heldFields: number;
  toReturn: number;
}

export function summarise(rows: QueueRow[]): Summary {
  let dueSoon = 0,
    dueSoonValue = 0,
    overdue = 0,
    interest = 0,
    needsReview = 0,
    heldFields = 0,
    toReturn = 0;
  for (const r of rows) {
    if (r.clock_state === 'overdue') {
      overdue += 1;
      interest += r.interest_accrued ?? 0;
    } else if (r.business_days_left != null && r.business_days_left <= 5 && r.clock_state !== 'not_started') {
      dueSoon += 1;
      dueSoonValue += r.total_inc_gst ?? 0;
    }
    if (r.status === 'needs_review') {
      needsReview += 1;
      heldFields += list(r.held_fields).length;
    }
    if (r.status === 'exception') toReturn += 1;
  }
  return { dueSoon, dueSoonValue, overdue, interest, needsReview, heldFields, toReturn };
}

/** The clock in words: what an officer needs to read at a glance. */
/** The line under the clock: when it was or is due. */
export function dueText(r: Pick<QueueRow, 'clock_state' | 'pay_by_date'>): string {
  if (!r.pay_by_date) return 'no pay-by date';
  const d = new Date(`${r.pay_by_date}T00:00:00`).toLocaleDateString('en-AU', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
  return r.clock_state === 'overdue' ? `was due ${d}` : `pay by ${d}`;
}

export function clockText(
  r: Pick<QueueRow, 'clock_state' | 'business_days_left' | 'calendar_days_left' | 'status'> & { doc_type?: string }
): { short: string; long: string } {
  if (r.doc_type === 'adjustment_note')
    return { short: 'No payment', long: 'A credit: it reduces what is owed, so no payment clock applies' };
  if (r.clock_state === 'not_started') {
    if (r.status === 'exception') return { short: 'Not started', long: 'Clock not started: not correctly rendered' };
    if (r.status === 'needs_review')
      return { short: 'Not started', long: 'Clock not started: no delivery receipt matched yet' };
    return { short: 'Not started', long: 'Clock not started: delivery not acknowledged' };
  }
  if (r.clock_state === 'overdue') {
    const d = Math.abs(r.calendar_days_left ?? 0);
    return {
      short: `${d} ${d === 1 ? 'day' : 'days'} late`,
      long: `${d} calendar ${d === 1 ? 'day' : 'days'} past the pay-by date`,
    };
  }
  const b = r.business_days_left ?? 0;
  if (b <= 0) return { short: 'Pay today', long: 'The last business day before the pay-by date is today' };
  return {
    short: `${b} business ${b === 1 ? 'day' : 'days'} left`,
    long: `${b} business ${b === 1 ? 'day' : 'days'} to the pay-by date`,
  };
}
