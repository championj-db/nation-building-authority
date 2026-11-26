-- @param catalog STRING = main
-- @param schema STRING = improper_payments_detection
-- When the queue was last scored, by which model version, over how many records.
SELECT CAST(scored_ts AS STRING) AS scored_ts, model_name, model_version, source_records, entities_resolved,
       payments_scored, cases_open
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_pipeline_summary')
