import { z } from 'zod';

/**
 * Contracts shared by the server and the client. Documents, fields and checks come from the
 * governed gold layer written by ../../src (Unity Catalog, read on behalf of the signed-in
 * officer). Decisions and field corrections are app-owned records in Lakebase Postgres (schema
 * `daw`), read back into Unity Catalog by src/05_sync_decisions.py.
 *
 * The decision rules live here so the client can explain them and the server can enforce them
 * with the same code.
 */

export const REVIEW_THRESHOLD = 0.85;

export const STATUSES = {
  ready: 'Ready to accept',
  needs_review: 'Needs review',
  exception: 'Exception',
  awaiting_delivery: 'Awaiting delivery',
  not_invoice: 'Not an invoice',
  processing: 'Processing',
} as const;
export type Status = keyof typeof STATUSES;

export const CHECK_LABELS: Record<string, string> = {
  addressed_to_buyer: 'Addressed to the Authority',
  tax_invoice_label: 'Identified as a tax invoice',
  supplier_abn_valid: 'Supplier ABN is valid',
  supplier_abn_matches_vendor: 'ABN matches vendor record',
  recipient_identity: 'Recipient identity shown',
  po_quoted: 'Purchase order quoted',
  po_matches: 'Purchase order matches',
  gst_calculated: 'GST correctly calculated',
  within_po_value: 'Within remaining order value',
  not_duplicate: 'Not already received',
  delivery_acknowledged: 'Delivery acknowledged',
};

/** Checks whose failure is the supplier's to fix: the invoice is not correctly rendered. */
export const SUPPLIER_FAULT_CHECKS = Object.keys(CHECK_LABELS).filter((c) => c !== 'delivery_acknowledged');

/** The extracted fields each check reads. A check that fails on a field still held for review
 *  may be failing on a misread, so it cannot be relied on until that field is resolved. */
export const CHECK_FIELDS: Record<string, string[]> = {
  addressed_to_buyer: ['recipient_name'],
  tax_invoice_label: ['document_title'],
  supplier_abn_valid: ['supplier_abn'],
  supplier_abn_matches_vendor: ['supplier_abn'],
  recipient_identity: ['recipient_name', 'recipient_abn', 'total_inc_gst'],
  po_quoted: ['po_number'],
  po_matches: ['po_number'],
  gst_calculated: ['subtotal_ex_gst', 'gst_amount', 'total_inc_gst'],
  within_po_value: ['po_number', 'total_inc_gst'],
  not_duplicate: ['invoice_number'],
  delivery_acknowledged: ['po_number', 'total_inc_gst'],
};

export const FIELD_NAMES: Record<string, string> = {
  supplier_name: 'Supplier',
  supplier_abn: 'Supplier ABN',
  recipient_name: 'Addressed to',
  recipient_abn: 'Recipient ABN',
  document_title: 'Document title',
  invoice_number: 'Invoice number',
  invoice_date: 'Invoice date',
  po_number: 'Purchase order',
  subtotal_ex_gst: 'Amount excl. GST',
  gst_amount: 'GST',
  total_inc_gst: 'Total incl. GST',
};

/** Held fields behind a check that the officer has not yet confirmed or corrected. */
export function unresolvedBehind(
  code: string,
  heldFields: string[],
  confirmed: string[],
  corrected: string[],
  invalid: string[] = []
): string[] {
  const done = new Set([...confirmed.filter((f) => !invalid.includes(f)), ...corrected]);
  return (CHECK_FIELDS[code] ?? []).filter((f) => heldFields.includes(f) && !done.has(f));
}

export const DECISIONS = ['accepted', 'returned', 'reclassified', 'actioned'] as const;
export type Decision = (typeof DECISIONS)[number];

export const DOC_TYPES = {
  tax_invoice: 'Tax invoice',
  adjustment_note: 'Adjustment note',
  supplier_statement: 'Supplier statement',
  correspondence: 'Correspondence',
  quote: 'Quote',
} as const;
export type DocType = keyof typeof DOC_TYPES;

