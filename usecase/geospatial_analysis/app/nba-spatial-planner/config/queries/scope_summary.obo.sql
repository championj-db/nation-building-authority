-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param scope STRING = NSW
-- @param service STRING = public_hospital
-- @param threshold INT = 45
-- @param min_count INT = 10
-- Headline figures for the whole scope (one state, or 'AUS'), from the state-level bands.
WITH b AS (
  SELECT b.band_km, b.persons, b.persons_65_plus, b.households, b.households_no_vehicle
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_access_band') b
  JOIN IDENTIFIER(:catalog || '.' || :schema || '.gold_region') r
    ON r.geo_level = 'state' AND r.region_code = b.region_code
  WHERE b.geo_level = 'state' AND b.service_type = :service AND (:scope = 'AUS' OR r.state_abbr = :scope)
),
bands AS (
  SELECT band_km, sum(persons) AS persons FROM b GROUP BY band_km
),
cum AS (
  SELECT band_km, sum(persons) OVER (ORDER BY band_km) AS cum, sum(persons) OVER () AS tot FROM bands
),
t AS (
  SELECT sum(persons) AS persons, sum(households) AS households, sum(persons_65_plus) AS persons_65_plus,
         sum(households_no_vehicle) AS households_no_vehicle,
         sum(CASE WHEN band_km >= :threshold THEN persons ELSE 0 END) AS beyond,
         sum(CASE WHEN band_km >= :threshold THEN persons_65_plus ELSE 0 END) AS beyond_65,
         sum(CASE WHEN band_km >= :threshold THEN households_no_vehicle ELSE 0 END) AS beyond_nv
  FROM b
)
SELECT CAST(t.persons AS DOUBLE) AS persons, CAST(t.households AS DOUBLE) AS households,
       CAST(t.persons_65_plus AS DOUBLE) AS persons_65_plus, CAST(t.households_no_vehicle AS DOUBLE) AS households_no_vehicle,
       CASE WHEN t.beyond > 0 AND t.beyond < :min_count THEN NULL ELSE CAST(t.beyond AS DOUBLE) END AS persons_beyond,
       CASE WHEN t.beyond_65 > 0 AND t.beyond_65 < :min_count THEN NULL ELSE CAST(t.beyond_65 AS DOUBLE) END AS persons_65_beyond,
       CASE WHEN t.beyond_nv > 0 AND t.beyond_nv < :min_count THEN NULL ELSE CAST(t.beyond_nv AS DOUBLE) END AS households_no_vehicle_beyond,
       CAST((SELECT min(band_km) FROM cum WHERE cum >= 0.5 * tot) AS DOUBLE) AS median_km,
       CAST((SELECT min(band_km) FROM cum WHERE cum >= 0.9 * tot) AS DOUBLE) AS p90_km
FROM t
