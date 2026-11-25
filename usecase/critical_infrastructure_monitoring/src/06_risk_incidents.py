# Databricks notebook source
# Step 6 of the critical infrastructure monitoring pipeline: risk, incidents and the operating
# picture.
#
# The risk engine is a transparent likelihood x consequence model, the vocabulary infrastructure
# operators already use:
#   likelihood = weighted sum of normalised factors (common.LIKELIHOOD_WEIGHTS)
#   risk       = 100 x likelihood x (floor + (1 - floor) x consequence)
# Every score resolves to the factors that produced it, and every incident carries a recommended
# first action and its downstream impact. This is decision support with a human in the loop: an
# officer decides whether to dispatch, notify the responsible operator, or keep monitoring.
#
# Writes gold_asset_risk, gold_incident (+ history, impact, review audit), gold_sector_status,
# gold_hazard_status and gold_ops_metrics.

# COMMAND ----------

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
    CONSEQUENCE_FLOOR, HAZARD_LABELS, INCIDENT_THRESHOLD, LIKELIHOOD_WEIGHTS, METRIC_INCIDENT,
    MODEL_VERSION, RISK_RATINGS, SECTOR_LABELS, get_params, local_now, timestamp_sql, use_local_time,
)

params = get_params({"catalog": "", "schema": "", "incident_threshold": INCIDENT_THRESHOLD}, dbutils)
if not params["catalog"] or not params["schema"]:
    raise ValueError("catalog and schema parameters are required")

use_local_time(spark)
CATALOG, SCHEMA = params["catalog"], params["schema"]
THRESHOLD = int(params["incident_threshold"])
RUN_TS = local_now()
RUN_SQL = timestamp_sql(RUN_TS)


