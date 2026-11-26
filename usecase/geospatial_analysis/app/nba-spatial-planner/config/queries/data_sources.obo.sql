-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- Provenance of every public input: publisher, licence, feature count, and whether the latest
-- fetch fell back to the cached copy.
SELECT dataset, step, publisher, source_url, attribution, licence, CAST(features AS DOUBLE) AS features,
       from_cache, fetch_error, fetched_at
FROM IDENTIFIER(:catalog || '.' || :schema || '.ref_source')
ORDER BY step, dataset
