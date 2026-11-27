import { describe, expect, it } from 'vitest';
import { normalizeRow } from './rows';
import { applyFilter, clockText, counts, summarise } from './queue';
import type { QueueRow } from './types';

const row = (over: Partial<QueueRow>): QueueRow => ({
  doc_id: 'DOC-000001',
  doc_type: 'tax_invoice',
  status: 'ready',
  status_label: 'Ready to accept',
  supplier_name: 'Kestrel Ridge',
  invoice_number: 'KRC-1',
  po_number: 'PO-1',
  po_number_quoted: 'PO-1',
  total_inc_gst: 1000,
  lowest_required_confidence: 0.98,
  held_fields: '[]',
  failed_checks: '[]',
  arrival_ts: '2026-11-20 09:00:00',
  arrival_date: '2026-11-20',
  channel: 'email',
  receipt_date: null,
  trigger_date: null,
  pay_by_date: '2026-12-10',
  pay_by_2027_date: null,
  term_label: null,
  clock_regime: null,
  calendar_days_left: 10,
  business_days_left: 8,
  business_days_left_2027: 2,
  clock_state: 'on_track',
  interest_accrued: 0,
  contract_manager: null,
  ...over,
});

describe('queue', () => {
  const rows = [
    row({ doc_id: 'DOC-000001' }),
    row({
      doc_id: 'DOC-000002',
      status: 'needs_review',
      held_fields: '["po_number","gst_amount"]',
      business_days_left: 2,
      clock_state: 'due_soon',
    }),
    row({
      doc_id: 'DOC-000003',
      status: 'exception',
      clock_state: 'not_started',
      business_days_left: null,
      pay_by_date: null,
    }),
    row({
      doc_id: 'DOC-000004',
      clock_state: 'overdue',
      calendar_days_left: -3,
      interest_accrued: 12.5,
      supplier_name: 'Granite Vale',
    }),
  ];
  it('summarises the tiles', () => {
    expect(summarise(rows)).toMatchObject({
      dueSoon: 1,
      overdue: 1,
      interest: 12.5,
      needsReview: 1,
      heldFields: 2,
      toReturn: 1,
    });
  });
  it('filters and searches', () => {
    expect(counts(rows)).toMatchObject({ all: 4, ready: 2, needs_review: 1, exception: 1 });
    expect(applyFilter(rows, 'all', 'granite').map((r) => r.doc_id)).toEqual(['DOC-000004']);
  });
  it('words the clock', () => {
    expect(clockText(rows[2]).long).toMatch(/not correctly rendered/);
    expect(clockText(rows[3]).short).toBe('3 days late');
    expect(clockText(row({ business_days_left: 0 })).short).toBe('Pay today');
  });
});

describe('normalizeRow', () => {
  it('keeps identifiers as strings and converts measures', () => {
    const r = normalizeRow({
      value: '51824753556',
      invoice_number: '20431',
      total_inc_gst: '11330.0',
      required: 'true',
      business_days_left: '4',
    });
    expect(r).toEqual({
      value: '51824753556',
      invoice_number: '20431',
      total_inc_gst: 11330,
      required: true,
      business_days_left: 4,
    });
  });
});