def table(name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{name}"


def sql_case(column: str, mapping: dict, default: str = "NULL") -> str:
    """CASE expression mapping column values to string literals."""
    def lit(v: str) -> str:
        return "'" + v.replace("'", "''") + "'"
    return f"CASE {column} " + " ".join(f"WHEN {lit(k)} THEN {lit(v)}" for k, v in mapping.items()) + f" ELSE {default} END"


# COMMAND ----------

# MAGIC %md
# MAGIC ## Score every asset

# COMMAND ----------

likelihood_expr = " + ".join(f"{w} * {f}_score" for f, w in LIKELIHOOD_WEIGHTS.items())
dominant_expr = "CASE " + " ".join(
    "WHEN " + " AND ".join(f"{w} * {f}_score >= {w2} * {f2}_score" for f2, w2 in LIKELIHOOD_WEIGHTS.items() if f2 != f)
    + f" THEN '{f}'" for f, w in LIKELIHOOD_WEIGHTS.items()) + " END"
rating_expr = "CASE " + " ".join(f"WHEN risk_score >= {t} THEN '{r}'" for r, t in RISK_RATINGS) + " ELSE 'low' END"
priority_expr = "CASE " + " ".join(f"WHEN risk_score >= {t} THEN {i + 1}" for i, (_r, t) in enumerate(RISK_RATINGS)) + " ELSE 4 END"

operators = spark.table(table("dim_operator")).select("operator_id", "operator_name")
risk = (
    spark.table(table("gold_asset_features"))
    .join(operators, "operator_id", "left")
    .withColumn("likelihood", F.expr(likelihood_expr))
    .withColumn("consequence_multiplier", F.expr(f"{CONSEQUENCE_FLOOR} + {1 - CONSEQUENCE_FLOOR} * consequence_score"))
    .withColumn("risk_score", F.expr("cast(round(100 * likelihood * consequence_multiplier) as int)"))
    .withColumn("risk_rating", F.expr(rating_expr))
    .withColumn("priority", F.expr(priority_expr).cast("int"))
    .withColumn("dominant_factor", F.expr(dominant_expr))
    # what the incident is "about": the metric for sensor-led risk, else the hazard or condition
    .withColumn("trigger_key", F.expr(
        "CASE WHEN dominant_factor IN ('limit_exceedance', 'anomaly') AND trigger_metric IS NOT NULL THEN trigger_metric "
        "WHEN dominant_factor = 'hazard_exposure' THEN 'hazard' ELSE 'condition' END"))
    .withColumn("model_version", F.lit(MODEL_VERSION))
    .withColumn("incident_threshold", F.lit(THRESHOLD))
    .withColumn("run_ts", F.expr(RUN_SQL))
)
risk.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("gold_asset_risk"))
risk = spark.table(table("gold_asset_risk"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Incidents
# MAGIC Assets at or above the threshold become incidents. Identity is asset + trigger, so the same
# MAGIC condition persisting across runs is one incident with a stable first-seen time.

# COMMAND ----------

titles = {m: t for m, (t, _a) in METRIC_INCIDENT.items()}
actions = {m: a for m, (_t, a) in METRIC_INCIDENT.items()}
fmt_value = "format_number(trigger_value, CASE WHEN trigger_alarm_limit < 10 THEN 2 ELSE 0 END)"
fmt_alarm = "format_number(trigger_alarm_limit, CASE WHEN trigger_alarm_limit < 10 THEN 2 ELSE 0 END)"

run_incidents = (
    risk.filter(F.col("risk_score") >= THRESHOLD)
    .withColumn("incident_id", F.concat(F.col("asset_id").cast("string"), F.lit(":"), F.col("trigger_key")))
    .withColumn("incident_title", F.expr(
        "CASE WHEN trigger_key = 'hazard' THEN concat('In the path of a ', lower(" + sql_case("hazard_type", HAZARD_LABELS) + "), ' warning') "
        "WHEN trigger_key = 'condition' THEN 'Condition deteriorating' "
        f"ELSE {sql_case('trigger_key', titles)} END"))
    .withColumn("evidence_summary", F.expr(
        "concat_ws(' · ', "
        f"CASE WHEN trigger_metric IS NOT NULL THEN concat(trigger_metric_label, ' ', {fmt_value}, ' ', trigger_unit, "
        f"  ' (alarm ', {fmt_alarm}, ')') END, "
        "hazard_title, "
        "CASE WHEN inspection_overdue THEN concat('inspection overdue by ', days_since_inspection - 365, ' days') END)"))
    .withColumn("recommended_action", F.expr(
        "CASE WHEN trigger_key = 'hazard' THEN 'Pre-position crews and confirm the operator''s response plan' "
        "WHEN trigger_key = 'condition' THEN 'Bring the next inspection forward' "
        f"ELSE {sql_case('trigger_key', actions)} END"))
    .withColumn("impact_summary", F.expr(
        "CASE WHEN downstream_assets > 0 THEN concat('Supplies ', downstream_assets, ' asset', "
        "CASE WHEN downstream_assets = 1 THEN '' ELSE 's' END, ' across ', downstream_sector_list) END"))
    .withColumn("sector_label", F.expr(sql_case("sector", SECTOR_LABELS)))
)

run_incidents.select(
    "incident_id", F.expr(RUN_SQL).alias("run_ts"), "asset_id", "risk_score", "risk_rating",
).write.mode("append").saveAsTable(table("gold_incident_history"))

first_seen = spark.table(table("gold_incident_history")).groupBy("incident_id").agg(F.min("run_ts").alias("created_ts"))
incidents = (
    run_incidents.join(first_seen, "incident_id")
    .withColumn("age_minutes", F.expr(f"cast(round((unix_timestamp({RUN_SQL}) - unix_timestamp(created_ts)) / 60.0) as int)"))
    .withColumn("detected_lag_minutes", F.expr(
        f"round((unix_timestamp({RUN_SQL}) - unix_timestamp(trigger_value_ts)) / 60.0, 0)"))
    .select(
        "incident_id", "run_ts", "created_ts", "age_minutes", "asset_id", "asset_code", "asset_name",
        "asset_class", "asset_class_label", "sector", "sector_label", "operator_name", "locality", "state",
        "latitude", "longitude", "risk_score", "risk_rating", "priority", "likelihood", "consequence_score",
        "consequence_multiplier", "dominant_factor", "trigger_key", "incident_title", "evidence_summary",
        "recommended_action", "impact_summary", "limit_exceedance_score", "anomaly_score", "hazard_exposure_score",
        "condition_score", "trigger_metric", "trigger_metric_label", "trigger_unit", "trigger_value",
        "trigger_value_ts", "trigger_warn_limit", "trigger_alarm_limit", "trigger_direction",
        "hazard_warning_id", "hazard_title", "hazard_type", "hazard_severity", "condition_grade",
        "inspection_overdue", "people_served", "people_affected", "downstream_assets", "downstream_sectors",
        "detected_lag_minutes",
    )
)
incidents.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("gold_incident"))
incidents = spark.table(table("gold_incident"))

impact = (
    spark.table(table("gold_asset_dependency_impact"))
    .join(incidents.select("incident_id", "asset_id"), "asset_id")
    .join(risk.select(F.col("asset_id").alias("downstream_asset_id"), F.col("risk_score").alias("downstream_risk_score")),
          "downstream_asset_id", "left")
)
impact.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("gold_incident_impact"))

# Human-in-the-loop decision record. Created once, never truncated; the app writes to it.
spark.sql(f"""CREATE TABLE IF NOT EXISTS {table('gold_incident_review_audit')} (
  review_id string, incident_id string, reviewed_ts timestamp, officer_name string,
  disposition string, evidence_viewed string, notes string) USING DELTA""")
spark.sql(f"""COMMENT ON TABLE {table('gold_incident_review_audit')} IS
  'Human-in-the-loop decision record for incident reviews: officer, time, evidence viewed and disposition
   (dispatch / notify / monitor). Retained as the audit trail for every action taken on a risk score.'""")