export const NOTE_MAX = 1500;
export const OVERRIDE_NOTE_MIN = 15;

export const docIdSchema = z.string().regex(/^DOC-\d{6}$/, 'Unknown document reference');

const correctionSchema = z.object({
  field: z.string().regex(/^[a-z_]{2,40}$/),
  extracted: z.string().max(400).nullable(),
  corrected: z.string().trim().min(1, 'Enter the corrected value').max(400),
});
export type Correction = z.infer<typeof correctionSchema>;

export const decisionSchema = z.object({
  decision: z.enum(DECISIONS),
  reasonCodes: z.array(z.string().max(60)).max(12).default([]),
  note: z.string().trim().max(NOTE_MAX).default(''),
  corrections: z.array(correctionSchema).max(20).default([]),
  confirmedFields: z
    .array(z.string().regex(/^[a-z_]{2,40}$/))
    .max(20)
    .default([]),
  reclassifyTo: z.enum(Object.keys(DOC_TYPES) as [DocType, ...DocType[]]).optional(),
  handlingSeconds: z.number().int().min(0).max(86_400).default(0),
});
export type DecisionInput = z.infer<typeof decisionSchema>;

/** What the governed gold layer says about a document at the moment of decision. */
export interface GovernedSnapshot {
  docId: string;
  docType: string;
  status: Status;
  lowestConfidence: number | null;
  heldFields: string[];
  failedChecks: string[];
  /** Fields whose value does not parse as its type: they can be corrected, never confirmed as read. */
  invalidFields?: string[];
}

/**
 * The rules a decision must satisfy. Returns the first broken rule as an officer-readable
 * sentence, or null when the decision may be recorded.
 *
 * - Accepting confirms the invoice is correctly rendered. Every field held for review must be
 *   confirmed against the page or corrected first; a failed supplier check needs an override
 *   note; an invoice without a delivery receipt cannot be accepted yet.
 * - Returning sends it back with at least one stated criterion.
 * - Reclassifying needs the type it should have been.
 * - "Actioned" closes a statement, letter or quote.
 */
export function decisionProblem(input: DecisionInput, snap: GovernedSnapshot): string | null {
  const isInvoice = snap.docType === 'tax_invoice' || snap.docType === 'adjustment_note';
  if (input.decision === 'reclassified') {
    if (!input.reclassifyTo) return 'Choose the document type it should be.';
    if (input.reclassifyTo === snap.docType) return 'That is the type it already has.';
    return null;
  }
  if (input.decision === 'actioned') {
    return isInvoice ? 'Invoices are accepted or returned, not marked actioned.' : null;
  }
  if (!isInvoice) return 'Only invoices and adjustment notes are accepted or returned.';
  if (input.decision === 'returned') {
    if (!input.reasonCodes.length) return 'Choose at least one criterion the invoice does not meet.';
    const unknown = input.reasonCodes.filter((c) => c !== 'other' && !SUPPLIER_FAULT_CHECKS.includes(c));
    if (unknown.length) return 'One of those reasons is not a correctly rendered criterion.';
    if (input.reasonCodes.includes('other') && input.note.length < OVERRIDE_NOTE_MIN) {
      return 'Explain the other reason in the note to the supplier.';
    }
    // A criterion that rests on a held field may only be failing because the field was misread.
    const corrected = input.corrections.map((c) => c.field);
    for (const code of input.reasonCodes) {
      const behind = unresolvedBehind(code, snap.heldFields, input.confirmedFields, corrected, snap.invalidFields);
      if (behind.length) {
        return `Confirm or correct ${behind.map((f) => FIELD_NAMES[f] ?? f).join(' and ')} before returning the invoice for "${CHECK_LABELS[code]}".`;
      }
    }
    if (input.reasonCodes.some((c) => c !== 'other' && !snap.failedChecks.includes(c)) && input.note.length < OVERRIDE_NOTE_MIN) {
      return 'One of those criteria passed its check. Explain in the note why the invoice does not meet it.';
    }
    return null;
  }
  // accepted
  if (snap.status === 'awaiting_delivery' || snap.failedChecks.includes('delivery_acknowledged')) {
    return 'Delivery has not been acknowledged yet, so the invoice cannot be accepted.';
  }
  const invalid = new Set(snap.invalidFields ?? []);
  const resolved = new Set([
    ...input.confirmedFields.filter((f) => !invalid.has(f)),
    ...input.corrections.map((c) => c.field),
  ]);
  const open = snap.heldFields.filter((f) => !resolved.has(f));
  if (open.length)
    return `Confirm or correct ${open.length === 1 ? 'the held field' : `all ${open.length} held fields`} before accepting.`;
  const supplierFails = snap.failedChecks.filter((c) => SUPPLIER_FAULT_CHECKS.includes(c));
  if (supplierFails.length && input.note.length < OVERRIDE_NOTE_MIN) {
    return 'A correctly rendered check failed. Record why it is acceptable before accepting.';
  }
  return null;
}

