-- @param catalog STRING = main
-- @param schema STRING = intelligent_document_processing
-- Injected defects and whether the correctly rendered checks caught them.
SELECT defect, documents, caught, false_alarms, to_exception, to_review, to_ready
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_check_detection')
ORDER BY documents DESC
