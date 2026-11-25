-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param geo_level STRING = sa4
-- @param scope STRING = NSW
-- Map-ready region polygons for one geography, either for one state ('NSW', 'VIC', ...) or the
-- whole country ('AUS', which uses the more generalised national geometry). Served as Arrow.
SELECT region_code, region_name, state_abbr, ra_class,
       CASE WHEN :scope = 'AUS' THEN geom_national ELSE geom_state END AS geom,
       label_lon, label_lat, xmin, xmax, ymin, ymax,
       CAST(persons AS DOUBLE) AS persons, area_sqkm
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_region')
WHERE geo_level = :geo_level AND (:scope = 'AUS' OR state_abbr = :scope)
