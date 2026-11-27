-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- Every document in the inbox, newest first, with its invoice outcome where it has one.
SELECT d.doc_id, CAST(d.arrival_ts AS STRING) AS arrival_ts, d.channel, d.sender, d.subject, d.attachment_name, d.doc_type,
       d.doc_type_label, d.status, d.status_label, d.page_count, d.parse_error, d.in_live_window, a.supplier_name,
       a.invoice_number, a.total_inc_gst, a.queue_state, a.decision, a.decision_source
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_documents') d
LEFT JOIN IDENTIFIER(:catalog || '.' || :schema || '.gold_invoice_assessment') a ON a.doc_id = d.doc_id
ORDER BY d.arrival_ts DESC, d.doc_id DESC
