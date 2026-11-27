-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- @param doc_id STRING = DOC-000001
SELECT field, label, display_order, required, value, model_confidence, routing_confidence, grounded, type_valid, in_cited_region,
       below_threshold, regions_json, cited_text, field_type
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_extracted_fields')
WHERE doc_id = :doc_id
ORDER BY display_order
