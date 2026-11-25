# Databricks notebook source
# MAGIC %pip install --quiet "dbldatagen>=0.4.0.post1,<0.5"

# COMMAND ----------

# Step 4 of the geospatial analysis pipeline: synthetic households.
#
# The only synthetic data in the use case. Households are generated with dbldatagen (Databricks
# Labs Data Generator) from ABS 2021 Census-shaped distributions, then placed on the map in
# proportion to the real ABS population:
#
#   1  Each SA2's estimated resident population is shared across its SA1s. SA1s are designed by
#      the ABS to hold roughly 200-800 residents, so an even share follows real settlement
#      closely; SA1s far larger than their SA2's typical SA1 (national parks, industrial land)
#      get a reduced share.
#   2  Households get a size, tenure and dwelling type (dbldatagen, seeded) and a count of
#      residents aged 65+ drawn against the SA2's real 65+ share.
#   3  Each household is given a point inside its SA1 by rejection sampling: candidate points are
#      drawn in the SA1's bounding box and kept when ST_Contains says they fall inside the polygon.
#      The rare household left without a point (very thin polygons) uses ST_PointOnSurface.
#
# Every random draw is a seeded hash, so the same seed always produces the same households.

# COMMAND ----------

import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

import dbldatagen as dg  # noqa: E402

from common import (  # noqa: E402
    HOUSEHOLD_SIZE_WEIGHTS, MEAN_HOUSEHOLD_SIZE, TENURE_WEIGHTS, fq, get_params, hash_uniform_expr,
)

