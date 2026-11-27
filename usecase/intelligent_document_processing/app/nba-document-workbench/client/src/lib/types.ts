import type { Status } from '../../../shared/contracts';

export interface QueueRow {
  doc_id: string;
  doc_type: string;
  status: Status;
  status_label: string;
  supplier_name: string | null;
  invoice_number: string | null;
  po_number: string | null;
  po_number_quoted: string | null;
  total_inc_gst: number | null;
  lowest_required_confidence: number | null;
  held_fields: string;
  failed_checks: string;
  arrival_ts: string;
  arrival_date: string;
  channel: string;
  receipt_date: string | null;
  trigger_date: string | null;
  pay_by_date: string | null;
  pay_by_2027_date: string | null;
  term_label: string | null;
  clock_regime: string | null;
  calendar_days_left: number | null;
  business_days_left: number | null;
  business_days_left_2027: number | null;
  clock_state: 'overdue' | 'due_soon' | 'on_track' | 'not_started';
  interest_accrued: number | null;
  contract_manager: string | null;
}

export interface InvoiceRow extends Omit<QueueRow, 'arrival_ts' | 'held_fields' | 'failed_checks'> {
  held_fields: string;
  failed_checks: string;
  return_reasons: string;
  supplier_id: string | null;
  invoice_date: string | null;
  contract_id: string | null;
  po_value_inc_gst: number | null;
  po_billed_before_inc_gst: number | null;
  subtotal_ex_gst: number | null;
  gst_amount: number | null;
  receipt_id: string | null;
  duplicate_of: string | null;
  einvoice: boolean;
  contract_description: string | null;
  contract_category: string | null;
  contract_value_inc_gst: number | null;
  queue_state: 'open' | 'decided';
  decision: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_source: string | null;
  vendor_abn: string | null;
  vendor_gst_registered: boolean | null;
}

export interface DocumentRow {
  doc_id: string;
  arrival_ts: string;
  channel: string;
  sender: string;
  subject: string;
  attachment_name: string;
  batch_id: string;
  doc_type: string | null;
  doc_type_label: string | null;
  status: Status;
  status_label: string;
  page_count: number | null;
  page_images: string;
  parse_error: string | null;
  parsed_at: string | null;
}

export interface FieldRow {
  field: string;
  label: string;
  display_order: number;
  required: boolean;
  value: string | null;
  model_confidence: number | null;
  routing_confidence: number;
  grounded: boolean;
  type_valid: boolean;
  in_cited_region: boolean;
  below_threshold: boolean;
  regions_json: string;
  cited_text: string | null;
  field_type: string;
}

export interface CheckRow {
  check_code: string;
  display_order: number;
  label: string;
  criterion: string;
  source: string;
  source_url: string | null;
  supplier_fault: boolean;
  result: 'pass' | 'fail' | 'unknown';
  detail: string;
}

export interface IntakeRow {
  doc_id: string;
  doc_type: string;
  arrival_ts: string;
  sender: string;
  subject: string;
  supplier_id: string | null;
  supplier_name: string | null;
  intent: string | null;
  intent_label: string | null;
  next_action: string | null;
  summary: string | null;
  referenced_invoices: string;
  linked_doc_ids: string;
  unmatched_invoices: string;
  bank_details_differ: boolean | null;
  balance_due: number | null;
  overdue_amount: number | null;
  risk_flag: string | null;
  in_live_window: boolean;
}

export interface RegisterRow {
  doc_id: string;
  arrival_ts: string;
  channel: string;
  sender: string;
  subject: string;
  attachment_name: string;
  doc_type: string | null;
  doc_type_label: string | null;
  status: Status;
  status_label: string;
  page_count: number | null;
  parse_error: string | null;
  in_live_window: boolean;
  supplier_name: string | null;
  invoice_number: string | null;
  total_inc_gst: number | null;
  queue_state: string | null;
  decision: string | null;
  decision_source: string | null;
  vendor_abn: string | null;
  vendor_gst_registered: boolean | null;
}

export interface PipelineStatus {
  documents_landed: number;
  documents_parsed: number;
  parse_errors: number;
  documents_classified: number;
  invoices_extracted: number;
  invoices_assessed: number;
  open_invoices: number;
  straight_through_pct: number | null;
  classification_accuracy_pct: number | null;
  last_arrival_ts: string;
  last_parsed_at: string;
  assessed_at: string;
  as_of: string;
  contracts_source: string;
  contracts_fetched_at: string;
  gic_rate: number;
  gic_quarter: string;
  review_threshold: number;
  arrival_batches: number;
}

export interface Region {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}
