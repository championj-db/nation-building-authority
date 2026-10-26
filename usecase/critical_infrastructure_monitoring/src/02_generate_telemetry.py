# Databricks notebook source
# Step 2 of the critical infrastructure monitoring pipeline: generate synthetic
# sighting telemetry with dbldatagen and land it as JSON files in the use
# case's Unity Catalog volume.
#
# The batch models what a real regulator's feeds deliver: high-volume events
# (camera and weigh-in-machine reads) that arrive out of order, with a share
# of late stragglers from previous days, and a realistic rate of plate
# misreads that the silver identity resolver has to cope with.
#
# Run with history_days > 1 for a backfill, then history_days = 1 on a
# schedule. Re-landing an overlapping window is safe: sighting ids are
# deterministic and silver deduplicates on them.

# COMMAND ----------

# MAGIC %pip install dbldatagen==0.4.0.post1

# COMMAND ----------

import datetime
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
    DAY_HOURS, NIGHT_HOURS, NORMAL_MASS_MULTIPLIERS,
    OCR_CONFUSION_DST, OCR_CONFUSION_SRC, OVERLOAD_MASS_MULTIPLIERS,
    SITE_CATALOGUE, SIGHTING_SOURCES, ansi_sql_off, get_params, plate_expr,
    resolve_as_of, volume_dir
)

params = get_params(
    {
        "catalog": "",
        "schema": "",
        "volume": "landing",
        "seed": 42,
        "as_of": "",
        "num_assets": 800,
        "num_sites": len(SITE_CATALOGUE),
        "events_per_day": 150000,
        "history_days": 14,
        "straggler_pct": 3,
        "ocr_misread_pct": 5,
        "random_sub_pct": 2,
        "unresolved_pct": 1,
        "partitions": 8,
    },
    dbutils,
)
if not params["catalog"] or not params["schema"] or not params["volume"]:
    raise ValueError("catalog, schema and volume parameters are required")

CATALOG = params["catalog"]
SCHEMA = params["schema"]
VOLUME = params["volume"]
SEED = int(params["seed"])
AS_OF = resolve_as_of(params["as_of"])
NUM_ASSETS = int(params["num_assets"])
NUM_SITES = min(int(params["num_sites"]), len(SITE_CATALOGUE))
EVENTS_PER_DAY = int(params["events_per_day"])
HISTORY_DAYS = max(1, int(params["history_days"]))
STRAGGLER_PCT = int(params["straggler_pct"])
OCR_MISREAD_PCT = int(params["ocr_misread_pct"])
RANDOM_SUB_PCT = int(params["random_sub_pct"])
UNRESOLVED_PCT = int(params["unresolved_pct"])
PARTITIONS = int(params["partitions"])
TOTAL_ROWS = EVENTS_PER_DAY * HISTORY_DAYS
LANDING_DIR = volume_dir(CATALOG, SCHEMA, VOLUME, "telemetry")

