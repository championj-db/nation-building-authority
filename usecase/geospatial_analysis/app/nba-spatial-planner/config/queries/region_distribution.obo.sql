-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param geo_level STRING = sa4
-- @param region_code STRING = 105
-- @param service STRING = public_hospital
-- @param min_count INT = 10
-- How far residents of one region live from the nearest site, in 10 km buckets (150 = 150 km or
-- more). Buckets with a small count are suppressed.
WITH b AS (
  SELECT least(floor(band_km / 10) * 10, 150) AS bucket_km, sum(persons) AS persons
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_access_band')
  WHERE geo_level = :geo_level AND region_code = :region_code AND service_type = :service
  GROUP BY 1
)
SELECT CAST(bucket_km AS INT) AS bucket_km,
       CASE WHEN persons < :min_count THEN NULL ELSE CAST(persons AS DOUBLE) END AS persons,
       persons < :min_count AS suppressed
FROM b ORDER BY bucket_km
