import { describe, expect, it } from 'vitest';
import { decisionProblem, decisionSchema, returnNotice, type GovernedSnapshot } from './contracts';

const snap = (over: Partial<GovernedSnapshot> = {}): GovernedSnapshot => ({
  docId: 'DOC-000001',
  docType: 'tax_invoice',
  status: 'ready',
  lowestConfidence: 0.97,
  heldFields: [],
  failedChecks: [],
  ...over,
});
const input = (over: Record<string, unknown> = {}) => decisionSchema.parse({ decision: 'accepted', ...over });

describe('accepting', () => {
  it('accepts a ready invoice', () => {
    expect(decisionProblem(input(), snap())).toBeNull();
  });
  it('locks accept until every held field is confirmed or corrected', () => {
    const s = snap({ status: 'needs_review', heldFields: ['po_number', 'total_inc_gst'] });
    expect(decisionProblem(input(), s)).toMatch(/all 2 held fields/);
    expect(decisionProblem(input({ confirmedFields: ['po_number'] }), s)).toMatch(/the held field/);
    expect(
      decisionProblem(
        input({
          confirmedFields: ['po_number'],
          corrections: [{ field: 'total_inc_gst', extracted: '1.00', corrected: '11330.00' }],
        }),
        s
      )
    ).toBeNull();
  });
  it('does not let a malformed value be confirmed as read', () => {
    const s = snap({ status: 'needs_review', heldFields: ['supplier_abn'], invalidFields: ['supplier_abn'] });
    expect(decisionProblem(input({ confirmedFields: ['supplier_abn'] }), s)).toMatch(/held field/);
    expect(
      decisionProblem(
        input({ corrections: [{ field: 'supplier_abn', extracted: '83792749072122', corrected: '83792749072' }] }),
        s
      )
    ).toBeNull();
  });
  it('needs an override note to accept past a failed supplier check', () => {
    const s = snap({ status: 'exception', failedChecks: ['po_quoted'] });
    expect(decisionProblem(input(), s)).toMatch(/Record why/);
    expect(decisionProblem(input({ note: 'Contract manager confirmed the order by email' }), s)).toBeNull();
  });
  it('never accepts an invoice without a delivery receipt', () => {
    const s = snap({ status: 'awaiting_delivery', failedChecks: ['delivery_acknowledged'] });
    expect(decisionProblem(input({ note: 'please just pay it anyway' }), s)).toMatch(
      /Delivery has not been acknowledged/
    );
  });
});

describe('returning', () => {
  it('needs at least one criterion, and only real ones', () => {
    const s = snap({ status: 'exception', failedChecks: ['gst_calculated'] });
    expect(decisionProblem(input({ decision: 'returned' }), s)).toMatch(/at least one/);
    expect(decisionProblem(input({ decision: 'returned', reasonCodes: ['made_up'] }), s)).toMatch(
      /not a correctly rendered criterion/
    );
    expect(decisionProblem(input({ decision: 'returned', reasonCodes: ['delivery_acknowledged'] }), s)).toMatch(
      /not a correctly rendered criterion/
    );
    expect(decisionProblem(input({ decision: 'returned', reasonCodes: ['gst_calculated'] }), s)).toBeNull();
    expect(decisionProblem(input({ decision: 'returned', reasonCodes: ['other'] }), s)).toMatch(/Explain/);
  });
  it('writes a notice naming each failed criterion', () => {
    const text = returnNotice('Kestrel Ridge Consulting Pty Ltd', 'KRC-1', ['po_quoted', 'gst_calculated'], '');
    expect(text).toContain('invoice KRC-1');
    expect(text).toContain('does not quote a purchase order');
    expect(text).toContain('GST or total');
  });
});

describe('other decisions', () => {
  it('reclassify needs a different type; actioned is for non-invoices', () => {
    expect(decisionProblem(input({ decision: 'reclassified' }), snap())).toMatch(/Choose/);
    expect(decisionProblem(input({ decision: 'reclassified', reclassifyTo: 'tax_invoice' }), snap())).toMatch(
      /already/
    );
    expect(decisionProblem(input({ decision: 'actioned' }), snap())).toMatch(/not marked actioned/);
    expect(
      decisionProblem(input({ decision: 'actioned' }), snap({ docType: 'correspondence', status: 'not_invoice' }))
    ).toBeNull();
    expect(decisionProblem(input({ decision: 'accepted' }), snap({ docType: 'quote', status: 'not_invoice' }))).toMatch(
      /Only invoices/
    );
  });
});
