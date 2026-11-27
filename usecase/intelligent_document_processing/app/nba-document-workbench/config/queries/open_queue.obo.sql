-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- Open invoices and adjustment notes, with days left on the RMG 417 clock computed at query time.
-- Decisions recorded in the workbench are overlaid by the app from Lakebase.
SELECT doc_id, doc_type, status, status_label, supplier_name, invoice_number, po_number, po_number_quoted,
       total_inc_gst, lowest_required_confidence,
       to_json(fields_below_threshold) AS held_fields, to_json(failed_checks) AS failed_checks,
       CAST(arrival_ts AS STRING) AS arrival_ts, CAST(arrival_date AS STRING) AS arrival_date, channel,
       CAST(receipt_date AS STRING) AS receipt_date, CAST(trigger_date AS STRING) AS trigger_date,
       CAST(pay_by_date AS STRING) AS pay_by_date, CAST(pay_by_2027_date AS STRING) AS pay_by_2027_date,
       term_label, clock_regime, calendar_days_left, business_days_left, business_days_left_2027, clock_state,
       interest_accrued, contract_manager
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_open_queue')
ORDER BY CASE clock_state WHEN 'overdue' THEN 0 WHEN 'due_soon' THEN 1 WHEN 'on_track' THEN 2 ELSE 3 END,
         business_days_left, arrival_ts, doc_id