print(f"Telemetry: {TOTAL_ROWS} rows over {HISTORY_DAYS} days to {LANDING_DIR}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Base events
# MAGIC dbldatagen produces the random scaffolding (dates, speeds, minutes); the
# MAGIC joins and CASE expressions below attach the asset, apply the cohort risk
# MAGIC patterns and inject the plate read errors. Everything is derived from the
# MAGIC seeded hash of the row, so a rerun of the same window is byte-identical.

# COMMAND ----------

dim_asset = spark.table(f"{CATALOG}.{SCHEMA}.dim_asset")
dim_site = spark.table(f"{CATALOG}.{SCHEMA}.dim_site")

with ansi_sql_off(spark):
    base = (
        dg.DataGenerator(
            spark, name="sightings", rows=TOTAL_ROWS,
            partitions=PARTITIONS, randomSeed=SEED, seedColumnName="sighting_seed",
        )
        .withIdOutput()
        .withColumn("nominal_day_offset", T.IntegerType(),
                    minValue=0, maxValue=HISTORY_DAYS - 1, random=True)
        .withColumn("minute_of_hour", T.IntegerType(),
                    minValue=0, maxValue=59, random=True)
        .withColumn("speed_kph", T.DoubleType(),
                    minValue=35, maxValue=115, random=True, step=0.5)
        .withColumn("source_type", "string", values=SIGHTING_SOURCES, random=True,
                    weights=[55, 30, 15])
        .withColumn("asset_ref", T.LongType(),
                    expr=f"pmod(hash('vehicle', sighting_seed), {NUM_ASSETS})")
        .withColumn("site_ref", T.IntegerType(),
                    expr=f"pmod(hash('site', sighting_seed), {NUM_SITES})")
        .build()
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Risk patterns, plate noise and arrival skew

# COMMAND ----------

night_arr = "array(" + ", ".join(str(h) for h in NIGHT_HOURS) + ")"
day_arr = "array(" + ", ".join(str(h) for h in DAY_HOURS) + ")"
hour_expr = f"""CASE
  WHEN risk_cohort = 'fatigue' AND pmod(hash('hourbias', sighting_seed), 100) < 65
    THEN element_at({night_arr}, 1 + pmod(hash('nighthour', sighting_seed), {len(NIGHT_HOURS)}))
  WHEN pmod(hash('hourbias', sighting_seed), 100) < 8
    THEN element_at({night_arr}, 1 + pmod(hash('nighthour', sighting_seed), {len(NIGHT_HOURS)}))
  ELSE element_at({day_arr}, 1 + pmod(hash('dayhour', sighting_seed), {len(DAY_HOURS)}))
END"""

# The route cohort concentrates on the last corridor in the site catalogue
# (an unusual minority corridor), which is what route-variance detection finds.
route_corridor_last = NUM_SITES - 1
site_ref_expr = f"""CASE
  WHEN risk_cohort = 'route' AND pmod(hash('routeconcentration', sighting_seed), 100) < 80
    THEN {route_corridor_last} - pmod(hash('corridor', sighting_seed), 3)
  ELSE site_ref
END"""

# Late stragglers: events from 1-3 days before their nominal window.
day_offset_expr = f"""CASE
  WHEN pmod(hash('straggler', sighting_seed), 100) < {STRAGGLER_PCT}
    THEN nominal_day_offset + 1 + pmod(hash('stragglerlag', sighting_seed), 3)
  ELSE nominal_day_offset
END"""

plate_noise_expr = f"""CASE
  WHEN pmod(hash('ocr', sighting_seed), 100) < {OCR_MISREAD_PCT}
    THEN overlay(plate,
                 translate(substring(plate, 1 + pmod(hash('ocrpos', sighting_seed), 6), 1),
                           '{OCR_CONFUSION_SRC}', '{OCR_CONFUSION_DST}'),
                 1 + pmod(hash('ocrpos', sighting_seed), 6), 1)
  WHEN pmod(hash('ocr', sighting_seed), 100) < {OCR_MISREAD_PCT + RANDOM_SUB_PCT}
    THEN overlay(plate,
                 char(65 + pmod(hash('randomsub', sighting_seed), 26)),
                 1 + pmod(hash('ocrpos', sighting_seed), 6), 1)
  WHEN pmod(hash('ocr', sighting_seed), 100) >= {100 - UNRESOLVED_PCT}
    THEN {plate_expr('sighting_seed + 100000000')}
  ELSE plate
END"""

n_lo, n_hi = NORMAL_MASS_MULTIPLIERS
o_lo, o_hi = OVERLOAD_MASS_MULTIPLIERS
mass_expr = f"""CASE
  WHEN risk_cohort = 'mass' AND pmod(hash('massbias', sighting_seed), 100) < 70
    THEN cast(round(registered_mass_kg * ({o_lo} + pmod(hash('massover', sighting_seed), 1000) / 1000.0 * ({o_hi} - {o_lo}))) as long)
  ELSE cast(round(registered_mass_kg * ({n_lo} + pmod(hash('massnormal', sighting_seed), 1000) / 1000.0 * ({n_hi} - {n_lo}))) as long)
END"""

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assemble the event record

# COMMAND ----------

events = (
    base
    .join(
        dim_asset.select(
            F.col("asset_id").alias("reg_asset_id"),
            F.col("registration_plate").alias("plate"),
            "registered_mass_kg", "axle_count", "risk_cohort",
        ),
        F.col("asset_ref") == F.col("reg_asset_id"),
    )
    .join(
        dim_site.select(
            F.col("site_id").alias("site_join_id"),
            "road_name", "locality", "state", "latitude", "longitude", "heading",
        ),
        F.col("site_ref") == F.col("site_join_id"),
    )
    .withColumn("hour_of_day", F.expr(hour_expr))
    .withColumn("site_id", F.expr(site_ref_expr))
    .withColumn("day_offset", F.expr(day_offset_expr))
    .withColumn("event_ts", F.expr(f"""to_timestamp(concat(
        date_sub(date '{AS_OF}', day_offset), 'T',
        lpad(cast(hour_of_day as string), 2, '0'), ':',
        lpad(cast(minute_of_hour as string), 2, '0'), ':00'))"""))
    .withColumn("event_ts_epoch_ms", (F.col("event_ts").cast("long") * 1000))
    .withColumn("sighted_plate_raw", F.expr(plate_noise_expr))
    .withColumn("mass_estimate_kg", F.expr(mass_expr))
    .withColumn("axle_count_est", F.col("axle_count"))
    # Deterministic natural key: re-landing the same event is deduplicated in silver.
    .withColumn("sighting_id", F.expr(
        "md5(concat(sighted_plate_raw, '|', cast(event_ts_epoch_ms as string), '|', cast(site_id as string)))"
    ))
    .select(
        "sighting_id", "event_ts_epoch_ms", "hour_of_day", "sighted_plate_raw",
        "site_id", "road_name", "locality", "state", "latitude", "longitude",
        "heading", "source_type", "speed_kph", "axle_count_est", "mass_estimate_kg",
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Land as JSON in the volume
# MAGIC Rows are written in shuffled order across files, so arrival order never
# MAGIC matches event order and bronze must be tolerant of out-of-order events -
# MAGIC exactly the property the use case is built to demonstrate.

# COMMAND ----------

(events.write
    .mode("append")
    .json(LANDING_DIR))

summary = events.agg(
    F.min("event_ts_epoch_ms").alias("min_epoch_ms"),
    F.max("event_ts_epoch_ms").alias("max_epoch_ms"),
    F.count("*").alias("rows"),
).collect()[0]

print(f"Landed {summary['rows']} events in {LANDING_DIR}")
print(f"Event window: {datetime.datetime.fromtimestamp(summary['min_epoch_ms'] / 1000)} "
      f"to {datetime.datetime.fromtimestamp(summary['max_epoch_ms'] / 1000)}")
print(f"Plate noise target: {OCR_MISREAD_PCT}% OCR-confusable, "
      f"{RANDOM_SUB_PCT}% random substitution, {UNRESOLVED_PCT}% unmatchable")

# COMMAND ----------

print("Telemetry batch complete. Bronze ingest (03) will pick these files up incrementally.")
