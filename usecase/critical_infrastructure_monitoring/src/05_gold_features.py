# Databricks notebook source
# Step 5 of the critical infrastructure monitoring pipeline: gold risk
# features.
#
# One row per asset that was sighted in the feature window, holding every
# normalised factor the risk engine consumes: night movement, rest-window
# anomalies, route concentration, over-mass loading, inspection defect
# history and recent activity surge. Every factor is computed from resolved
# telemetry only - the generator's synthetic risk_cohort is carried along as
# ground truth for evaluation, never as a scoring input.

# COMMAND ----------

import datetime as dt
import sys

from pyspark.sql import functions as F
from pyspark.sql.window import Window

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

from common import OVER_MASS_RATIO_THRESHOLD, get_params, resolve_as_of

params = get_params(
    {
        "catalog": "",
        "schema": "",
        "as_of": "",
        "feature_window_days": 14,
        "recent_days": 3,
    },
    dbutils,
)
if not params["catalog"] or not params["schema"]:
    raise ValueError("catalog and schema parameters are required")

CATALOG = params["catalog"]
SCHEMA = params["schema"]
AS_OF = resolve_as_of(params["as_of"])
FEATURE_WINDOW_DAYS = int(params["feature_window_days"])
RECENT_DAYS = min(int(params["recent_days"]), FEATURE_WINDOW_DAYS - 1)
RUN_TS = dt.datetime.now()  # one run timestamp for every row written this run

window_start = (dt.date.fromisoformat(AS_OF) - dt.timedelta(days=FEATURE_WINDOW_DAYS)).isoformat()
recent_start = (dt.date.fromisoformat(AS_OF) - dt.timedelta(days=RECENT_DAYS)).isoformat()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Movement aggregates

# COMMAND ----------

silver = spark.table(f"{CATALOG}.{SCHEMA}.silver_sighting").filter(
    (F.col("asset_id").isNotNull())
    & (F.col("event_ts") >= F.lit(window_start))
    & (F.col("event_ts") <= F.lit(AS_OF).cast("date") + F.expr("INTERVAL 1 DAY"))
)

movement = (
    silver.groupBy("asset_id")
    .agg(
        F.count("*").alias("sightings_count"),
        F.sum(F.when(F.col("is_night"), 1).otherwise(0)).alias("night_sightings"),
        F.sum(F.when(F.col("is_rest_window"), 1).otherwise(0)).alias("rest_window_sightings"),
        F.approx_count_distinct("site_id").alias("distinct_sites"),
        F.sum(F.when(F.col("mass_ratio") > OVER_MASS_RATIO_THRESHOLD, 1).otherwise(0)).alias("mass_violation_count"),
        F.max("mass_ratio").alias("max_mass_ratio"),
        F.max("speed_kph").alias("max_speed_kph"),
        # struct max keeps the whole last-seen context together
        F.max(F.struct(
            F.col("event_ts").alias("event_ts"),
            F.col("road_name").alias("road_name"),
            F.col("locality").alias("locality"),
            F.col("site_id").alias("site_id"),
        )).alias("last_seen"),
        # activity split for the recent-pattern factor
        F.sum(F.when(F.col("event_ts") >= F.lit(recent_start), 1).otherwise(0)).alias("recent_sightings"),
    )
)

