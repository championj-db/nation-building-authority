-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- @param doc_id STRING = DOC-000001
SELECT a.doc_id, a.doc_type, a.status, a.status_label, a.lowest_required_confidence,
       to_json(a.fields_below_threshold) AS held_fields, to_json(a.failed_checks) AS failed_checks,
       to_json(a.return_reasons) AS return_reasons, a.supplier_id, a.supplier_name, a.invoice_number,
       CAST(a.invoice_date AS STRING) AS invoice_date, a.po_number_quoted, a.po_number, a.contract_id,
       a.po_value_inc_gst, a.po_billed_before_inc_gst, a.subtotal_ex_gst, a.gst_amount, a.total_inc_gst, a.receipt_id,
       CAST(a.receipt_date AS STRING) AS receipt_date, a.duplicate_of, a.einvoice, CAST(a.trigger_date AS STRING) AS trigger_date,
       a.clock_regime, a.term_label, CAST(a.pay_by_date AS STRING) AS pay_by_date, CAST(a.pay_by_2027_date AS STRING) AS pay_by_2027_date,
       CAST(a.arrival_date AS STRING) AS arrival_date, a.channel, a.contract_description, a.contract_category, a.contract_manager,
       a.contract_value_inc_gst, a.queue_state, a.decision, a.decided_by, CAST(a.decided_at AS STRING) AS decided_at, a.decision_source,
       q.calendar_days_left, q.business_days_left, q.business_days_left_2027, q.clock_state, q.interest_accrued,
       s.abn AS vendor_abn, s.gst_registered AS vendor_gst_registered
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_invoice_assessment') a
LEFT JOIN IDENTIFIER(:catalog || '.' || :schema || '.ref_suppliers') s ON s.supplier_id = a.supplier_id
LEFT JOIN IDENTIFIER(:catalog || '.' || :schema || '.gold_open_queue') q ON q.doc_id = a.doc_id
WHERE a.doc_id = :doc_id
