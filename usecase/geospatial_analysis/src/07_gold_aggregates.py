# Databricks notebook source
# Step 7 of the geospatial analysis pipeline: spatial aggregation and map-ready serving (gold).
#
# Household-level results never leave silver. What the app reads is aggregated:
#
#   gold_region          every region at every geography, with display geometry simplified for
#                        the map (state view and national view) and modelled population
#   gold_access_band     persons per region x service x 1 km distance band. Any access threshold
#                        becomes a cheap SUM over bands, so the planner's slider needs no re-run
#   gold_cell_access     the same bands per H3 cell, for the hex map layer and for testing a
#                        proposed new site (who would move within the threshold)
#   gold_service_site    sites with their catchment (people for whom the site is the nearest)
#   gold_service_catalog the service types, their sources and default thresholds
#   gold_pipeline_metric what each step produced, for the app's pipeline view
#
# Small-count suppression is applied when the app queries these tables (the disclosure threshold
# is a setting the officer can see), not baked in here, so suppression is always visible to the
# person relying on the numbers.

# COMMAND ----------

import json
import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import DISTANCE_BAND_CAP_KM, GEO_LEVELS, REMOTENESS, SERVICE_TYPES, STATES, fq, get_params  # noqa: E402

params = get_params({"catalog": "", "schema": "", "h3_resolution": "8"}, dbutils)
CATALOG, SCHEMA = params["catalog"], params["schema"]
H3_RES = int(params["h3_resolution"])
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731

# COMMAND ----------

# MAGIC %md
# MAGIC ## Regions with map-ready geometry
# MAGIC Geometry is simplified twice (ST_Simplify) - `geom_state` for a state-scoped map and
# MAGIC `geom_national` for the national view - rounded to 3 decimal places (~100 m) and encoded as a
# MAGIC compact list of rings (`[[[lon, lat], ...], ...]`), drawn even-odd so holes render correctly.

# COMMAND ----------

# level: (tolerance for the state view, tolerance for the national view) in degrees
TOLERANCE = {"state": (0.004, 0.02), "sa4": (0.003, 0.015), "sa3": (0.002, 0.012),
             "sa2": (0.0012, 0.01), "lga": (0.002, 0.012), "ra": (0.003, 0.015)}
tol_state = " ".join(f"WHEN '{k}' THEN {v[0]}" for k, v in TOLERANCE.items())
tol_nat = " ".join(f"WHEN '{k}' THEN {v[1]}" for k, v in TOLERANCE.items())
state_abbr = " ".join(f"WHEN '{c}' THEN '{a}'" for c, (a, _n) in STATES.items())
ra_label = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in REMOTENESS.items())


def rings_sql(geom: str) -> str:
    """GeoJSON (Multi)Polygon -> rounded JSON list of rings."""
    js = f"regexp_replace(ST_AsGeoJSON({geom}), '(\\\\.[0-9]{{3}})[0-9]+', '$1')"
    return f"""CASE
      WHEN {geom} IS NULL OR ST_IsEmpty({geom}) THEN NULL
      WHEN ST_GeometryType({geom}) ILIKE '%multi%' THEN
        to_json(flatten(from_json(get_json_object({js}, '$.coordinates'), 'array<array<array<array<double>>>>')))
      ELSE to_json(from_json(get_json_object({js}, '$.coordinates'), 'array<array<array<double>>>'))
    END"""


