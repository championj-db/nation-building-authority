/**
 * Re-run the correctly rendered checks that depend only on the document's own fields, after an
 * officer corrects one of them. Mirrors src/rules.py (ABN check digits, GST arithmetic, addressee,
 * recipient identity, tax invoice label, PO quoted). Checks that need the AP ledger (order match,
 * remaining value, duplicates, delivery) cannot be re-run here and keep the pipeline's result.
 *
 * Shared by the client (to show the effect of a correction) and the server (to judge the
 * decision on the corrected values, not the misread ones).
 */

export const BUYER_ABN = '25357576716';
const ABN_WEIGHTS = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19];
const GST_TOLERANCE = 0.05;

/** Which checks each field feeds. */
export const FIELD_CHECKS: Record<string, string[]> = {
  supplier_abn: ['supplier_abn_valid', 'supplier_abn_matches_vendor'],
  subtotal_ex_gst: ['gst_calculated'],
  gst_amount: ['gst_calculated'],
  total_inc_gst: ['gst_calculated', 'recipient_identity'],
  po_number: ['po_quoted'],
  recipient_name: ['addressed_to_buyer', 'recipient_identity'],
  recipient_abn: ['recipient_identity'],
  document_title: ['tax_invoice_label'],
};

const digits = (v: unknown) => (typeof v === 'string' || typeof v === 'number' ? String(v).replace(/\D/g, '') : '');
const norm = (v: unknown) => (typeof v === 'string' ? v.toLowerCase().replace(/[^0-9a-z]/g, '') : '');

export function abnValid(v: unknown): boolean {
  const d = digits(v);
  if (d.length !== 11 || d[0] === '0') return false;
  const n = d.split('').map(Number);
  n[0] -= 1;
  return n.reduce((s, x, i) => s + x * ABN_WEIGHTS[i], 0) % 89 === 0;
}

export function money(v: unknown): number | null {
  if (typeof v === 'number') return v;
  if (typeof v !== 'string' || !v.trim()) return null;
  const negative = /^\s*[-(]/.test(v) || /CR\s*$/i.test(v);
  const n = Number(v.replace(/[^0-9.]/g, ''));
  return Number.isFinite(n) ? (negative ? -n : n) : null;
}

const isBuyer = (name: unknown) => {
  const n = norm(name);
  return Boolean(n) && (n.includes('nationbuildingauthority') || n === 'nba');
};

export interface RecheckContext {
  docType: string;
  vendorAbn: string | null;
  gstRegistered: boolean;
}

/** Result of one check on the given values; null when it is not field-local. */
export function evaluateLocal(code: string, v: Record<string, string | null>, ctx: RecheckContext): boolean | null {
  const credit = ctx.docType === 'adjustment_note';
  switch (code) {
    case 'supplier_abn_valid':
      return abnValid(v.supplier_abn);
    case 'supplier_abn_matches_vendor':
      return ctx.vendorAbn ? digits(v.supplier_abn) === digits(ctx.vendorAbn) : null;
    case 'po_quoted':
      return Boolean(v.po_number && v.po_number.trim());
    case 'addressed_to_buyer':
      return isBuyer(v.recipient_name);
    case 'tax_invoice_label': {
      if (!ctx.gstRegistered) return true;
      const t = (v.document_title ?? '').toLowerCase();
      return t.includes('tax invoice') || t.includes('adjustment note') || (credit && t.includes('credit'));
    }
    case 'recipient_identity': {
      const total = money(v.total_inc_gst);
      if (total == null || Math.abs(total) < 1000 || !ctx.gstRegistered) return true;
      return isBuyer(v.recipient_name) || digits(v.recipient_abn) === BUYER_ABN;
    }
    case 'gst_calculated': {
      let sub = money(v.subtotal_ex_gst),
        gst = money(v.gst_amount),
        total = money(v.total_inc_gst);
      if (sub == null || gst == null || total == null) return null;
      if (credit) [sub, gst, total] = [Math.abs(sub), Math.abs(gst), Math.abs(total)];
      if (Math.abs(sub + gst - total) > GST_TOLERANCE) return false;
      return ctx.gstRegistered ? Math.abs(gst - sub * 0.1) <= GST_TOLERANCE : Math.abs(gst) <= GST_TOLERANCE;
    }
    default:
      return null;
  }
}

/**
 * The failed checks after applying corrections. Only checks fed by a corrected field are re-run;
 * `rechecked` lists them with their new result.
 */
export function recheck(
  failed: string[],
  values: Record<string, string | null>,
  corrections: Record<string, string>,
  ctx: RecheckContext
): { failed: string[]; rechecked: Record<string, boolean> } {
  const fields = Object.keys(corrections);
  if (!fields.length) return { failed, rechecked: {} };
  const merged = { ...values, ...corrections };
  const codes = new Set(fields.flatMap((f) => FIELD_CHECKS[f] ?? []));
  const rechecked: Record<string, boolean> = {};
  for (const code of codes) {
    const r = evaluateLocal(code, merged, ctx);
    if (r != null) rechecked[code] = r;
  }
  const out = new Set(failed);
  for (const [code, ok] of Object.entries(rechecked)) {
    if (ok) out.delete(code);
    else out.add(code);
  }
  return { failed: [...out], rechecked };
}
