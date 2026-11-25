-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param geo_level STRING = sa4
-- @param scope STRING = NSW
-- @param service STRING = public_hospital
-- @param threshold INT = 45
-- @param min_count INT = 10
-- Access to the nearest site, per region, for an access threshold in km.
--   beyond threshold  residents whose straight-line distance to the nearest site is >= threshold
--   access class      beyond: the median resident is beyond the threshold
--                     near:   the median resident is at 75-100% of the threshold
--                     within: otherwise
-- Small-count suppression: a count of 1 to (min_count - 1) is returned as NULL with a flag, and a
-- region with fewer than min_count residents is suppressed entirely. min_count = 0 turns it off.
WITH r AS (
  SELECT region_code, region_name, state_abbr, ra_class
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_region')
  WHERE geo_level = :geo_level AND (:scope = 'AUS' OR state_abbr = :scope)
),
b AS (
  SELECT b.region_code, b.band_km, b.persons, b.persons_65_plus, b.households_no_vehicle, b.households
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_access_band') b
  JOIN r ON r.region_code = b.region_code
  WHERE b.geo_level = :geo_level AND b.service_type = :service
),
cum AS (
  SELECT region_code, band_km,
         sum(persons) OVER (PARTITION BY region_code ORDER BY band_km) AS cum,
         sum(persons) OVER (PARTITION BY region_code) AS tot
  FROM b
),
pct AS (
  SELECT region_code, min(CASE WHEN cum >= 0.5 * tot THEN band_km END) AS median_band,
         min(CASE WHEN cum >= 0.9 * tot THEN band_km END) AS p90_band
  FROM cum GROUP BY region_code
),
agg AS (
  SELECT region_code, sum(persons) AS persons, sum(households) AS households,
         sum(persons_65_plus) AS persons_65_plus,
         sum(CASE WHEN band_km >= :threshold THEN persons ELSE 0 END) AS beyond,
         sum(CASE WHEN band_km >= :threshold THEN persons_65_plus ELSE 0 END) AS beyond_65,
         sum(CASE WHEN band_km >= :threshold THEN households_no_vehicle ELSE 0 END) AS beyond_nv
  FROM b GROUP BY region_code
),
joined AS (
  SELECT r.*, coalesce(a.persons, 0) AS persons, a.households, a.persons_65_plus, a.beyond, a.beyond_65, a.beyond_nv,
         p.median_band, p.p90_band,
         coalesce(a.persons, 0) > 0 AND a.persons < :min_count AS region_suppressed
  FROM r LEFT JOIN agg a ON a.region_code = r.region_code LEFT JOIN pct p ON p.region_code = r.region_code
)
SELECT region_code, region_name, state_abbr, ra_class,
  CASE WHEN region_suppressed THEN NULL ELSE CAST(persons AS DOUBLE) END AS persons,
  CASE WHEN persons = 0 THEN 'no_population'
       WHEN region_suppressed THEN 'suppressed'
       WHEN median_band >= :threshold THEN 'beyond'
       WHEN median_band >= 0.75 * :threshold THEN 'near'
       ELSE 'within' END AS access_class,
  CASE WHEN region_suppressed THEN NULL ELSE CAST(median_band AS DOUBLE) END AS median_km,
  CASE WHEN region_suppressed THEN NULL ELSE CAST(p90_band AS DOUBLE) END AS p90_km,
  CASE WHEN region_suppressed OR (beyond > 0 AND beyond < :min_count) THEN NULL ELSE CAST(coalesce(beyond, 0) AS DOUBLE) END AS persons_beyond,
  NOT region_suppressed AND beyond > 0 AND beyond < :min_count AS beyond_suppressed,
  CASE WHEN region_suppressed OR (beyond > 0 AND beyond < :min_count) OR persons = 0 THEN NULL
       ELSE round(beyond / persons, 4) END AS share_beyond,
  CASE WHEN region_suppressed OR (beyond_65 > 0 AND beyond_65 < :min_count) THEN NULL ELSE CAST(coalesce(beyond_65, 0) AS DOUBLE) END AS persons_65_beyond,
  CASE WHEN region_suppressed OR (beyond_nv > 0 AND beyond_nv < :min_count) THEN NULL ELSE CAST(coalesce(beyond_nv, 0) AS DOUBLE) END AS households_no_vehicle_beyond
FROM joined
ORDER BY coalesce(beyond, 0) DESC, region_name
