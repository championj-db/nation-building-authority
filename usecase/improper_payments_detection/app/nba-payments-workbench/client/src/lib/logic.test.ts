import { describe, expect, it } from 'vitest';
import { applyFilters, DEFAULT_FILTERS, mergeState, summarise, tabCounts, type CaseRow } from './queue';
import { edgePath, layoutGraph } from './graphLayout';

const row = (id: string, score: number, value: number, extra: Partial<CaseRow> = {}): CaseRow => ({
  case_id: id,
  entity_id: `e-${id}`,
  entity_label: `Entity ${id}`,
  entity_sub: 'Supplier',
  entity_kind: 'supplier',
  program: 'supplier',
  program_label: 'Supplier payments',
  primary_signal: 'shared_bank_account',
  primary_signal_label: 'Shared bank account',
  risk_score: score,
  risk_band: score >= 80 ? 'high' : 'medium',
  payment_value: value,
  payment_count: 1,
  opened_date: '2026-11-01',
  age_days: 3,
  model_version: '1',
  scored_ts: '2026-11-26 08:15:00',
  ...extra,
});

const now = new Date('2026-11-26T03:00:00Z');
const rows = [row('IP-2001', 92, 100), row('IP-2002', 60, 900, { program: 'claims' }), row('IP-2003', 85, 50)];
const states = [
  { case_id: 'IP-2002', status: 'review' as const, assignee: 'me@x', updated_at: '2026-11-26T01:00:00Z', outcome: null, reason_code: null },
  { case_id: 'IP-2003', status: 'closed' as const, assignee: 'you@x', updated_at: '2026-11-26T02:00:00Z', outcome: 'cleared' as const, reason_code: 'documents_verified' },
];

describe('queue', () => {
  const cases = mergeState(rows, states, now);
  it('overlays state and counts tabs', () => {
    expect(tabCounts(cases, 'me@x')).toEqual({ all: 2, unassigned: 1, review: 1, mine: 1, closed: 1 });
  });
  it('sorts by risk then value, and by value', () => {
    expect(applyFilters(cases, 'all', DEFAULT_FILTERS, null).map((c) => c.case_id)).toEqual(['IP-2001', 'IP-2002']);
    expect(applyFilters(cases, 'all', { ...DEFAULT_FILTERS, sort: 'value' }, null)[0]?.case_id).toBe('IP-2002');
  });
  it('filters by every search word, band and program', () => {
    expect(applyFilters(cases, 'all', { ...DEFAULT_FILTERS, term: 'ip-2001 shared' }, null)).toHaveLength(1);
    expect(applyFilters(cases, 'all', { ...DEFAULT_FILTERS, band: 'medium' }, null)).toHaveLength(1);
    expect(applyFilters(cases, 'all', { ...DEFAULT_FILTERS, program: 'claims' }, null)[0]?.case_id).toBe('IP-2002');
  });
  it('summarises open work only', () => {
    expect(summarise(cases)).toMatchObject({ unassigned: 1, review: 1, openValue: 1000, openCount: 2 });
  });
});

describe('graph layout', () => {
  const nodes = [
    { node_id: 's', label: 'North Harbour', kind: 'supplier', sub_label: 'Supplier', role: 'subject' },
    { node_id: 'a', label: 'Account ··824', kind: 'bank_account', sub_label: 'Bank account', role: 'link' },
    { node_id: 'o', label: 'Officer 029', kind: 'officer', sub_label: 'Approver', role: 'link' },
    { node_id: 'r', label: 'Coastal Trade', kind: 'supplier', sub_label: 'Related supplier', role: 'related' },
  ];
  const edges = [
    { src: 's', dst: 'a', relation: 'pays into' },
    { src: 'r', dst: 'a', relation: 'pays into' },
    { src: 's', dst: 'o', relation: 'approved by' },
    { src: 's', dst: 'ghost', relation: 'x' },
  ];
  const g = layoutGraph(nodes, edges);
  it('places subject left, links middle, related right', () => {
    const x = Object.fromEntries(g.nodes.map((n) => [n.node_id, n.x + n.w / 2]));
    expect(x.s).toBeLessThan(x.a);
    expect(x.a).toBeLessThan(x.r);
    expect(g.edges).toHaveLength(3);
  });
  it('keeps every box inside the canvas', () => {
    for (const n of g.nodes) {
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x + n.w).toBeLessThanOrEqual(g.width);
      expect(n.y + n.h).toBeLessThanOrEqual(g.height);
    }
  });
  it('is deterministic', () => expect(layoutGraph(nodes, edges)).toEqual(g));
  it('draws edges between facing sides', () => {
    const [s, a] = [g.nodes.find((n) => n.node_id === 's')!, g.nodes.find((n) => n.node_id === 'a')!];
    expect(edgePath(s, a).x1).toBe(s.x + s.w);
  });
});
