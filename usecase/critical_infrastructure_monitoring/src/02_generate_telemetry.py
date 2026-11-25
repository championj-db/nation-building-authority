# Databricks notebook source
# Step 2 of the critical infrastructure monitoring pipeline: synthetic telemetry and hazard
# warnings, landed as JSON in the use case's Unity Catalog volume.
#
# Two feeds, as an operations centre would receive them from many operators and the weather
# service:
#   telemetry/  15-minute sensor readings for every asset metric over the history window
#   hazards/    weather warnings (heatwave, flood, bushfire, storm) with a centre and radius
#
# Readings are physically driven: baseline + daily load cycle + noise, plus the effect of any
# active warning the asset sits inside (scaled by severity, proximity and how long the warning has
# run), plus the demo storylines and slow background deterioration from common.py. The feed also
# carries the defects real telemetry has - late arrival, duplicates, unregistered sensors and
# implausible spikes - which silver has to handle.

# COMMAND ----------

import datetime as dt
import os
import sys

from pyspark.sql import functions as F

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir")
_candidates = [_src, os.path.dirname(_src) if _src.endswith(".py") else None, "src", "."]
_src_dir = next((c for c in _candidates if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import (
    ASSET_CLASSES, DRIFT_MAX_EXCEEDANCE, DRIFTING_ASSET_PCT, DUPLICATE_READING_PCT,
    GLITCH_READING_PCT, HAZARD_EFFECTS, HAZARD_WARNINGS, LATE_READING_PCT, LOCALITIES, METRICS,
    READING_INTERVAL_MINUTES, SEVERITY_WEIGHT, STORYLINES, UNKNOWN_SENSOR_PCT, generation_tag,
    get_params, haversine_km_expr, local_now, resolve_as_of, timestamp_sql, use_local_time,
    volume_dir,
)

params = get_params(
    {"catalog": "", "schema": "", "volume": "landing", "seed": 42, "history_days": 7, "as_of": ""},
    dbutils,
)
if not params["catalog"] or not params["schema"]:
    raise ValueError("catalog and schema parameters are required")

use_local_time(spark)
CATALOG, SCHEMA, VOLUME = params["catalog"], params["schema"], params["volume"]
SEED = int(params["seed"])
HISTORY_DAYS = max(1, int(params["history_days"]))
AS_OF = resolve_as_of(params["as_of"])
GENERATION = generation_tag(AS_OF)
TELEMETRY_DIR = volume_dir(CATALOG, SCHEMA, VOLUME, "telemetry", GENERATION)
HAZARD_DIR = volume_dir(CATALOG, SCHEMA, VOLUME, "hazards", GENERATION)

# Anchor the timeline at "now", floored to the reading interval: today's readings stop here.
_now = local_now()
NOW = _now.replace(minute=_now.minute - _now.minute % READING_INTERVAL_MINUTES, second=0)
START = NOW - dt.timedelta(days=HISTORY_DAYS)
INTERVALS = HISTORY_DAYS * 24 * 60 // READING_INTERVAL_MINUTES + 1
NOW_SQL, START_SQL = timestamp_sql(NOW), timestamp_sql(START)
print(f"Generating {INTERVALS} intervals from {START} to {NOW} into {GENERATION}")


def u(*parts: str) -> str:
    """Deterministic uniform [0, 1) from the seed and the given SQL expressions."""
    return f"(pmod(hash({SEED}, {', '.join(parts)}), 1000003) / 1000003.0)"


# COMMAND ----------

# MAGIC %md
# MAGIC ## Hazard warnings feed

# COMMAND ----------

loc = {l[0]: l for l in LOCALITIES}
warnings = []
for wid, title, htype, severity, centre, radius, started_h, ends_h in HAZARD_WARNINGS:
    lat, lon = (loc[centre][2], loc[centre][3]) if isinstance(centre, str) else centre
    issued = NOW - dt.timedelta(hours=started_h)
    warnings.append((wid, title, htype, severity, float(lat), float(lon), float(radius),
                     issued.strftime("%Y-%m-%d %H:%M:%S"),
                     (NOW + dt.timedelta(hours=ends_h)).strftime("%Y-%m-%d %H:%M:%S")))
hazards = (
    spark.createDataFrame(
        warnings,
        "warning_id string, title string, hazard_type string, severity string, centre_lat double, "
        "centre_lon double, radius_km double, valid_from string, valid_to string",
    )
    .withColumn("issuer", F.lit("Synthetic weather warnings feed"))
    .withColumn("valid_from", F.to_timestamp("valid_from"))
    .withColumn("valid_to", F.to_timestamp("valid_to"))
)
hazards.withColumn("valid_from", F.date_format("valid_from", "yyyy-MM-dd'T'HH:mm:ss")) \
    .withColumn("valid_to", F.date_format("valid_to", "yyyy-MM-dd'T'HH:mm:ss")) \
    .write.mode("overwrite").json(HAZARD_DIR)
print(f"Landed {len(warnings)} warnings in {HAZARD_DIR}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sensor timeline
# MAGIC Every registered sensor gets a reading per interval. Values are built in SQL from
# MAGIC deterministic hashes, so the same seed and as-of time produce the same world.

# COMMAND ----------

assets = spark.table(f"{CATALOG}.{SCHEMA}.dim_asset")
sensors = spark.table(f"{CATALOG}.{SCHEMA}.dim_sensor").select("sensor_id", "asset_id", "metric").join(
    assets.select("asset_id", "asset_class", "asset_name", "latitude", "longitude"), "asset_id"
)

metric_rows = [(m, v[2], v[3], v[4], v[6], v[7], v[8]) for m, v in METRICS.items()]
metric_df = spark.createDataFrame(
    metric_rows,
    "metric string, m_base double, m_sd double, m_diurnal double, m_alarm double, m_direction string, m_kind string",
)

grid = (
    sensors.join(metric_df, "metric")
    .crossJoin(spark.range(INTERVALS).withColumnRenamed("id", "i"))
    .withColumn("event_ts", F.expr(
        f"{START_SQL} + make_interval(0, 0, 0, 0, 0, cast(i * {READING_INTERVAL_MINUTES} as int), 0)"))
    .withColumn("hour_f", F.expr("hour(event_ts) + minute(event_ts) / 60.0"))
    # daily load cycle peaking late afternoon; "low" metrics (storage, pressure) dip as demand peaks
    .withColumn("cycle", F.expr("sin(2 * pi() * (hour_f - 10) / 24)"))
    .withColumn("span", F.expr("CASE WHEN m_direction = 'high' THEN m_alarm - m_base ELSE m_base - m_alarm END"))
    .withColumn("sign", F.expr("CASE WHEN m_direction = 'high' THEN 1.0 ELSE -1.0 END"))
    .withColumn("noise", F.expr(
        f"m_sd * 2 * ({u('sensor_id', 'i', '1')} + {u('sensor_id', 'i', '2')} + {u('sensor_id', 'i', '3')} - 1.5)"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Hazard effects
# MAGIC Each warning affects the metrics it physically bears on (`HAZARD_EFFECTS`), scaled by
# MAGIC severity, proximity to the warning centre, and a 6-hour build-up from issue time.

# COMMAND ----------

effect_rows = [(h, m, float(e)) for h, effects in HAZARD_EFFECTS.items() for m, e in effects.items()]
effects = spark.createDataFrame(effect_rows, "hazard_type string, metric string, effect double")
sev = spark.createDataFrame([(k, float(v)) for k, v in SEVERITY_WEIGHT.items()], "severity string, sev_w double")

exposure = (
    sensors.select("sensor_id", "metric", "latitude", "longitude")
    .crossJoin(hazards.select("hazard_type", "severity", "centre_lat", "centre_lon", "radius_km", "valid_from", "valid_to"))
    .withColumn("dist_km", F.expr(haversine_km_expr("latitude", "longitude", "centre_lat", "centre_lon")))
    .withColumn("prox", F.expr("greatest(0.0, 1 - dist_km / radius_km)"))
    .filter("prox > 0")
    .join(effects, ["hazard_type", "metric"])
    .join(sev, "severity")
    .select("sensor_id", "valid_from", "valid_to",
            (F.col("effect") * F.col("sev_w") * F.expr("0.4 + 0.6 * prox")).alias("peak_effect"))
)

hazard_delta = (
    grid.select("sensor_id", "i", "event_ts")
    .join(F.broadcast(exposure), "sensor_id")
    .withColumn("ramp", F.expr(
        "CASE WHEN event_ts < valid_from OR event_ts > valid_to THEN 0.0 "
        "ELSE least(1.0, (unix_timestamp(event_ts) - unix_timestamp(valid_from)) / 21600.0) END"))
    .groupBy("sensor_id", "i").agg(F.sum(F.col("peak_effect") * F.col("ramp")).alias("hazard_delta"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Storylines and background deterioration
# MAGIC Storylines and drift are expressed as a share of each metric's alarm band, so they move a
# MAGIC metric toward its own limit regardless of units.

# COMMAND ----------

story_rows = [
    (f"{locality} {ASSET_CLASSES[cls][1].title()}", metric, float(target), float(ramp_h))
    for cls, locality, metric, target, ramp_h in STORYLINES
]
stories = spark.createDataFrame(story_rows, "asset_name string, metric string, s_target double, s_ramp_h double")

readings = (
    grid.join(hazard_delta, ["sensor_id", "i"], "left").fillna(0.0, subset=["hazard_delta"])
    .join(F.broadcast(stories), ["asset_name", "metric"], "left")
    .withColumn("story", F.expr(
        "CASE WHEN s_target IS NULL THEN 0.0 ELSE s_target * least(1.0, greatest(0.0, "
        f"(unix_timestamp(event_ts) - (unix_timestamp({NOW_SQL}) - s_ramp_h * 3600)) / (s_ramp_h * 3600))) END"))
    .withColumn("drift", F.expr(
        f"CASE WHEN pmod(hash({SEED}, 'drift', asset_id), 100) < {DRIFTING_ASSET_PCT} "
        f"THEN {DRIFT_MAX_EXCEEDANCE} * {u('asset_id', repr('driftsize'))} * i / {INTERVALS} ELSE 0.0 END"))
    .withColumn("gauge_value", F.expr(
        "m_base + sign * m_diurnal * cycle + noise + hazard_delta + sign * span * (story + drift)"))
    .withColumn("count_rate", F.expr("m_base + hazard_delta + span * (story + drift)"))
    .withColumn("value", F.expr(
        "CASE WHEN m_kind = 'count' THEN "
        f"  CASE WHEN count_rate < 1 THEN CASE WHEN {u('sensor_id', 'i', '4')} < count_rate THEN 1.0 ELSE 0.0 END "
        f"  ELSE round(count_rate * (0.6 + 0.8 * {u('sensor_id', 'i', '5')})) END "
        "WHEN metric = 'level_pct' THEN least(100.0, greatest(0.0, gauge_value)) "
        "WHEN metric = 'surface_water_mm' THEN greatest(0.0, gauge_value) "
        # protection and control act just past the alarm limit (a transformer trips, a pump
        # cuts out), so engineered quantities do not run far beyond it
        "WHEN m_direction = 'high' THEN greatest(0.0, least(gauge_value, m_base + span * 1.08)) "
        "ELSE greatest(m_base - span * 1.08, gauge_value) END"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Feed defects: late arrival, duplicates, unregistered sensors, glitches

# COMMAND ----------

feed = (
    readings
    .withColumn("late", F.expr(f"{u('sensor_id', 'i', '6')} * 100 < {LATE_READING_PCT}"))
    .withColumn("arrival_ts", F.expr(
        "event_ts + make_interval(0, 0, 0, 0, 0, cast(CASE WHEN late "
        f"THEN 60 + {u('sensor_id', 'i', '7')} * 300 ELSE 1 + {u('sensor_id', 'i', '8')} * 4 END as int), 0)"))
    .filter(F.col("arrival_ts") <= F.expr(NOW_SQL))  # late readings still in flight have not arrived
    .withColumn("glitch", F.expr(f"{u('sensor_id', 'i', '9')} * 100 < {GLITCH_READING_PCT}"))
    .withColumn("value", F.expr("CASE WHEN glitch THEN m_base + sign * span * 10 ELSE value END"))
    .withColumn("sensor_id", F.expr(
        f"CASE WHEN {u('sensor_id', 'i', '10')} * 100 < {UNKNOWN_SENSOR_PCT} "
        "THEN concat('UNREG-', substring(md5(concat(sensor_id, cast(i as string))), 1, 8)) ELSE sensor_id END"))
    .withColumn("reading_id", F.expr("md5(concat(sensor_id, '|', cast(unix_timestamp(event_ts) as string)))"))
    .select(
        "reading_id", "sensor_id",
        (F.unix_timestamp("event_ts") * 1000).alias("event_ts_epoch_ms"),
        (F.unix_timestamp("arrival_ts") * 1000).alias("arrival_ts_epoch_ms"),
        F.round("value", 3).alias("value"),
    )
)
dupes = feed.filter(F.expr(f"pmod(hash({SEED}, 'dupe', reading_id), 10000) < {int(DUPLICATE_READING_PCT * 100)}"))

feed.unionByName(dupes).write.mode("overwrite").json(TELEMETRY_DIR)
summary = spark.read.json(TELEMETRY_DIR).agg(
    F.count("*").alias("rows"), F.countDistinct("sensor_id").alias("sensor_ids"),
    F.max("event_ts_epoch_ms").alias("latest_ms"),
).collect()[0]
print(f"Landed {summary['rows']:,} readings from {summary['sensor_ids']} sensor ids "
      f"(latest {dt.datetime.fromtimestamp(summary['latest_ms'] / 1000)} UTC) in {TELEMETRY_DIR}")
