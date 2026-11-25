-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- Service types the planner can analyse, their public sources and default access thresholds.
-- (Sample catalog/schema values above are used only by `appkit generate-types`; at runtime the
-- client binds the governed schema the server reads from app config.)
SELECT service_type, label, description, default_threshold_km, publisher, source_url, attribution,
       sort_order, sites, fetched_at, from_cache
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_service_catalog')
ORDER BY sort_order
