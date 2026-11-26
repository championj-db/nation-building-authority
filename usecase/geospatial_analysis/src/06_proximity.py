# Databricks notebook source
# Step 6 of the geospatial analysis pipeline: proximity analysis (distance to nearest service).
#
# For every synthetic household and every service type, the straight-line distance to the
# nearest site. Done naively that is households x sites - tens of billions of distance
# calculations. H3 makes it tractable without approximating:
#
#   A  For each populated H3 res-5 cell (~250 km2), measure from the cell centre to every site and
#      keep only the sites within d_min + 2r (r bounds the distance from the centre to any point
#      in the cell). No household in the cell can have its nearest site outside that list.
#   B  Repeat at res 8 (~0.7 km2) against that short list, which tightens it to a handful.
#   C  Measure each household exactly (ST_DistanceSphere) against its final candidates only.
#
# Straight-line distance, not road travel time: the README says so and so does the app.

# COMMAND ----------

import os
import sys
import time

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import PRUNE_LEVELS, fq, get_params, haversine_km_expr  # noqa: E402

params = get_params({"catalog": "", "schema": ""}, dbutils)
CATALOG, SCHEMA = params["catalog"], params["schema"]
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731
(RES_A, R_A), (RES_B, R_B) = PRUNE_LEVELS
started = time.time()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Households keyed by their coarse and fine cells

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {t('tmp_hh_cells')} AS
SELECT household_id, longitude, latitude,
       h3_longlatash3(longitude, latitude, {RES_A}) AS cell_a,
       h3_longlatash3(longitude, latitude, {RES_B}) AS cell_b
FROM {t('silver_household_located')}
""")

def centre(cell):
    return (f"ST_X(ST_GeomFromGeoJSON(h3_centerasgeojson({cell})))",
            f"ST_Y(ST_GeomFromGeoJSON(h3_centerasgeojson({cell})))")

# COMMAND ----------

# MAGIC %md
# MAGIC ## A. Coarse cells against every site

# COMMAND ----------

ax, ay = centre("cell_a")
spark.sql(f"""
CREATE OR REPLACE TABLE {t('tmp_cand_a')} AS
WITH cells AS (SELECT DISTINCT cell_a FROM {t('tmp_hh_cells')}),
centred AS (SELECT cell_a, {ax} AS cx, {ay} AS cy FROM cells),
pairs AS (
  SELECT c.cell_a, s.service_type, s.site_id, s.longitude AS sx, s.latitude AS sy,
         {haversine_km_expr('c.cy', 'c.cx', 's.latitude', 's.longitude')} AS d
  FROM centred c CROSS JOIN {t('silver_service_site')} s
)
SELECT cell_a, service_type, site_id, sx, sy
FROM (SELECT *, min(d) OVER (PARTITION BY cell_a, service_type) AS d_min FROM pairs)
WHERE d <= d_min + 2 * {R_A}
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## B. Fine cells against the coarse short list

# COMMAND ----------

bx, by = centre("cell_b")
spark.sql(f"""
CREATE OR REPLACE TABLE {t('tmp_cand_b')} AS
WITH cells AS (SELECT DISTINCT cell_a, cell_b FROM {t('tmp_hh_cells')}),
centred AS (SELECT cell_a, cell_b, {bx} AS cx, {by} AS cy FROM cells),
pairs AS (
  SELECT c.cell_a, c.cell_b, a.service_type, a.site_id, a.sx, a.sy,
         {haversine_km_expr('c.cy', 'c.cx', 'a.sy', 'a.sx')} AS d
  FROM centred c JOIN {t('tmp_cand_a')} a ON a.cell_a = c.cell_a
)
SELECT cell_a, cell_b, service_type, site_id, sx, sy
FROM (SELECT *, min(d) OVER (PARTITION BY cell_a, cell_b, service_type) AS d_min FROM pairs)
WHERE d <= d_min + 2 * {R_B}
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## C. Exact distance per household (ST_DistanceSphere)

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {t('silver_household_access')}
COMMENT 'SYNTHETIC: straight-line distance from each household to its nearest site of each service type'
TBLPROPERTIES ('nba.synthetic' = 'true')
AS
SELECT household_id, service_type,
       min_by(site_id, d_m) AS nearest_site_id,
       round(min(d_m) / 1000.0, 3) AS distance_km
FROM (
  SELECT h.household_id, b.service_type, b.site_id,
         ST_DistanceSphere(ST_Point(h.longitude, h.latitude, 4326), ST_Point(b.sx, b.sy, 4326)) AS d_m
  FROM {t('tmp_hh_cells')} h
  JOIN {t('tmp_cand_b')} b ON b.cell_a = h.cell_a AND b.cell_b = h.cell_b
)
GROUP BY household_id, service_type
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## How much work H3 saved

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {t('silver_proximity_stats')}
COMMENT 'Distance calculations performed by the H3-pruned nearest-site search versus all pairs'
AS
WITH hh AS (SELECT count(*) AS households, count(DISTINCT cell_a) AS cells_a, count(DISTINCT cell_b) AS cells_b FROM {t('tmp_hh_cells')}),
sites AS (SELECT service_type, count(*) AS sites FROM {t('silver_service_site')} GROUP BY 1),
a AS (SELECT service_type, count(*) AS kept_a FROM {t('tmp_cand_a')} GROUP BY 1),
b AS (SELECT service_type, count(*) AS kept_b FROM {t('tmp_cand_b')} GROUP BY 1),
c AS (
  SELECT b.service_type, count(*) AS exact_pairs
  FROM {t('tmp_hh_cells')} h JOIN {t('tmp_cand_b')} b ON b.cell_a = h.cell_a AND b.cell_b = h.cell_b
  GROUP BY 1
)
SELECT s.service_type, hh.households, s.sites,
       CAST(hh.households AS DOUBLE) * s.sites AS all_pairs,
       -- stage A (every coarse cell x every site) + stage B (fine cells x short list) + exact stage C
       CAST(hh.cells_a AS DOUBLE) * s.sites + coalesce(b_pairs.n, 0) + c.exact_pairs AS evaluated_pairs,
       hh.cells_a, hh.cells_b, a.kept_a, b.kept_b, c.exact_pairs
FROM sites s CROSS JOIN hh
JOIN a ON a.service_type = s.service_type
JOIN b ON b.service_type = s.service_type
JOIN c ON c.service_type = s.service_type
LEFT JOIN (
  SELECT a.service_type, count(*) AS n
  FROM (SELECT DISTINCT cell_a, cell_b FROM {t('tmp_hh_cells')}) x JOIN {t('tmp_cand_a')} a ON a.cell_a = x.cell_a
  GROUP BY 1
) b_pairs ON b_pairs.service_type = s.service_type
""")
for tmp in ("tmp_hh_cells", "tmp_cand_a", "tmp_cand_b"):
    spark.sql(f"DROP TABLE IF EXISTS {t(tmp)}")

print(f"Proximity analysis finished in {time.time() - started:,.0f}s")
display(spark.sql(f"""
  SELECT service_type, households, sites, all_pairs, evaluated_pairs,
         round(100 * evaluated_pairs / all_pairs, 4) AS pct_of_all_pairs
  FROM {t('silver_proximity_stats')} ORDER BY service_type
"""))