params = get_params({"catalog": "", "schema": "", "seed": "42", "household_scale": "1.0", "h3_resolution": "8"}, dbutils)
CATALOG, SCHEMA = params["catalog"], params["schema"]
SEED = int(params["seed"])
SCALE = float(params["household_scale"])
H3_RES = int(params["h3_resolution"])
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
if not 0 < SCALE <= 1:
    raise ValueError("household_scale must be in (0, 1] - 1.0 generates one household per real household")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. How many households each SA1 holds

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW sa1_allocation AS
WITH sa1 AS (
  SELECT s.*, percentile_approx(area_sqkm, 0.5) OVER (PARTITION BY sa2_code) AS sa2_median_area
  FROM {t('silver_sa1')} s
),
weighted AS (
  SELECT *, CASE WHEN area_sqkm > 10 * sa2_median_area AND area_sqkm > 5 THEN 0.25 ELSE 1.0 END AS weight
  FROM sa1
),
shared AS (
  SELECT w.*, p.erp_persons, coalesce(p.share_65_plus, 0.17) AS share_65_plus,
         p.erp_persons * w.weight / sum(w.weight) OVER (PARTITION BY w.sa2_code) AS persons_target
  FROM weighted w JOIN {t('silver_population_sa2')} p ON p.sa2_code = w.sa2_code
  WHERE p.erp_persons > 0
)
SELECT *, CAST(round(persons_target * {SCALE} / {MEAN_HOUSEHOLD_SIZE}) AS INT) AS n_households
FROM shared
""")

# Materialised so household ids (a running total in SA1 order) are fixed for every later read.
spark.sql(f"""
CREATE OR REPLACE TABLE {t('tmp_sa1_alloc')} AS
SELECT *, coalesce(sum(n_households) OVER (ORDER BY sa1_code ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS id_start,
       ST_X(ST_PointOnSurface(ST_GeomFromWKB(geom_wkb, 4326))) AS surface_lon,
       ST_Y(ST_PointOnSurface(ST_GeomFromWKB(geom_wkb, 4326))) AS surface_lat
FROM sa1_allocation WHERE n_households > 0
""")
spark.table(t("tmp_sa1_alloc")).createOrReplaceTempView("sa1_alloc")
TOTAL = spark.sql("SELECT sum(n_households) AS n FROM sa1_alloc").first()["n"]
print(f"{TOTAL:,} households to generate (scale {SCALE}, mean size {MEAN_HOUSEHOLD_SIZE:.2f})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Household attributes (dbldatagen)

# COMMAND ----------

partitions = max(8, int(TOTAL // 400_000))
spec = (
    dg.DataGenerator(spark, name="synthetic_households", rows=TOTAL, partitions=partitions,
                     randomSeedMethod="hash_fieldname", randomSeed=SEED)
    .withIdOutput()
    .withColumn("household_size", "int", values=list(HOUSEHOLD_SIZE_WEIGHTS.keys()),
                weights=list(HOUSEHOLD_SIZE_WEIGHTS.values()), random=True)
    .withColumn("tenure", "string", values=list(TENURE_WEIGHTS.keys()),
                weights=list(TENURE_WEIGHTS.values()), random=True)
    .withColumn("dwelling_type", "string", values=["separate_house", "semi_detached", "apartment", "other"],
                weights=[70.3, 12.6, 16.0, 1.1], random=True)
)
spec.build().createOrReplaceTempView("hh_attributes")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Place each household inside its SA1 (rejection sampling with ST_Contains)

# COMMAND ----------

def candidates_sql(round_no: int, oversample: float, sa1_filter: str) -> str:
    u = hash_uniform_expr("sa1_code", "k", str(SEED), f"{round_no}", "'x'")
    v = hash_uniform_expr("sa1_code", "k", str(SEED), f"{round_no}", "'y'")
    return f"""
      WITH need AS (
        SELECT a.sa1_code, a.n_households, a.xmin, a.xmax, a.ymin, a.ymax, a.geom_wkb,
               CAST(least(20000, ceil(a.n_households / a.fill_ratio * {oversample}) + 8) AS INT) AS n_cand
        FROM sa1_alloc a {sa1_filter}
      ),
      cand AS (
        SELECT sa1_code, n_households, geom_wkb, k,
               xmin + {u} * (xmax - xmin) AS lon, ymin + {v} * (ymax - ymin) AS lat
        FROM need LATERAL VIEW explode(sequence(1, n_cand)) AS k
      )
      SELECT sa1_code, lon, lat, row_number() OVER (PARTITION BY sa1_code ORDER BY k) AS slot
      FROM cand
      WHERE ST_Contains(ST_GeomFromWKB(geom_wkb, 4326), ST_Point(lon, lat, 4326))
    """


spark.sql(f"""
CREATE OR REPLACE TABLE {t('tmp_household_points')} AS
SELECT c.* FROM ({candidates_sql(1, 1.4, '')}) c JOIN sa1_alloc a ON a.sa1_code = c.sa1_code
WHERE c.slot <= a.n_households
""")

# Second round for SA1s that came up short (irregular shapes), with heavier oversampling.
short = spark.sql(f"""
  SELECT a.sa1_code, a.n_households - coalesce(p.got, 0) AS missing
  FROM sa1_alloc a LEFT JOIN (SELECT sa1_code, count(*) AS got FROM {t('tmp_household_points')} GROUP BY 1) p
    ON p.sa1_code = a.sa1_code
  WHERE a.n_households > coalesce(p.got, 0)
""")
short.createOrReplaceTempView("short_sa1")
n_short = short.count()
if n_short:
    spark.sql(f"""
    INSERT INTO {t('tmp_household_points')}
    SELECT c.sa1_code, c.lon, c.lat, c.slot + coalesce(p.got, 0) AS slot
    FROM ({candidates_sql(2, 6.0, 'WHERE a.sa1_code IN (SELECT sa1_code FROM short_sa1)')}) c
    JOIN short_sa1 s ON s.sa1_code = c.sa1_code
    LEFT JOIN (SELECT sa1_code, count(*) AS got FROM {t('tmp_household_points')} GROUP BY 1) p ON p.sa1_code = c.sa1_code
    WHERE c.slot <= s.missing
    """)
print(f"{n_short:,} SA1s needed a second sampling round")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Assemble the household table

# COMMAND ----------

u65 = hash_uniform_expr("h.id", "x", str(SEED), "'age65'")
spark.sql(f"""
CREATE OR REPLACE TABLE {t('silver_household')}
COMMENT 'SYNTHETIC households placed in proportion to ABS ERP. Not real people. Location is identifying: never expose rows, only suppressed aggregates.'
TBLPROPERTIES ('nba.synthetic' = 'true', 'nba.seed' = '{SEED}', 'nba.household_scale' = '{SCALE}')
AS
WITH slots AS (
  SELECT a.sa1_code, a.sa2_code, a.sa2_name, a.sa3_code, a.sa3_name, a.sa4_code, a.sa4_name, a.state_code,
         a.share_65_plus, a.surface_lon, a.surface_lat, CAST(a.id_start + slot - 1 AS BIGINT) AS household_id, slot
  FROM sa1_alloc a LATERAL VIEW explode(sequence(1, a.n_households)) s AS slot
),
placed AS (
  SELECT sl.*, p.lon, p.lat
  FROM slots sl LEFT JOIN {t('tmp_household_points')} p ON p.sa1_code = sl.sa1_code AND p.slot = sl.slot
),
located AS (
  SELECT pl.*,
    coalesce(pl.lon, pl.surface_lon) AS longitude, coalesce(pl.lat, pl.surface_lat) AS latitude
  FROM placed pl
)
SELECT
  pl.household_id, pl.sa1_code, pl.sa2_code, pl.sa2_name, pl.sa3_code, pl.sa3_name, pl.sa4_code, pl.sa4_name,
  pl.state_code,
  pl.longitude, pl.latitude, h3_longlatash3(pl.longitude, pl.latitude, {H3_RES}) AS h3_cell,
  pl.lon IS NULL AS placed_by_fallback,
  h.household_size, h.tenure, h.dwelling_type,
  CAST(size(filter(sequence(1, h.household_size), x -> {u65} < pl.share_65_plus)) AS INT) AS persons_65_plus
FROM located pl JOIN hh_attributes h ON h.id = pl.household_id
""")
for tmp in ("tmp_household_points", "tmp_sa1_alloc"):
    spark.sql(f"DROP TABLE IF EXISTS {t(tmp)}")

display(spark.sql(f"""
  SELECT state_code, count(*) AS households, sum(household_size) AS persons, sum(persons_65_plus) AS persons_65_plus,
         count_if(placed_by_fallback) AS fallback_placed
  FROM {t('silver_household')} GROUP BY 1 ORDER BY 1
"""))
