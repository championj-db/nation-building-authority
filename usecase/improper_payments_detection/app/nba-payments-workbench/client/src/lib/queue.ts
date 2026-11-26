import type { CaseState, CaseStatus, RiskBand } from '../../../shared/contracts';
import { isTodaySydney } from './format';

/** One row of gold_case (config/queries/case_queue.obo.sql). */
export interface CaseRow {
  case_id: string;
  entity_id: string;
  entity_label: string;
  entity_sub: string;
  /** supplier | claimant_cluster */
  entity_kind: string;
  /** supplier | claims */
  program: string;
  program_label: string;
  primary_signal: string;
  primary_signal_label: string;
  risk_score: number;
  risk_band: RiskBand;
  payment_value: number;
  payment_count: number;
  opened_date: string;
  age_days: number;
  model_version: string;
  scored_ts: string;
}

export interface QueueCase extends CaseRow {
  status: CaseStatus;
  assignee: string | null;
  updated_at: string | null;
  outcome: CaseState['outcome'];
  closedToday: boolean;
}

export type QueueTab = 'all' | 'unassigned' | 'review' | 'mine' | 'closed';
export type SortKey = 'risk' | 'value' | 'age';

export interface Filters {
  term: string;
  band: 'all' | RiskBand;
  /** 'all' or a program code */
  program: string;
  sort: SortKey;
}
export const DEFAULT_FILTERS: Filters = { term: '', band: 'all', program: 'all', sort: 'risk' };

/** Overlay Lakebase case state on the governed queue. */
export function mergeState(rows: readonly CaseRow[], states: readonly CaseState[], now = new Date()): QueueCase[] {
  const byId = new Map(states.map((s) => [s.case_id, s]));
  return rows.map((row) => {
    const s = byId.get(row.case_id);
    return {
      ...row,
      status: s?.status ?? 'unassigned',
      assignee: s?.assignee ?? null,
      updated_at: s?.updated_at ?? null,
      outcome: s?.outcome ?? null,
      closedToday: s?.status === 'closed' && isTodaySydney(s.updated_at, now),
    };
  });
}

/** "All cases" is the open queue; closed cases stay visible for the day they were decided. */
export function inTab(c: QueueCase, tab: QueueTab, user: string | null): boolean {
  switch (tab) {
    case 'all':
      return c.status !== 'closed';
    case 'unassigned':
      return c.status === 'unassigned';
    case 'review':
      return c.status === 'review';
    case 'mine':
      return c.status === 'review' && c.assignee != null && c.assignee === user;
    case 'closed':
      return c.closedToday;
  }
}

export function tabCounts(cases: readonly QueueCase[], user: string | null): Record<QueueTab, number> {
  const tabs: QueueTab[] = ['all', 'unassigned', 'review', 'mine', 'closed'];
  return Object.fromEntries(tabs.map((t) => [t, cases.filter((c) => inTab(c, t, user)).length])) as Record<QueueTab, number>;
}

function matches(c: QueueCase, term: string) {
  if (!term) return true;
  const haystack = `${c.case_id} ${c.entity_label} ${c.entity_sub} ${c.primary_signal_label} ${c.program_label}`.toLowerCase();
  return term
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
}

const COMPARE: Record<SortKey, (a: QueueCase, b: QueueCase) => number> = {
  risk: (a, b) => b.risk_score - a.risk_score || b.payment_value - a.payment_value,
  value: (a, b) => b.payment_value - a.payment_value || b.risk_score - a.risk_score,
  age: (a, b) => b.age_days - a.age_days || b.risk_score - a.risk_score,
};

export function applyFilters(cases: readonly QueueCase[], tab: QueueTab, filters: Filters, user: string | null): QueueCase[] {
  return cases
    .filter(
      (c) =>
        inTab(c, tab, user) &&
        (filters.band === 'all' || c.risk_band === filters.band) &&
        (filters.program === 'all' || c.program === filters.program) &&
        matches(c, filters.term.trim()),
    )
    .sort((a, b) => COMPARE[filters.sort](a, b) || a.case_id.localeCompare(b.case_id));
}

export function summarise(cases: readonly QueueCase[]) {
  const open = cases.filter((c) => c.status !== 'closed');
  return {
    unassigned: cases.filter((c) => c.status === 'unassigned').length,
    review: cases.filter((c) => c.status === 'review').length,
    openValue: open.reduce((sum, c) => sum + c.payment_value, 0),
    openCount: open.length,
    highOpen: open.filter((c) => c.risk_band === 'high').length,
  };
}

export function filtersActive(f: Filters) {
  return f.term.trim() !== '' || f.band !== 'all' || f.program !== 'all' || f.sort !== 'risk';
}
