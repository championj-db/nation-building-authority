-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- Extraction measured on the synthetic corpus, per field: born-digital and scanned together and apart.
SELECT field, label, scanned, fields, matches_truth, routed_to_review, mean_routing_confidence, reviewed,
       corrected_by_reviewer, wrong_but_not_routed, accuracy_pct
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_extraction_accuracy')
ORDER BY field, scanned