print(f"gold_incident: {incidents.count()} open incidents at threshold {THRESHOLD}")
incidents.groupBy("sector", "risk_rating").count().orderBy("sector", "risk_rating").show(truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Operating picture: sectors, hazards and the feed

# COMMAND ----------

readings = spark.table(table("silver_reading"))
sensors_total = spark.table(table("dim_sensor")).count()

sector_status = (
    risk.groupBy("sector").agg(
        F.count("*").alias("assets"),
        F.sum(F.when(F.col("limit_exceedance_score") >= 0.7, 1).otherwise(0)).alias("assets_in_alarm"),
        F.sum(F.when(F.col("minutes_since_reading") > 60, 1).otherwise(0)).alias("assets_not_reporting"),
    )
    .join(incidents.groupBy("sector").agg(
        F.count("*").alias("open_incidents"),
        F.sum(F.when(F.col("priority") == 1, 1).otherwise(0)).alias("extreme_incidents"),
    ), "sector", "left")
    # Distinct downstream assets of the sector's incidents. People are deliberately not summed at
    # sector level: supply chains nest (a line's customers are its substations' customers), so any
    # total would double-count the same households.
    .join(impact.join(incidents.select("incident_id", F.col("sector").alias("incident_sector")), "incident_id")
          .groupBy(F.col("incident_sector").alias("sector"))
          .agg(F.countDistinct("downstream_asset_id").alias("dependants_at_risk")), "sector", "left")
    .fillna(0, subset=["open_incidents", "extreme_incidents", "dependants_at_risk"])
    .withColumn("sector_label", F.expr(sql_case("sector", SECTOR_LABELS)))
    .withColumn("run_ts", F.expr(RUN_SQL))
)
sector_status.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("gold_sector_status"))

active = spark.table(table("silver_hazard_warning")).filter(F.expr(f"valid_from <= {RUN_SQL} AND valid_to >= {RUN_SQL}"))
exposed = risk.filter("hazard_warning_id IS NOT NULL")
hazard_status = (
    active.join(
        exposed.groupBy(F.col("hazard_warning_id").alias("warning_id")).agg(
            F.count("*").alias("exposed_assets"),
            *[F.sum(F.when(F.col("sector") == s, 1).otherwise(0)).alias(f"exposed_{s}") for s in SECTOR_LABELS],
            F.sum("people_served").alias("people_in_zone"),
        ), "warning_id", "left")
    .join(incidents.filter("hazard_warning_id IS NOT NULL").groupBy(F.col("hazard_warning_id").alias("warning_id"))
          .agg(F.count("*").alias("linked_incidents")), "warning_id", "left")
    .fillna(0, subset=["exposed_assets", "people_in_zone", "linked_incidents"] + [f"exposed_{s}" for s in SECTOR_LABELS])
    .withColumn("hazard_label", F.expr(sql_case("hazard_type", HAZARD_LABELS)))
    .withColumn("hours_remaining", F.expr(f"round((unix_timestamp(valid_to) - unix_timestamp({RUN_SQL})) / 3600.0, 0)"))
    .withColumn("run_ts", F.expr(RUN_SQL))
)
hazard_status.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("gold_hazard_status"))

today_start = f"to_timestamp(to_date({RUN_SQL}))"
feed = readings.agg(
    F.sum(F.when(F.expr(f"event_ts >= {today_start}"), 1).otherwise(0)).alias("readings_today"),
    F.countDistinct(F.when(F.expr(f"arrival_ts >= {RUN_SQL} - INTERVAL 60 MINUTES"), F.col("sensor_id"))).alias("sensors_reporting"),
    F.expr("percentile(lateness_minutes, 0.5)").alias("median_lateness_minutes"),
    F.sum(F.when(F.col("lateness_minutes") > 60, 1).otherwise(0)).alias("late_readings"),
    F.max("event_ts").alias("latest_reading_ts"),
).collect()[0]
quarantined = spark.table(table("silver_reading_quarantine")).count()
total_readings = readings.count()
latest_ingest = spark.table(table("bronze_readings")).agg(F.max("_ingest_ts")).collect()[0][0]
inc = incidents.agg(
    F.count("*").alias("n"), F.sum(F.when(F.col("priority") == 1, 1).otherwise(0)).alias("p1"),
    F.expr("percentile(detected_lag_minutes, 0.5)").alias("lag"),
).collect()[0]

ops = spark.createDataFrame([(
    int(inc["n"] or 0), int(inc["p1"] or 0), int(feed["readings_today"] or 0), int(feed["sensors_reporting"] or 0),
    sensors_total, float(feed["median_lateness_minutes"] or 0), int(feed["late_readings"] or 0),
    float(quarantined / (total_readings + quarantined)) if total_readings else 0.0,
    float(inc["lag"] or 0), active.count(),
)], "open_incidents int, extreme_incidents int, readings_today long, sensors_reporting long, sensors_total long, "
    "median_lateness_minutes double, late_readings long, quarantine_rate double, median_detection_minutes double, "
    "active_hazards long") \
    .withColumn("run_ts", F.expr(RUN_SQL)) \
    .withColumn("latest_reading_ts", F.lit(feed["latest_reading_ts"]).cast("timestamp")) \
    .withColumn("latest_ingest_ts", F.lit(latest_ingest).cast("timestamp")) \
    .withColumn("model_version", F.lit(MODEL_VERSION))
ops.write.mode("append").option("mergeSchema", "true").saveAsTable(table("gold_ops_metrics"))
ops.show(truncate=False)
