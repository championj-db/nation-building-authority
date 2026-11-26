-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- What each pipeline step produced on the latest run.
SELECT step_order, step, metric, CAST(value AS DOUBLE) AS value, detail
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_pipeline_metric')
ORDER BY step_order, metric
