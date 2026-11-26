-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param scope STRING = NSW
-- @param service STRING = public_hospital
-- @param min_count INT = 10
-- Sites of one service type in scope, with their modelled catchment (residents for whom the site
-- is the nearest of its type). Site locations are public; catchments are suppressed when small.
SELECT s.site_id, s.name, s.address, s.suburb, r.state_abbr, s.longitude, s.latitude, s.capacity_places,
       CASE WHEN s.catchment_persons > 0 AND s.catchment_persons < :min_count THEN NULL
            ELSE CAST(s.catchment_persons AS DOUBLE) END AS catchment_persons,
       s.catchment_median_km, s.catchment_p90_km
FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_service_site') s
LEFT JOIN IDENTIFIER(:catalog || '.' || :schema || '.gold_region') r
  ON r.geo_level = 'state' AND r.region_code = s.state_code
WHERE s.service_type = :service AND (:scope = 'AUS' OR r.state_abbr = :scope)
ORDER BY s.name
