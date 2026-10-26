# Databricks notebook source
# Step 1 of the critical infrastructure monitoring pipeline: generate the
# synthetic reference data (operators, assets, sighting sites, inspection
# history) with dbldatagen. Every table is fully rebuilt from the seed, so the
# dataset is reproducible for anyone who runs the bundle.
#
# Parameters arrive from the job (base_parameters) or from widgets when run
# interactively. Nothing environment-specific is written in this file.

# COMMAND ----------

# MAGIC %pip install dbldatagen==0.4.0.post1

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC The `src_dir` parameter locates the use case's `src/` folder (the job
# MAGIC passes `${workspace.file_path}`); the shared model contract lives in
# MAGIC `common.py` there.

# COMMAND ----------

import datetime as dt
import sys

import dbldatagen as dg
from pyspark.sql import functions as F, types as T

import os

# The shared model contract (common.py) lives in this use case's src/ folder.
# The job passes src_dir=${workspace.file_path} (a file path, which is
# normalised to its folder); interactive runs probe well-known locations.
dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir")
_candidates = [_src]
if _src.endswith(".py"):
    _candidates.append(os.path.dirname(_src))
if _src.endswith(".yml"):
    _candidates.append(os.path.join(os.path.dirname(_src), "..", "src"))
_candidates += ["src", "."]
_src_dir = next(
    (c for c in _candidates if c and os.path.isfile(os.path.join(c, "common.py"))),
    None,
)
if _src_dir is None:
    raise FileNotFoundError(
        "common.py not found - pass src_dir pointing at the use case's src folder"
    )
sys.path.insert(0, _src_dir)

from common import (
    ASSET_TYPES, DEFECT_CODES, INSPECTION_TYPES, OPERATOR_NAME_DOMAINS,
    OPERATOR_NAME_REGIONS, OPERATOR_NAME_SUFFIXES, OPERATOR_STATES,
    OPERATOR_TYPES, PLATE_REGEX, SITE_CATALOGUE, ansi_sql_off,
    get_params, plate_expr, resolve_as_of,
)

params = get_params(
    {
        "catalog": "",
        "schema": "",
        "src_dir": "",
        "seed": 42,
        "as_of": "",
        "num_operators": 60,
        "num_assets": 800,
        "num_sites": len(SITE_CATALOGUE),
        "inspections_per_asset": 6,
        "partitions": 8,
    },
    dbutils,
)
if not params["catalog"] or not params["schema"]:
    raise ValueError("catalog and schema parameters are required")

CATALOG = params["catalog"]
SCHEMA = params["schema"]
SEED = int(params["seed"])
AS_OF = resolve_as_of(params["as_of"])
NUM_OPERATORS = int(params["num_operators"])
NUM_ASSETS = int(params["num_assets"])
NUM_SITES = min(int(params["num_sites"]), len(SITE_CATALOGUE))
INSPECTIONS_PER_ASSET = int(params["inspections_per_asset"])
PARTITIONS = int(params["partitions"])

print(f"Reference data: {NUM_OPERATORS} operators, {NUM_ASSETS} assets, "
      f"{NUM_SITES} sites, {NUM_ASSETS * INSPECTIONS_PER_ASSET} inspections, "
      f"seed={SEED}, as_of={AS_OF}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Schema
# MAGIC Recreated idempotently so interactive runs work without a prior deploy.

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Operators

# COMMAND ----------

inspections_begin = (dt.date.fromisoformat(AS_OF) - dt.timedelta(days=365)).isoformat()

operator_name_expr = "concat({})".format(
    ", ' ', ".join(
        f"element_at(array({', '.join(repr(p) for p in parts)}), "
        f"1 + pmod(hash('{tag}', operator_id), {len(parts)}))"
        for parts, tag in (
            (OPERATOR_NAME_REGIONS, "region"),
            (OPERATOR_NAME_DOMAINS, "domain"),
            (OPERATOR_NAME_SUFFIXES, "suffix"),
        )
    )
)

with ansi_sql_off(spark):
    operators = (
        dg.DataGenerator(
            spark, name="operators", rows=NUM_OPERATORS,
            partitions=PARTITIONS, randomSeed=SEED, seedColumnName="operator_id",
        )
        .withIdOutput()
        .withColumn("operator_name", expr=operator_name_expr)
        .withColumn("operator_type", "string", values=OPERATOR_TYPES, random=True,
                    weights=[35, 30, 15, 10, 10])
        .withColumn("state", "string", values=OPERATOR_STATES, random=True,
                    weights=[32, 26, 20, 8, 7, 4, 2, 1])
        .withColumn("safety_rating", T.IntegerType(), minValue=1, maxValue=5, random=True)
        .withColumn("accreditation_expiry", T.DateType(),
                    begin="2026-06-30", end="2029-06-30", interval="1 day", random=True)
        .withColumn("accreditation_status", "string",
                    values=["active", "under_review", "suspended"], random=True,
                    weights=[88, 9, 3])
        .build()
    )

operators.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.dim_operator"
)
print(f"dim_operator: {operators.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assets
# MAGIC Assets carry a synthetic risk cohort so the telemetry can be generated with
# MAGIC realistic risk patterns (night movement, over-mass loading, route
# MAGIC concentration, defect history). The cohort shapes the data only; the risk
# MAGIC engine later rediscovers risk from telemetry alone.

# COMMAND ----------

with ansi_sql_off(spark):
    assets = (
        dg.DataGenerator(
            spark, name="assets", rows=NUM_ASSETS,
            partitions=PARTITIONS, randomSeed=SEED, seedColumnName="asset_id",
        )
        .withIdOutput()
        .withColumn("registration_plate", expr=plate_expr("asset_id"))
        .withColumn("operator_id", T.LongType(),
                   expr=f"pmod(hash('operator', asset_id), {NUM_OPERATORS})")
        .withColumn("asset_type", "string", values=ASSET_TYPES, random=True,
                    weights=[30, 25, 15, 20, 10])
        .withColumn("registered_mass_kg", T.LongType(),
                    minValue=19500, maxValue=42500, random=True, step=500)
        .withColumn("axle_count", T.IntegerType(),
                    values=[3, 4, 5, 6, 7, 8, 9], random=True,
                    weights=[10, 25, 25, 20, 10, 7, 3])
        .withColumn("manufacture_year", T.IntegerType(),
                    minValue=2006, maxValue=2026, random=True)
        .withColumn("risk_cohort", "string",
                    values=["none", "fatigue", "roadworthiness", "mass", "route"],
                    random=True, weights=[70, 10, 8, 7, 5])
        .build()
    )

bad_plates = assets.filter(~F.col("registration_plate").rlike(PLATE_REGEX)).count()
if bad_plates or assets.select("registration_plate").distinct().count() != NUM_ASSETS:
    raise AssertionError("registration plates are not unique and well-formed")

assets.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.dim_asset"
)
print(f"dim_asset: {assets.count()} rows, all plates unique")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sighting sites
# MAGIC A small static catalogue of public road locations (the design mock-up's
# MAGIC alert locations appear in it), enriched with site type and direction.