# route concentration: the largest share of an asset's sightings at one site
site_counts = silver.groupBy("asset_id", "site_id").count()
site_window = Window.partitionBy("asset_id")
routes = (
    site_counts
    .withColumn("site_share", F.col("count") / F.sum("count").over(site_window))
    .groupBy("asset_id")
    .agg(F.max("site_share").alias("max_site_share"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Inspection history

# COMMAND ----------

inspections = (
    spark.table(f"{CATALOG}.{SCHEMA}.dim_inspection")
    .filter(F.col("inspection_date") >= F.lit(window_start))
    .groupBy("asset_id")
    .agg(
        F.sum(F.when(F.col("outcome") == "defect", 1).otherwise(0)).alias("defect_count"),
        F.sum(F.when(
            (F.col("outcome") == "defect") & (F.col("defect_severity") == "critical"), 1
        ).otherwise(0)).alias("critical_defect_count"),
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Normalised risk factors
# MAGIC Each factor is capped to the 0-1 range so the transparent weighted sum
# MAGIC in the scoring step stays interpretable: a factor value is the share of
# MAGIC the evidence band, never an unbounded raw number.

# COMMAND ----------

features = (
    movement
    .join(routes, "asset_id")
    .join(
        spark.table(f"{CATALOG}.{SCHEMA}.dim_asset")
            .select("asset_id", "registration_plate", "operator_id", "risk_cohort"),
        "asset_id",
    )
    .join(inspections, "asset_id", "left")
    .fillna(0, subset=["defect_count", "critical_defect_count"])
    .withColumn("night_sightings_ratio", F.col("night_sightings") / F.col("sightings_count"))
    .withColumn("rest_window_ratio", F.col("rest_window_sightings") / F.col("sightings_count"))
    .withColumn("over_mass_ratio", F.col("mass_violation_count") / F.col("sightings_count"))
    .withColumn("recent_rate", F.col("recent_sightings") / F.lit(RECENT_DAYS))
    .withColumn("prior_rate", (F.col("sightings_count") - F.col("recent_sightings"))
               / F.lit(FEATURE_WINDOW_DAYS - RECENT_DAYS))
    .withColumn("recent_surge_ratio", F.col("recent_rate") / (F.col("prior_rate") + 0.05))
    .withColumn("hours_since_last_seen", F.expr(
        f"round((unix_timestamp(date '{AS_OF}' + INTERVAL 1 DAY) - unix_timestamp(last_seen.event_ts)) / 3600.0, 1)"
    ))
    .withColumn("rest_window_anomaly_score", F.least(F.lit(1.0), F.col("rest_window_ratio") * 3))
    .withColumn("night_movement_score", F.least(F.lit(1.0), F.col("night_sightings_ratio") * 2))
    .withColumn("recent_pattern_score",
                F.least(F.lit(1.0), F.greatest(F.lit(0.0), F.col("recent_surge_ratio") - 1.0)))
    .withColumn("route_variance_score",
                F.least(F.lit(1.0), F.greatest(F.lit(0.0), (F.col("max_site_share") - 0.2) / 0.6)))
    .withColumn("mass_variance_score", F.least(F.lit(1.0), F.col("over_mass_ratio") * 2))
    .withColumn("defect_history_score",
                F.least(F.lit(1.0), (F.col("defect_count") + 2 * F.col("critical_defect_count")) / 8.0))
    .select(
        F.lit(RUN_TS).alias("run_ts"),
        F.lit(AS_OF).alias("as_of_date"),
        F.lit(FEATURE_WINDOW_DAYS).alias("window_days"),
        "asset_id", "registration_plate", "operator_id", "risk_cohort",
        "sightings_count", "night_sightings_ratio", "rest_window_ratio",
        "distinct_sites", "max_site_share", "over_mass_ratio", "max_mass_ratio",
        "mass_violation_count", "max_speed_kph", "recent_surge_ratio",
        "hours_since_last_seen",
        F.col("last_seen.event_ts").alias("last_seen_ts"),
        F.col("last_seen.road_name").alias("last_seen_road"),
        F.col("last_seen.locality").alias("last_seen_locality"),
        F.col("last_seen.site_id").alias("last_seen_site_id"),
        "rest_window_anomaly_score", "night_movement_score", "recent_pattern_score",
        "route_variance_score", "mass_variance_score", "defect_history_score",
    )
)

features.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.gold_asset_risk_features"
)

# COMMAND ----------

print(f"gold_asset_risk_features: {features.count()} sighted assets "
      f"over a {FEATURE_WINDOW_DAYS}-day window ending {AS_OF}")
features.select("registration_plate", "risk_cohort", "sightings_count",
                "night_sightings_ratio", "max_site_share", "over_mass_ratio") \
    .orderBy(F.desc("night_sightings_ratio")).show(10, truncate=False)
