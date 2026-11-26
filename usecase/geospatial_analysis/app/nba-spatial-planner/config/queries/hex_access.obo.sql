-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param scope STRING = NSW
-- @param service STRING = public_hospital
-- @param threshold INT = 45
-- @param min_count INT = 10
-- @param hex_res INT = 6
-- The H3 view: residents per hexagon, classed the same way as regions. Hexagons with fewer than
-- min_count residents are not returned at all (a hexagon is a fine geography). Served as Arrow.
WITH sc AS (
  SELECT region_code AS state_code FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_region')
  WHERE geo_level = 'state' AND state_abbr = :scope
),
c AS (
  SELECT h3_toparent(h3_cell, :hex_res) AS hex, band_km, persons
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_cell_access')
  WHERE service_type = :service AND (:scope = 'AUS' OR state_code IN (SELECT state_code FROM sc))
),
bands AS (SELECT hex, band_km, sum(persons) AS persons FROM c GROUP BY hex, band_km),
cum AS (
  SELECT hex, band_km, persons,
         sum(persons) OVER (PARTITION BY hex ORDER BY band_km) AS cum,
         sum(persons) OVER (PARTITION BY hex) AS tot
  FROM bands
),
h AS (
  SELECT hex, max(tot) AS persons, min(CASE WHEN cum >= 0.5 * tot THEN band_km END) AS median_band,
         sum(CASE WHEN band_km >= :threshold THEN persons ELSE 0 END) AS beyond
  FROM cum GROUP BY hex
)
SELECT h3_h3tostring(hex) AS hex_id,
       regexp_replace(get_json_object(h3_boundaryasgeojson(hex), '$.coordinates[0]'), '(\\.[0-9]{3})[0-9]+', '$1') AS ring,
       CAST(persons AS DOUBLE) AS persons,
       CASE WHEN beyond > 0 AND beyond < :min_count THEN NULL ELSE CAST(beyond AS DOUBLE) END AS persons_beyond,
       CAST(median_band AS DOUBLE) AS median_km,
       CASE WHEN median_band >= :threshold THEN 'beyond' WHEN median_band >= 0.75 * :threshold THEN 'near' ELSE 'within' END AS access_class
FROM h
WHERE persons >= greatest(:min_count, 1)
