# Databricks notebook source
# Step 5 of the critical infrastructure monitoring pipeline: gold risk features.
#
# One row per asset holding every normalised factor (0-1) the risk engine consumes, and the
# evidence behind each one, so a score is always explainable:
#   limit_exceedance  worst metric's movement from normal toward its engineering alarm limit
#   anomaly           deviation of the last two hours from the asset's own seven-day baseline
#   hazard_exposure   inside an active warning, by severity, sector relevance and proximity
#   condition         poor inspection grade (3-5), plus a penalty when the inspection is overdue
#   consequence       people relying on the asset and on everything downstream of it
# Also writes gold_asset_dependency_impact: the downstream assets (up to CASCADE_DEPTH hops) each
# asset supports, which the incident view uses to show what fails if this asset fails.

# COMMAND ----------

import os
import sys

from pyspark.sql import functions as F
from pyspark.sql.window import Window

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir")
_candidates = [_src, os.path.dirname(_src) if _src.endswith(".py") else None, "src", "."]
_src_dir = next((c for c in _candidates if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import (
    CASCADE_DEPTH, CONSEQUENCE_LOG_RANGE, HAZARD_RELEVANCE, SEVERITY_WEIGHT, get_params,
    haversine_km_expr, local_now, timestamp_sql, use_local_time,
)

params = get_params({"catalog": "", "schema": "", "recent_hours": 2, "baseline_days": 7}, dbutils)
if not params["catalog"] or not params["schema"]:
    raise ValueError("catalog and schema parameters are required")

use_local_time(spark)
CATALOG, SCHEMA = params["catalog"], params["schema"]
RECENT_HOURS = int(params["recent_hours"])
BASELINE_DAYS = int(params["baseline_days"])
RUN_TS = local_now()
RUN_SQL = timestamp_sql(RUN_TS)


def table(name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{name}"


readings = spark.table(table("silver_reading"))
assets = spark.table(table("dim_asset"))
sensors = spark.table(table("dim_sensor"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sensor evidence: recent window vs the asset's own baseline

# COMMAND ----------

recent_start = f"{RUN_SQL} - INTERVAL {RECENT_HOURS} HOURS"
per_sensor = (
    readings.filter(F.col("event_ts") >= F.expr(f"{RUN_SQL} - INTERVAL {BASELINE_DAYS} DAYS"))
    .withColumn("is_recent", F.expr(f"event_ts >= {recent_start}"))
    .groupBy("asset_id", "sensor_id", "metric", "metric_label", "unit", "direction", "warn_limit", "alarm_limit")
    .agg(
        F.avg(F.when(~F.col("is_recent"), F.col("value"))).alias("baseline_mean"),
        F.stddev(F.when(~F.col("is_recent"), F.col("value"))).alias("baseline_sd"),
        F.avg(F.when(F.col("is_recent"), F.col("value"))).alias("recent_mean"),
        F.max(F.when(F.col("is_recent"), F.col("exceedance"))).alias("recent_exceedance"),
        F.max(F.struct("event_ts", "value")).alias("latest"),
        F.max("arrival_ts").alias("last_arrival_ts"),
    )
    .withColumn("z", F.expr(
        "CASE WHEN direction = 'high' THEN 1 ELSE -1 END * (recent_mean - baseline_mean) / greatest(baseline_sd, 1e-6)"))
    .withColumn("anomaly", F.expr("least(1.0, greatest(0.0, (z - 2) / 4))"))
    .fillna(0.0, subset=["recent_exceedance", "anomaly"])
)

# the metric that drives the asset: highest exceedance, ties broken by anomaly
pick = Window.partitionBy("asset_id").orderBy(F.desc("recent_exceedance"), F.desc("anomaly"))
evidence = (
    per_sensor.withColumn("rn", F.row_number().over(pick)).filter("rn = 1")
    .select(
        "asset_id",
        F.col("recent_exceedance").alias("limit_exceedance_score"),
        F.col("metric").alias("trigger_metric"), F.col("metric_label").alias("trigger_metric_label"),
        F.col("unit").alias("trigger_unit"), F.col("latest.value").alias("trigger_value"),
        F.col("latest.event_ts").alias("trigger_value_ts"),
        F.col("warn_limit").alias("trigger_warn_limit"), F.col("alarm_limit").alias("trigger_alarm_limit"),
        F.col("direction").alias("trigger_direction"),
    )
    .join(per_sensor.groupBy("asset_id").agg(
        F.max("anomaly").alias("anomaly_score"),
        F.max("last_arrival_ts").alias("last_reading_ts"),
    ), "asset_id")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Hazard exposure (active warnings only)
# MAGIC Full exposure at the warning centre, half at its edge, zero outside it - scaled by severity
# MAGIC and by how strongly that hazard type bears on the asset's sector.

# COMMAND ----------

relevance = spark.createDataFrame(
    [(h, s, float(w)) for h, by_sector in HAZARD_RELEVANCE.items() for s, w in by_sector.items()],
    "hazard_type string, sector string, relevance double",
)
sev = spark.createDataFrame([(k, float(v)) for k, v in SEVERITY_WEIGHT.items()], "severity string, sev_w double")
active = spark.table(table("silver_hazard_warning")).filter(
    F.expr(f"valid_from <= {RUN_SQL} AND valid_to >= {RUN_SQL}"))

exposure_all = (
    assets.select("asset_id", "sector", "latitude", "longitude")
    .crossJoin(F.broadcast(active))
    .withColumn("dist_km", F.expr(haversine_km_expr("latitude", "longitude", "centre_lat", "centre_lon")))
    .filter("dist_km <= radius_km")
    .join(relevance, ["hazard_type", "sector"])
    .join(sev, "severity")
    .withColumn("exposure", F.expr("sev_w * relevance * (1 - 0.5 * dist_km / radius_km)"))
)
best_hazard = Window.partitionBy("asset_id").orderBy(F.desc("exposure"))
exposure = (
    exposure_all.withColumn("rn", F.row_number().over(best_hazard)).filter("rn = 1")
    .select("asset_id", F.col("exposure").alias("hazard_exposure_score"),
            F.col("warning_id").alias("hazard_warning_id"), F.col("title").alias("hazard_title"),
            "hazard_type", F.col("severity").alias("hazard_severity"),
            F.round("dist_km", 1).alias("hazard_distance_km"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Condition from inspections

# COMMAND ----------

latest_insp = Window.partitionBy("asset_id").orderBy(F.desc("inspection_date"))
condition = (
    spark.table(table("dim_inspection"))
    .withColumn("rn", F.row_number().over(latest_insp)).filter("rn = 1")
    .withColumn("days_since_inspection", F.expr(f"datediff(to_date({RUN_SQL}), inspection_date)"))
    .withColumn("inspection_overdue", F.expr("days_since_inspection > 365"))
    # grades 1-2 are serviceable (0); 3-5 rise to 1, so condition flags poor assets rather than
    # adding a little risk to everything
    .withColumn("condition_score", F.expr(
        "least(1.0, greatest(0.0, (condition_grade - 2) / 3.0) + CASE WHEN inspection_overdue THEN 0.2 ELSE 0.0 END)"))
    .select("asset_id", "condition_grade", "defect_count", F.col("inspection_date").alias("last_inspection_date"),
            "days_since_inspection", "inspection_overdue", "condition_score")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Consequence: who relies on this asset, including downstream
# MAGIC Walk the dependency graph up to CASCADE_DEPTH hops. People counts can overlap between
# MAGIC services (one household relies on power and water), so the total is "people relying on
# MAGIC dependent services", an upper bound used for prioritisation, not a census.

# COMMAND ----------

deps = spark.table(table("dim_dependency"))
hop = deps.select(F.col("upstream_asset_id").alias("root_asset_id"), F.col("downstream_asset_id").alias("asset_id"),
                  "dependency_type", F.lit(1).alias("hop"))
frontier, paths = hop, hop
for depth in range(2, CASCADE_DEPTH + 1):
    frontier = (
        frontier.alias("f").join(deps.alias("d"), F.col("f.asset_id") == F.col("d.upstream_asset_id"))
        .select(F.col("f.root_asset_id"), F.col("d.downstream_asset_id").alias("asset_id"),
                F.col("d.dependency_type"), F.lit(depth).alias("hop"))
    )
    paths = paths.unionByName(frontier)

first_hop = Window.partitionBy("root_asset_id", "asset_id").orderBy("hop")
impact = (
    paths.withColumn("rn", F.row_number().over(first_hop)).filter("rn = 1").drop("rn")
    .join(assets.select("asset_id", "asset_code", "asset_name", "asset_class_label", "sector", "locality",
                        "state", "latitude", "longitude", "people_served"), "asset_id")
    .withColumnRenamed("asset_id", "downstream_asset_id")
    .withColumnRenamed("root_asset_id", "asset_id")
)
impact.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("gold_asset_dependency_impact"))

downstream = impact.groupBy("asset_id").agg(
    F.count("*").alias("downstream_assets"),
    F.sum("people_served").alias("downstream_people"),
    F.countDistinct("sector").alias("downstream_sectors"),
    F.concat_ws(", ", F.array_sort(F.collect_set("sector"))).alias("downstream_sector_list"),
)

lo, hi = CONSEQUENCE_LOG_RANGE
features = (
    assets.join(evidence, "asset_id", "left")
    .join(exposure, "asset_id", "left")
    .join(condition, "asset_id", "left")
    .join(downstream, "asset_id", "left")
    .fillna(0.0, subset=["limit_exceedance_score", "anomaly_score", "hazard_exposure_score", "condition_score"])
    .fillna(0, subset=["downstream_assets", "downstream_people", "downstream_sectors"])
    .withColumn("people_affected", F.col("people_served") + F.col("downstream_people"))
    .withColumn("consequence_score", F.expr(
        f"least(1.0, greatest(0.0, (log10(greatest(people_affected, 1)) - {lo}) / {hi - lo}))"))
    .withColumn("minutes_since_reading", F.expr(
        f"round((unix_timestamp({RUN_SQL}) - unix_timestamp(last_reading_ts)) / 60.0, 0)"))
    .withColumn("run_ts", F.expr(RUN_SQL))
)
features.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("gold_asset_features"))

print(f"gold_asset_features: {spark.table(table('gold_asset_features')).count()} assets; "
      f"{active.count()} active warnings; {impact.count()} downstream dependency paths")
