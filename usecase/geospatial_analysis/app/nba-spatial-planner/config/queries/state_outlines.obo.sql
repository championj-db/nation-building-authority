-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- State and territory outlines, drawn under every geography for context. Served as Arrow.
SELECT region_code, state_abbr, geom_national AS geom, xmin, xmax, ymin, ymax
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_region')
WHERE geo_level = 'state'
