import { describe, expect, it } from 'vitest';
import {
  bandFor,
  caseIdSchema,
  outcomeSchema,
  precision,
  reasonLabel,
  reduceEvents,
  resolveSchema,
  type CaseEvent,
} from './contracts';

const ev = (event_type: CaseEvent['event_type'], created_at: string, actor = 'a@x', detail: string | null = null): CaseEvent => ({
  event_id: created_at,
  case_id: 'IP-2048',
  event_type,
  actor,
  detail,
  created_at,
});

describe('outcomeSchema', () => {
  it('accepts a reason that belongs to the outcome', () => {
    const r = outcomeSchema.safeParse({ outcome: 'escalated', reasonCode: 'evidence_supports', notes: 'Checked ABR and bank records.' });
    expect(r.success).toBe(true);
  });
  it('rejects a reason from the other outcome', () => {
    const r = outcomeSchema.safeParse({ outcome: 'cleared', reasonCode: 'evidence_supports', notes: 'Checked ABR and bank records.' });
    expect(r.success).toBe(false);
  });
  it('requires substantive notes', () => {
    const r = outcomeSchema.safeParse({ outcome: 'cleared', reasonCode: 'documents_verified', notes: '  ok  ' });
    expect(r.success).toBe(false);
  });
});

describe('reduceEvents', () => {
  it('is null with no events (unassigned)', () => expect(reduceEvents([])).toBeNull());
  it('assign then release returns to unassigned', () => {
    expect(reduceEvents([ev('released', '2026-01-02'), ev('assigned', '2026-01-01')])?.status).toBe('unassigned');
  });
  it('an outcome is final and keeps the assignee', () => {
    const s = reduceEvents([
      ev('assigned', '2026-01-01', 'inv@x'),
      ev('outcome', '2026-01-02', 'inv@x', 'escalated:evidence_supports'),
      ev('released', '2026-01-03', 'other@x'),
    ]);
    expect(s).toMatchObject({ status: 'closed', outcome: 'escalated', reason_code: 'evidence_supports', assignee: 'inv@x' });
  });
});

describe('helpers', () => {
  it('bands scores', () => {
    expect(bandFor(80)).toBe('high');
    expect(bandFor(79)).toBe('medium');
  });
  it('precision', () => {
    expect(precision(3, 1)).toBe(0.75);
    expect(precision(0, 0)).toBeNull();
  });
  it('case ids', () => {
    expect(caseIdSchema.safeParse('IP-2048').success).toBe(true);
    expect(caseIdSchema.safeParse("IP-1' OR 1=1").success).toBe(false);
  });
  it('reason labels', () => expect(reasonLabel('entity_match_incorrect')).toBe('Records were linked in error'));
  it('rejects unsafe identifiers', () => {
    expect(() => resolveSchema({ DATABRICKS_CATALOG: 'a;drop', DATABRICKS_SCHEMA: 's' })).toThrow();
    expect(resolveSchema({ DATABRICKS_CATALOG: 'cat', DATABRICKS_SCHEMA: 'sch' })).toEqual({ catalog: 'cat', schema: 'sch' });
  });
});