/** Plain-language notice to the supplier, built from the failed criteria. */
export const RETURN_REASONS: Record<string, string> = {
  addressed_to_buyer:
    'The invoice is not addressed to the Nation Building Authority. Please reissue it to the correct entity.',
  tax_invoice_label: 'The document is not identified as a tax invoice. Please reissue it as a valid tax invoice.',
  supplier_abn_valid: 'The ABN on the invoice is missing or not valid. Please reissue it with your correct ABN.',
  supplier_abn_matches_vendor:
    'The ABN on the invoice does not match the ABN we hold for your business. Please confirm and reissue.',
  recipient_identity: "For invoices of $1,000 or more the recipient's identity or ABN must be shown. Please reissue.",
  po_quoted: 'The invoice does not quote a purchase order number. Please reissue it quoting the purchase order.',
  po_matches:
    'The purchase order quoted does not match an open order with your business. Please check the order number and reissue.',
  gst_calculated:
    'The GST or total on the invoice is not correctly calculated. Please correct the amounts and reissue.',
  within_po_value:
    'The invoice exceeds the value remaining on the purchase order. Please contact your contract manager before reissuing.',
  not_duplicate:
    'An invoice with this number has already been received. If this is a new invoice, please reissue it with a unique number.',
};

export function returnNotice(
  supplier: string | null,
  invoiceNumber: string | null,
  codes: string[],
  note: string
): string {
  const lines = codes.filter((c) => c !== 'other' && RETURN_REASONS[c]).map((c) => `- ${RETURN_REASONS[c]}`);
  if (note.trim()) lines.push(`- ${note.trim()}`);
  return [
    `Dear ${supplier ?? 'supplier'},`,
    '',
    `We are returning invoice ${invoiceNumber ?? '(no number)'} because it is not yet a correctly rendered invoice:`,
    ...lines,
    '',
    'The payment term starts once we receive a correctly rendered invoice and delivery has been acknowledged.',
    '',
    'Accounts Payable, Nation Building Authority',
  ].join('\n');
}

export interface DecisionRecord {
  decision_id: string;
  doc_id: string;
  decision: Decision;
  reason_codes: string[];
  note: string | null;
  doc_type: string;
  status_seen: string;
  lowest_confidence_seen: number | null;
  fields_corrected: number;
  fields_confirmed: string[];
  reclassify_to: string | null;
  handling_seconds: number;
  decided_by: string;
  decided_at: string;
}

export interface CorrectionRecord {
  correction_id: string;
  doc_id: string;
  field: string;
  extracted_value: string | null;
  corrected_value: string;
  routing_confidence: number | null;
  corrected_by: string;
  corrected_at: string;
}

export function resolveSchema(env: Record<string, string | undefined>) {
  const catalog = env.DATABRICKS_CATALOG?.trim();
  const schema = env.DATABRICKS_SCHEMA?.trim();
  if (!catalog || !schema) throw new Error('DATABRICKS_CATALOG and DATABRICKS_SCHEMA must be set');
  const ident = /^[A-Za-z0-9_]+$/;
  if (!ident.test(catalog) || !ident.test(schema)) throw new Error('Catalog and schema must be plain identifiers');
  return { catalog, schema };
}
