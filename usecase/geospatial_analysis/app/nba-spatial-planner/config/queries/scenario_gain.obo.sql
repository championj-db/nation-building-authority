-- @param catalog STRING = au_pubsec_catalog
-- @param schema STRING = geospatial_analysis_jared_champion
-- @param scope STRING = NSW
-- @param service STRING = public_hospital
-- @param threshold INT = 45
-- @param min_count INT = 10
-- @param geo_level STRING = sa4
-- @param sites STRING = [{"lon":149.1,"lat":-31.5}]
-- New-site scenario: residents currently beyond the threshold who would be within it if sites
-- were added at the proposed points (a JSON array of {lon, lat}, at most five). Estimated per H3
-- cell from the cell centre (about 0.7 km2), straight-line. Returns one row per region that gains
-- and one total row (region_code IS NULL).
WITH s AS (
  SELECT site.lon, site.lat
  FROM (SELECT explode(slice(from_json(:sites, 'array<struct<lon:double,lat:double>>'), 1, 5)) AS site)
),
sc AS (
  SELECT region_code AS state_code FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_region')
  WHERE geo_level = 'state' AND state_abbr = :scope
),
cells AS (
  SELECT h3_cell, cell_lon, cell_lat, persons, persons_65_plus, households_no_vehicle,
         CASE :geo_level WHEN 'sa4' THEN sa4_code WHEN 'sa3' THEN sa3_code WHEN 'sa2' THEN sa2_code
                         WHEN 'lga' THEN lga_code WHEN 'ra' THEN ra_code ELSE state_code END AS region_code
  FROM IDENTIFIER(:catalog || '.' || :schema || '.gold_cell_access')
  WHERE service_type = :service AND band_km >= :threshold
    AND (:scope = 'AUS' OR state_code IN (SELECT state_code FROM sc))
),
reach AS (
  SELECT c.h3_cell, c.region_code, c.persons, c.persons_65_plus, c.households_no_vehicle,
         min(2 * 6371.0088 * asin(least(1.0, sqrt(
           pow(sin(radians(s.lat - c.cell_lat) / 2), 2) +
           cos(radians(c.cell_lat)) * cos(radians(s.lat)) * pow(sin(radians(s.lon - c.cell_lon) / 2), 2))))) AS new_km
  FROM cells c CROSS JOIN s
  GROUP BY c.h3_cell, c.region_code, c.persons, c.persons_65_plus, c.households_no_vehicle
),
g AS (
  SELECT region_code, sum(persons) AS gained, sum(persons_65_plus) AS gained_65, sum(households_no_vehicle) AS gained_nv
  FROM reach WHERE new_km < :threshold
  GROUP BY GROUPING SETS ((region_code), ())
)
SELECT g.region_code, r.region_name,
       CASE WHEN g.gained < :min_count THEN NULL ELSE CAST(g.gained AS DOUBLE) END AS persons_gained,
       CASE WHEN g.gained_65 > 0 AND g.gained_65 < :min_count THEN NULL ELSE CAST(g.gained_65 AS DOUBLE) END AS persons_65_gained,
       CASE WHEN g.gained_nv > 0 AND g.gained_nv < :min_count THEN NULL ELSE CAST(g.gained_nv AS DOUBLE) END AS households_no_vehicle_gained
FROM g
LEFT JOIN IDENTIFIER(:catalog || '.' || :schema || '.gold_region') r
  ON r.geo_level = :geo_level AND r.region_code = g.region_code
ORDER BY g.region_code IS NULL DESC, g.gained DESC
