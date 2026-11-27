import { describe, expect, it } from 'vitest';
import { abnValid, recheck } from './recheck';

const ctx = { docType: 'tax_invoice', vendorAbn: '83 792 749 072', gstRegistered: true };
const values = {
  supplier_abn: '83792749072122',
  subtotal_ex_gst: '70241.80',
  gst_amount: '7024.18',
  total_inc_gst: '77265.98',
  recipient_name: 'Nation Building Authority',
  recipient_abn: null,
  po_number: 'PO-1',
  document_title: 'TAX INVOICE',
};

describe('recheck', () => {
  it('validates ABNs like the pipeline', () => {
    expect(abnValid('51 824 753 556')).toBe(true);
    expect(abnValid('83792749072122')).toBe(false);
  });
  it('clears the ABN checks once the misread ABN is corrected', () => {
    const r = recheck(
      ['supplier_abn_valid', 'supplier_abn_matches_vendor'],
      values,
      { supplier_abn: '83792749072' },
      ctx
    );
    expect(r.failed).toEqual([]);
    expect(r.rechecked).toEqual({ supplier_abn_valid: true, supplier_abn_matches_vendor: true });
  });
  it('can also introduce a failure, and leaves ledger checks alone', () => {
    const r = recheck(['within_po_value'], values, { gst_amount: '7500.00' }, ctx);
    expect(r.failed.sort()).toEqual(['gst_calculated', 'within_po_value']);
  });
  it('treats adjustment note amounts as magnitudes', () => {
    const r = recheck(
      [],
      { ...values, subtotal_ex_gst: '1726.53', gst_amount: '172.65', total_inc_gst: '-1899.18' },
      { gst_amount: '172.65' },
      { ...ctx, docType: 'adjustment_note' }
    );
    expect(r.failed).toEqual([]);
  });
});
