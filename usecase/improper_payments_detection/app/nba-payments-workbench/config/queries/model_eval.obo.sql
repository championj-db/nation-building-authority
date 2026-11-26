-- @param catalog STRING = main
-- @param schema STRING = improper_payments_detection
SELECT metric, value, model_version
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_model_eval')
ORDER BY metric
