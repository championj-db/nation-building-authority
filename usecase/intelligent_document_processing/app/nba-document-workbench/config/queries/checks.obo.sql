-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- @param doc_id STRING = DOC-000001
SELECT check_code, display_order, label, criterion, source, source_url, supplier_fault, result, detail
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_invoice_checks')
WHERE doc_id = :doc_id
ORDER BY display_order
