-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- Statements, supplier letters and quotes, newest first.
SELECT i.doc_id, i.doc_type, CAST(i.arrival_ts AS STRING) AS arrival_ts, i.sender, i.subject, i.supplier_id, i.supplier_name,
       i.intent, i.intent_label, i.next_action, i.summary, to_json(i.referenced_invoices) AS referenced_invoices,
       to_json(i.linked_doc_ids) AS linked_doc_ids, to_json(i.unmatched_invoices) AS unmatched_invoices,
       i.bank_details_differ, i.balance_due, i.overdue_amount, i.risk_flag, d.in_live_window
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_intake') i
JOIN IDENTIFIER(:catalog || '.' || :schema || '.gold_documents') d ON d.doc_id = i.doc_id
ORDER BY i.arrival_ts DESC, i.doc_id DESC
