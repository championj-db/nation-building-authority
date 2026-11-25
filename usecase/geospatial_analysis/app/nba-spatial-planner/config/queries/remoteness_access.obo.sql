-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param scope STRING = NSW
-- @param service STRING = public_hospital
-- @param threshold INT = 45
-- @param min_count INT = 10
-- Residents beyond the threshold by ABS remoteness class, within the scope.
WITH b AS (
  SELECT r.ra_class, b.band_km, b.persons
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_access_band') b
  JOIN IDENTIFIER(:catalog || '.' || :schema || '.gold_region') r
    ON r.geo_level = 'ra' AND r.region_code = b.region_code
  WHERE b.geo_level = 'ra' AND b.service_type = :service AND (:scope = 'AUS' OR r.state_abbr = :scope)
),
a AS (
  SELECT ra_class, sum(persons) AS persons, sum(CASE WHEN band_km >= :threshold THEN persons ELSE 0 END) AS beyond
  FROM b GROUP BY ra_class
)
SELECT ra_class,
       CASE ra_class WHEN '0' THEN 'Major Cities' WHEN '1' THEN 'Inner Regional' WHEN '2' THEN 'Outer Regional'
                     WHEN '3' THEN 'Remote' WHEN '4' THEN 'Very Remote' END AS ra_label,
       CASE WHEN persons < :min_count THEN NULL ELSE CAST(persons AS DOUBLE) END AS persons,
       CASE WHEN persons < :min_count OR (beyond > 0 AND beyond < :min_count) THEN NULL ELSE CAST(beyond AS DOUBLE) END AS persons_beyond,
       CASE WHEN persons < :min_count OR (beyond > 0 AND beyond < :min_count) THEN NULL ELSE round(beyond / persons, 4) END AS share_beyond
FROM a ORDER BY ra_class
