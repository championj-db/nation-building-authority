# Databricks notebook source
# Step 5 of the geospatial analysis pipeline: containment analysis (point in polygon at scale).
#
# Local government areas do not nest in the ASGS statistical hierarchy, so each household has to
# be tested against the LGA polygons themselves. Testing ~11 million points against 547 detailed
# polygons directly is all-pairs work; instead each polygon is tessellated into H3 cells
# (h3_tessellateaswkb):
#
#   core chips      cells wholly inside the polygon - a household in one is assigned by cell id
#                   alone, no geometry test
#   boundary chips  the polygon clipped to the cell - only here is ST_Contains evaluated, against
#                   a small chip rather than the whole polygon
#
# A household that falls in no chip (coastline generalisation, slivers between polygons) takes the
# most common LGA of its SA1, so every household lands in exactly one LGA.
#
# Remoteness Areas are built by the ABS from whole SA1s, so remoteness is located once per SA1
# (its ST_PointOnSurface against RA chips) and inherited by the SA1's households - exact by the
# ABS's own construction, and 61,845 tests instead of 11 million.
#
# Remoteness then drives the one modelled attribute that depends on location: whether the
# household has a motor vehicle (NO_VEHICLE_RATE, seeded hash).

# COMMAND ----------

import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import CONTAIN_H3_RES, NO_VEHICLE_RATE, REMOTENESS, fq, get_params, hash_uniform_expr  # noqa: E402

params = get_params({"catalog": "", "schema": "", "seed": "42"}, dbutils)
RA_H3_RES = 5          # coarser chips for the few, very large Remoteness Area polygons
RA_SIMPLIFY_DEG = 0.005  # RA edges follow SA1 boundaries; ~500 m generalisation cannot move an SA1's interior point
CATALOG, SCHEMA, SEED = params["catalog"], params["schema"], int(params["seed"])
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731

# COMMAND ----------

# MAGIC %md
# MAGIC ## Tessellate the zones

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {t('silver_zone_chip')}
COMMENT 'LGA (H3 res {CONTAIN_H3_RES}) and Remoteness Area (H3 res {RA_H3_RES}) polygons tessellated into chips for containment joins'
AS
SELECT level, code, name, state_code, {CONTAIN_H3_RES} AS h3_res, chip.cellid AS h3_cell, chip.core AS core, chip.chip AS chip_wkb
FROM {t('silver_boundary')}
LATERAL VIEW explode(h3_tessellateaswkb(geom_wkb, {CONTAIN_H3_RES})) c AS chip
WHERE kind = 'analysis' AND level = 'lga'
UNION ALL
SELECT level, code, name, state_code, {RA_H3_RES} AS h3_res, chip.cellid, chip.core, chip.chip
FROM {t('silver_boundary')}
LATERAL VIEW explode(h3_tessellateaswkb(ST_AsBinary(ST_Simplify(ST_GeomFromWKB(geom_wkb, 4326), {RA_SIMPLIFY_DEG})), {RA_H3_RES})) c AS chip
WHERE kind = 'analysis' AND level = 'ra' AND right(code, 1) IN ('0', '1', '2', '3', '4')
""")

# Remoteness per SA1, from a point guaranteed to be inside it.
spark.sql(f"""
CREATE OR REPLACE TABLE {t('tmp_sa1_ra')} AS
WITH p AS (
  SELECT sa1_code, sa2_code, ST_PointOnSurface(ST_GeomFromWKB(geom_wkb, 4326)) AS pt FROM {t('silver_sa1')}
),
hits AS (
  SELECT p.sa1_code, p.sa2_code, z.code AS ra_code, z.core
  FROM p JOIN {t('silver_zone_chip')} z
    ON z.level = 'ra' AND z.h3_cell = h3_longlatash3(ST_X(p.pt), ST_Y(p.pt), {RA_H3_RES})
  WHERE z.core OR ST_Contains(ST_GeomFromWKB(z.chip_wkb, 4326), p.pt)
  QUALIFY row_number() OVER (PARTITION BY p.sa1_code ORDER BY z.core DESC, z.code) = 1
),
sa2_mode AS (SELECT sa2_code, mode(ra_code) AS ra_code FROM hits GROUP BY sa2_code)
SELECT s.sa1_code, coalesce(h.ra_code, m.ra_code) AS ra_code,
       CASE WHEN h.ra_code IS NOT NULL THEN 'sa1_point' ELSE 'sa2_fallback' END AS ra_method
