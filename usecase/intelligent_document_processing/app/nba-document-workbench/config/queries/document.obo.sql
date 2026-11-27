-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- @param doc_id STRING = DOC-000001
SELECT doc_id, CAST(arrival_ts AS STRING) AS arrival_ts, channel, sender, subject, attachment_name, batch_id,
       doc_type, doc_type_label, status, status_label, page_count, to_json(page_images) AS page_images, parse_error,
       CAST(parsed_at AS STRING) AS parsed_at
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_documents')
WHERE doc_id = :doc_id