# COMMAND ----------

from pyspark.sql.window import Window

sites = (
    spark.createDataFrame(
        SITE_CATALOGUE[:NUM_SITES],
        "road_name string, locality string, state string, latitude double, longitude double",
    )
    # dense, deterministic 0-based site id so telemetry can hash into the range
    .withColumn("site_id", (F.row_number().over(Window.orderBy("road_name", "locality")) - 1).cast("int"))
    .withColumn("site_code", F.concat(F.lit("SITE-"), F.lpad(F.col("site_id").cast("string"), 3, "0")))
    .withColumn("site_type", F.expr(
        "element_at(array('anpr_camera', 'weigh_in_motion', 'gps_gateway'), "
        "1 + pmod(hash('stype', site_id), 3))"
    ))
    .withColumn("heading", F.expr(
        "element_at(array('northbound', 'southbound', 'eastbound', 'westbound'), "
        "1 + pmod(hash('dir', site_id), 4))"
    ))
)

sites.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.dim_site"
)
print(f"dim_site: {sites.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Inspection history
# MAGIC Defects are weighted toward the roadworthiness cohort so the risk engine
# MAGIC has a discoverable signal.

# COMMAND ----------

cohort_expr = (
    "CASE "
    "WHEN risk_cohort = 'roadworthiness' AND pmod(hash('outcome', inspection_id), 100) < 60 THEN 'defect' "
    "WHEN pmod(hash('outcome', inspection_id), 100) < 20 THEN 'defect' "
    "ELSE 'pass' END"
)

with ansi_sql_off(spark):
    inspections_base = (
        dg.DataGenerator(
            spark, name="inspections", rows=NUM_ASSETS * INSPECTIONS_PER_ASSET,
            partitions=PARTITIONS, randomSeed=SEED, seedColumnName="inspection_id",
        )
        .withIdOutput()
        .withColumn("asset_id", T.LongType(),
                   expr=f"pmod(hash('asset', inspection_id), {NUM_ASSETS})")
        .withColumn("inspection_date", T.DateType(),
                    begin=inspections_begin, end=AS_OF, interval="1 day", random=True)
        .withColumn("inspection_type", "string", values=INSPECTION_TYPES, random=True,
                    weights=[50, 30, 20])
        .build()
    )

inspections = (
    inspections_base
    .join(
        spark.table(f"{CATALOG}.{SCHEMA}.dim_asset").select("asset_id", "risk_cohort")
            .withColumnRenamed("asset_id", "reg_asset_id"),
        F.col("asset_id") == F.col("reg_asset_id"),
    )
    .withColumn("outcome", F.expr(cohort_expr))
    .withColumn("defect_code", F.expr(
        "CASE WHEN outcome = 'defect' THEN element_at(array({}, 1 + pmod(hash('code', inspection_id), {})) "
        "ELSE NULL END".format(", ".join(repr(c) for c in DEFECT_CODES), len(DEFECT_CODES))
    ))
    .withColumn("defect_severity", F.expr(
        "CASE WHEN outcome = 'defect' THEN "
        "element_at(array('minor', 'major', 'critical'), 1 + pmod(hash('sev', inspection_id), 3)) "
        "ELSE NULL END"
    ))
    .select("inspection_id", "asset_id", "inspection_date", "inspection_type",
            "outcome", "defect_code", "defect_severity")
)

inspections.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.dim_inspection"
)
print(f"dim_inspection: {inspections.count()} rows, "
      f"{inspections.filter("outcome = 'defect'").count()} defects")

# COMMAND ----------

print("Reference data complete. Tables: dim_operator, dim_asset, dim_site, dim_inspection")