FROM {t('silver_sa1')} s LEFT JOIN hits h ON h.sa1_code = s.sa1_code LEFT JOIN sa2_mode m ON m.sa2_code = s.sa2_code
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Point-in-polygon via chips

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW zone_match AS
WITH hh AS (
  SELECT household_id, sa1_code, longitude, latitude,
         h3_longlatash3(longitude, latitude, {CONTAIN_H3_RES}) AS cell
  FROM {t('silver_household')}
),
hits AS (
  SELECT hh.household_id, hh.sa1_code, z.level, z.code, z.name, z.core
  FROM hh JOIN {t('silver_zone_chip')} z ON z.level = 'lga' AND z.h3_cell = hh.cell
  WHERE z.core OR ST_Contains(ST_GeomFromWKB(z.chip_wkb, 4326), ST_Point(hh.longitude, hh.latitude, 4326))
)
SELECT household_id, sa1_code, level, code, name, CASE WHEN core THEN 'core_chip' ELSE 'boundary_chip' END AS method
FROM hits
-- generalised neighbours can overlap by a few metres: keep one zone per level, preferring a core hit
QUALIFY row_number() OVER (PARTITION BY household_id, level ORDER BY core DESC, code) = 1
""")
spark.sql(f"CREATE OR REPLACE TABLE {t('tmp_zone_match')} AS SELECT * FROM zone_match")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assemble, with the SA1 fallback and the vehicle attribute

# COMMAND ----------

vehicle_rate = " ".join(f"WHEN '{k}' THEN {v}" for k, v in NO_VEHICLE_RATE.items())
ra_label = " ".join(f"WHEN '{k}' THEN '{v}'" for k, v in REMOTENESS.items())
u_vehicle = hash_uniform_expr("h.household_id", str(SEED), "'vehicle'")

spark.sql(f"""
CREATE OR REPLACE TABLE {t('silver_household_located')}
COMMENT 'SYNTHETIC households with their LGA and Remoteness Area by point-in-polygon. Never expose rows.'
TBLPROPERTIES ('nba.synthetic' = 'true')
AS
WITH sa1_mode AS (
  SELECT sa1_code, level, max_by(code, n) AS code, max_by(name, n) AS name
  FROM (SELECT sa1_code, level, code, name, count(*) AS n FROM {t('tmp_zone_match')} GROUP BY ALL)
  GROUP BY sa1_code, level
),
lga AS (SELECT household_id, code, name, method FROM {t('tmp_zone_match')} WHERE level = 'lga'),
joined AS (
  SELECT h.*,
         coalesce(l.code, lm.code) AS lga_code, coalesce(l.name, lm.name) AS lga_name,
         r.ra_code,
         CASE WHEN l.code IS NULL THEN 'sa1_fallback' ELSE l.method END AS lga_method,
         r.ra_method
  FROM {t('silver_household')} h
  LEFT JOIN lga l ON l.household_id = h.household_id
  LEFT JOIN sa1_mode lm ON lm.sa1_code = h.sa1_code AND lm.level = 'lga'
  LEFT JOIN {t('tmp_sa1_ra')} r ON r.sa1_code = h.sa1_code
)
SELECT h.*,
       right(h.ra_code, 1) AS ra_class,
       CASE right(h.ra_code, 1) {ra_label} END AS ra_label,
       {u_vehicle} < CASE right(h.ra_code, 1) {vehicle_rate} ELSE 0.07 END AS no_vehicle
FROM joined h
""")
for tmp in ("tmp_zone_match", "tmp_sa1_ra"):
    spark.sql(f"DROP TABLE IF EXISTS {t(tmp)}")

display(spark.sql(f"""
  SELECT lga_method, ra_method, count(*) AS households, count_if(lga_code IS NULL) AS no_lga, count_if(ra_code IS NULL) AS no_ra
  FROM {t('silver_household_located')} GROUP BY ALL ORDER BY households DESC
"""))