spark.sql(f"""
CREATE OR REPLACE TEMP VIEW region_geom AS
WITH src AS (
  SELECT level, code, name, state_code, area_sqkm, ST_GeomFromWKB(geom_wkb, 4326) AS geom
  FROM {t('silver_boundary')}
  WHERE kind = 'display' AND level IN ({', '.join(f"'{k}'" for k in GEO_LEVELS)})
),
simplified AS (
  SELECT *,
    ST_Simplify(geom, CASE level {tol_state} END) AS g_state,
    ST_Simplify(geom, CASE level {tol_nat} END) AS g_nat
  FROM src
)
SELECT level, code, name, state_code, area_sqkm,
  coalesce({rings_sql('g_state')}, {rings_sql('geom')}) AS geom_state,
  coalesce({rings_sql('g_nat')}, {rings_sql('g_state')}, {rings_sql('geom')}) AS geom_national,
  ST_X(ST_PointOnSurface(geom)) AS label_lon, ST_Y(ST_PointOnSurface(geom)) AS label_lat,
  ST_XMin(geom) AS xmin, ST_XMax(geom) AS xmax, ST_YMin(geom) AS ymin, ST_YMax(geom) AS ymax
FROM simplified
""")

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW household_regions AS
SELECT h.*, region.geo_level, region.region_code
FROM {t('silver_household_located')} h
LATERAL VIEW stack(6,
  'state', h.state_code, 'sa4', h.sa4_code, 'sa3', h.sa3_code, 'sa2', h.sa2_code,
  'lga', h.lga_code, 'ra', h.ra_code) region AS geo_level, region_code
WHERE region.region_code IS NOT NULL
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {t('gold_region')}
COMMENT 'Regions at every analysis geography with map-ready geometry and modelled (synthetic) population'
CLUSTER BY (geo_level, state_code)
AS
WITH pop AS (
  SELECT geo_level, region_code, count(*) AS households, sum(household_size) AS persons,
         sum(persons_65_plus) AS persons_65_plus, count_if(no_vehicle) AS households_no_vehicle
  FROM household_regions GROUP BY geo_level, region_code
),
erp AS (
  SELECT s.sa2_code, s.sa3_code, s.sa4_code, s.state_code, p.erp_persons
  FROM (SELECT DISTINCT sa2_code, sa3_code, sa4_code, state_code FROM {t('silver_sa1')}) s
  JOIN {t('silver_population_sa2')} p ON p.sa2_code = s.sa2_code
),
erp_levels AS (
  SELECT 'sa2' AS geo_level, sa2_code AS region_code, sum(erp_persons) AS erp_persons FROM erp GROUP BY 2
  UNION ALL SELECT 'sa3', sa3_code, sum(erp_persons) FROM erp GROUP BY 2
  UNION ALL SELECT 'sa4', sa4_code, sum(erp_persons) FROM erp GROUP BY 2
  UNION ALL SELECT 'state', state_code, sum(erp_persons) FROM erp GROUP BY 2
)
SELECT
  g.level AS geo_level, g.code AS region_code,
  CASE WHEN g.level = 'ra'
       THEN concat(CASE right(g.code, 1) {ra_label} ELSE g.name END, ' (', CASE g.state_code {state_abbr} END, ')')
       ELSE g.name END AS region_name,
  g.state_code, CASE g.state_code {state_abbr} END AS state_abbr,
  CASE WHEN g.level = 'ra' THEN right(g.code, 1) END AS ra_class,
  round(g.area_sqkm, 1) AS area_sqkm,
  coalesce(p.households, 0) AS households, coalesce(p.persons, 0) AS persons,
  coalesce(p.persons_65_plus, 0) AS persons_65_plus, coalesce(p.households_no_vehicle, 0) AS households_no_vehicle,
  e.erp_persons,
  g.geom_state, g.geom_national,
  round(g.label_lon, 4) AS label_lon, round(g.label_lat, 4) AS label_lat,
  round(g.xmin, 3) AS xmin, round(g.xmax, 3) AS xmax, round(g.ymin, 3) AS ymin, round(g.ymax, 3) AS ymax
FROM region_geom g
LEFT JOIN pop p ON p.geo_level = g.level AND p.region_code = g.code
LEFT JOIN erp_levels e ON e.geo_level = g.level AND e.region_code = g.code
-- ABS non-spatial codes (migratory, no usual address, outside Australia) have no geometry; RA
-- class 5 (migratory) likewise
WHERE g.geom_state IS NOT NULL AND NOT (g.level = 'ra' AND right(g.code, 1) NOT IN ('0', '1', '2', '3', '4'))
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Distance bands per region and per H3 cell

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW household_band AS
SELECT h.household_id, h.household_size, h.persons_65_plus, h.no_vehicle, h.state_code, h.h3_cell,
       h.geo_level, h.region_code, a.service_type,
       CAST(least(floor(a.distance_km), {DISTANCE_BAND_CAP_KM}) AS INT) AS band_km
