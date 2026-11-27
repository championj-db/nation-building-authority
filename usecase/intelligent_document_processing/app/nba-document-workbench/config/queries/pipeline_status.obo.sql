-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- One row: volumes at each pipeline stage, straight-through rate and provenance.
SELECT * FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_pipeline_status')