FROM household_regions h JOIN {t('silver_household_access')} a ON a.household_id = h.household_id
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {t('gold_access_band')}
COMMENT 'Persons by region, service and 1 km straight-line distance band (band {DISTANCE_BAND_CAP_KM} = {DISTANCE_BAND_CAP_KM} km or more). Beyond a threshold T means band_km >= T. SYNTHETIC households; suppress small counts when serving.'
CLUSTER BY (geo_level, service_type, state_code)
AS
SELECT b.geo_level, b.region_code, r.state_code, b.service_type, b.band_km,
       count(*) AS households, sum(b.household_size) AS persons, sum(b.persons_65_plus) AS persons_65_plus,
       count_if(b.no_vehicle) AS households_no_vehicle
FROM household_band b JOIN {t('gold_region')} r ON r.geo_level = b.geo_level AND r.region_code = b.region_code
GROUP BY ALL
""")

spark.sql(f"""
CREATE OR REPLACE TABLE {t('gold_cell_access')}
COMMENT 'Persons by H3 res {H3_RES} cell, region, service and 1 km distance band - the hex map layer and new-site scenarios. A cell straddling a boundary has one row per region. SYNTHETIC; suppress small counts when serving.'
CLUSTER BY (state_code, service_type)
AS
SELECT h.h3_cell, h.state_code, h.sa4_code, h.sa3_code, h.sa2_code, h.lga_code, h.ra_code, a.service_type,
       CAST(least(floor(a.distance_km), {DISTANCE_BAND_CAP_KM}) AS INT) AS band_km,
       count(*) AS households, sum(h.household_size) AS persons, sum(h.persons_65_plus) AS persons_65_plus,
       count_if(h.no_vehicle) AS households_no_vehicle,
       round(ST_X(ST_GeomFromGeoJSON(h3_centerasgeojson(h.h3_cell))), 5) AS cell_lon,
       round(ST_Y(ST_GeomFromGeoJSON(h3_centerasgeojson(h.h3_cell))), 5) AS cell_lat
FROM {t('silver_household_located')} h JOIN {t('silver_household_access')} a ON a.household_id = h.household_id
GROUP BY ALL
""")


# COMMAND ----------

# MAGIC %md
# MAGIC ## Sites, catchments and the service catalogue

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {t('gold_service_site')}
COMMENT 'Essential-service sites (public data) with their modelled catchment: people for whom the site is the nearest of its type'
AS
WITH c AS (
  SELECT a.nearest_site_id AS site_id, count(*) AS catchment_households, sum(h.household_size) AS catchment_persons,
         percentile_approx(a.distance_km, 0.5) AS catchment_median_km, percentile_approx(a.distance_km, 0.9) AS catchment_p90_km
  FROM {t('silver_household_access')} a JOIN {t('silver_household_located')} h ON h.household_id = a.household_id
  GROUP BY 1
)
SELECT s.site_id, s.service_type, s.name, s.address, s.suburb, s.state_code, s.postcode,
       round(s.longitude, 5) AS longitude, round(s.latitude, 5) AS latitude, s.h3_cell, s.capacity_places,
       coalesce(c.catchment_households, 0) AS catchment_households, coalesce(c.catchment_persons, 0) AS catchment_persons,
       round(c.catchment_median_km, 1) AS catchment_median_km, round(c.catchment_p90_km, 1) AS catchment_p90_km
FROM {t('silver_service_site')} s LEFT JOIN c ON c.site_id = s.site_id
""")

catalog_rows = [
    (k, v["label"], v["description"], int(v["default_threshold_km"]), v["publisher"], v["url"], v["attribution"], i)
    for i, (k, v) in enumerate(SERVICE_TYPES.items())
]
spark.createDataFrame(
    catalog_rows,
    "service_type string, label string, description string, default_threshold_km int, publisher string, "
    "source_url string, attribution string, sort_order int",
).createOrReplaceTempView("catalog_rows")
spark.sql(f"""
CREATE OR REPLACE TABLE {t('gold_service_catalog')}
COMMENT 'Service types the planner can analyse, with their public sources'
AS
SELECT c.*, coalesce(s.sites, 0) AS sites, p.fetched_at, p.from_cache
FROM catalog_rows c
LEFT JOIN (SELECT service_type, count(*) AS sites FROM {t('silver_service_site')} GROUP BY 1) s ON s.service_type = c.service_type
LEFT JOIN {t('ref_source')} p ON p.dataset = concat('service_', c.service_type)
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Pipeline metrics for the app

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {t('gold_pipeline_metric')}
COMMENT 'What each pipeline step produced on the latest run, for the planner''s data pipeline view'
AS
WITH b AS (SELECT level, kind, count(*) AS n, sum(n_points) AS v FROM {t('silver_boundary')} GROUP BY ALL),
hh AS (
  SELECT count(*) AS households, sum(household_size) AS persons, count_if(placed_by_fallback) AS fallback
  FROM {t('silver_household')}
),
loc AS (
  SELECT count(*) AS n, count_if(lga_method = 'core_chip') AS core, count_if(lga_method = 'boundary_chip') AS boundary,
         count_if(lga_method = 'sa1_fallback') AS fallback
  FROM {t('silver_household_located')}
),
px AS (SELECT sum(all_pairs) AS all_pairs, sum(evaluated_pairs) AS evaluated FROM {t('silver_proximity_stats')}),
pop AS (SELECT max(erp_year) AS year, sum(erp_persons) AS persons FROM {t('silver_population_sa2')})
SELECT * FROM VALUES (0, 'x', 'x', 0D, 'x') AS v(step_order, step, metric, value, detail) WHERE false
UNION ALL SELECT 1, 'ingest', 'SA1 polygons', (SELECT n FROM b WHERE level = 'sa1'), 'ABS ASGS 2021, placement frame'
UNION ALL SELECT 1, 'ingest', 'Boundary vertices conformed', (SELECT sum(v) FROM b), 'All levels, analysis and display'
UNION ALL SELECT 1, 'ingest', 'Population (ERP)', (SELECT persons FROM pop), concat('ABS estimated resident population, ', (SELECT year FROM pop))
UNION ALL SELECT 1, 'ingest', 'Service sites', (SELECT count(*) FROM {t('silver_service_site')}), 'Four public national layers'
UNION ALL SELECT 2, 'index', 'Synthetic households', (SELECT households FROM hh), 'dbldatagen, placed by ST_Contains rejection sampling'
UNION ALL SELECT 2, 'index', 'Modelled residents', (SELECT persons FROM hh), 'Sum of synthetic household sizes'
UNION ALL SELECT 2, 'index', 'Zone chips (H3)', (SELECT count(*) FROM {t('silver_zone_chip')}), 'LGA (res 6) and Remoteness Area (res 5) tessellation'
UNION ALL SELECT 3, 'analysis', 'Assigned by core chip', (SELECT core / n FROM loc), 'Share of households placed in an LGA with no geometry test'
UNION ALL SELECT 3, 'analysis', 'Assigned by boundary test', (SELECT boundary / n FROM loc), 'Share needing ST_Contains against a chip'
UNION ALL SELECT 3, 'analysis', 'All-pairs distance calculations', (SELECT all_pairs FROM px), 'Households x sites, all four services'
UNION ALL SELECT 3, 'analysis', 'Calculations after H3 pruning', (SELECT evaluated FROM px), 'Exact nearest site, provably'
UNION ALL SELECT 4, 'aggregate', 'Regions', (SELECT count(*) FROM {t('gold_region')}), 'SA2, SA3, SA4, LGA, Remoteness Area and state'
UNION ALL SELECT 4, 'aggregate', 'Distance-band rows', (SELECT count(*) FROM {t('gold_access_band')}), '1 km bands per region and service'
UNION ALL SELECT 4, 'aggregate', 'Populated H3 cells', (SELECT count(DISTINCT h3_cell) FROM {t('gold_cell_access')}), 'res {H3_RES}, for the hex layer and scenarios'
UNION ALL SELECT 5, 'serve', 'Refreshed', unix_timestamp(), 'Unix time of the latest run'
""")

display(spark.table(t("gold_pipeline_metric")).orderBy("step_order"))
