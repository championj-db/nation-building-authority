# Databricks notebook source
# Step 6 of the critical infrastructure monitoring pipeline: risk scoring,
# alerting and operational metrics.
#
# The scoring engine is deliberately transparent: per-entity scores are a
# weighted sum of normalised factors, so every score resolves to contributing
# factors an officer can read, and every alert carries a recommended action
# and a decision record. This is decision support with a human in the loop,
# not automated enforcement (see the use case README's assurance notes).

# COMMAND ----------

import datetime as dt
import sys

from pyspark.sql import functions as F

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
    ALERT_COPY, FACTOR_WEIGHTS, MODEL_VERSION, RISK_TYPES,
    SEVERITY_BANDS, get_params, resolve_as_of,
)

params = get_params(
    {
        "catalog": "",
        "schema": "",
        "as_of": "",
        "alert_threshold": 70,
    },
    dbutils,
)
if not params["catalog"] or not params["schema"]:
    raise ValueError("catalog and schema parameters are required")

CATALOG = params["catalog"]
SCHEMA = params["schema"]
AS_OF = resolve_as_of(params["as_of"])
ALERT_THRESHOLD = int(params["alert_threshold"])
RUN_TS = dt.datetime.now()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Score every sighted entity
# MAGIC Each risk type applies its own weight vector to the same factors; an
# MAGIC entity's risk type is the vector that scores highest, and the primary
# MAGIC factor is the largest weighted contributor within it. Risk is discovered
# MAGIC from telemetry - the synthetic generator's cohort labels never feed in.

# COMMAND ----------

features = spark.table(f"{CATALOG}.{SCHEMA}.gold_asset_risk_features")
operators = spark.table(f"{CATALOG}.{SCHEMA}.dim_operator")


def weighted_sum_expr(risk_type: str) -> str:
    return " + ".join(
        f"{weight} * {factor}_score"
        for factor, weight in FACTOR_WEIGHTS[risk_type].items()
    )


def argmax_factor_expr(risk_type: str) -> str:
    """CASE expression naming the factor with the largest weighted value."""
    weighted = [
        (factor, f"{weight} * {factor}_score")
        for factor, weight in FACTOR_WEIGHTS[risk_type].items()
    ]
    cases = []
    for factor, value in weighted:
        guards = " AND ".join(f"{value} >= {other_value}" for _, other_value in weighted)
        cases.append(f"WHEN {guards} THEN '{factor}'")
    return "CASE " + " ".join(cases) + f" ELSE '{weighted[0][0]}' END"


scores = features
for risk_type in RISK_TYPES:
    scores = scores.withColumn(f"score_{risk_type}", F.expr(weighted_sum_expr(risk_type)))

score_cols = [f"score_{t}" for t in RISK_TYPES]
greatest_expr = "greatest(" + ", ".join(score_cols) + ")"
type_case = "CASE " + " ".join(
    f"WHEN score_{t} = {greatest_expr} THEN '{t}'" for t in RISK_TYPES
) + " END"
primary_case = "CASE " + " ".join(
    f"WHEN score_{t} = {greatest_expr} THEN ({argmax_factor_expr(t)})" for t in RISK_TYPES
) + " END"

scores = (
    scores
    .withColumn("risk_type", F.expr(type_case))
    .withColumn("primary_factor", F.expr(primary_case))
    .withColumn("risk_score", F.expr(f"round(100 * {greatest_expr})").cast("int"))
    .withColumn("recommended_action", F.expr(
        f"CASE WHEN risk_score >= {ALERT_THRESHOLD} "
        "THEN 'Route to field queue' ELSE 'Continue monitoring' END"
    ))
)

scored = (
    scores
    .join(
        operators.select(F.col("operator_id").alias("op_operator_id"), "operator_name"),
        F.col("operator_id") == F.col("op_operator_id"),
    )
    .select(
        F.lit(RUN_TS).alias("run_ts"),
        F.lit(AS_OF).alias("as_of_date"),
        F.lit(MODEL_VERSION).alias("model_version"),
        "asset_id", "registration_plate", "operator_id", "operator_name",
        "risk_type", "primary_factor", "risk_score", "recommended_action",
        F.lit(ALERT_THRESHOLD).alias("alert_threshold"),
        "rest_window_anomaly_score", "night_movement_score", "recent_pattern_score",
        "route_variance_score", "mass_variance_score", "defect_history_score",
        "sightings_count", "hours_since_last_seen",
        "last_seen_ts", "last_seen_road", "last_seen_locality",
    )
)

scored.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.gold_asset_risk_score"
)
print(f"gold_asset_risk_score: {scored.count()} entities scored with {MODEL_VERSION}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Alert queue
# MAGIC Assets scoring above the threshold enter the field queue, exactly as in
# MAGIC the operations-centre design: severity band, priority, last-seen context
# MAGIC and the alert copy for each risk type. History is appended per run so
# MAGIC queue age ("oldest open alert") survives across runs.

# COMMAND ----------

critical_band = SEVERITY_BANDS["critical"]
high_band = SEVERITY_BANDS["high"]

alerting = scored.filter(F.col("risk_score") >= ALERT_THRESHOLD)

run_alerts = (
    alerting
    .withColumn("alert_id", F.concat(F.col("asset_id").cast("string"), F.lit(":"), "risk_type"))
    .withColumn("severity", F.expr(
        f"CASE WHEN risk_score >= {critical_band} THEN 'critical' "
        f"WHEN risk_score >= {high_band} THEN 'high' ELSE 'medium' END"
    ))
    .withColumn("priority", F.expr(
        f"CASE WHEN risk_score >= {critical_band} THEN 1 "
        f"WHEN risk_score >= {high_band} THEN 2 ELSE 3 END"
    ).cast("int"))
    .withColumn("last_seen_location", F.concat(
        F.col("last_seen_road"), F.lit(", "), F.col("last_seen_locality")
    ))
    .withColumn("alert_title", F.expr(
        "CASE " + " ".join(
            f"WHEN risk_type = '{t}' THEN '{title}'" for t, (title, _) in ALERT_COPY.items()
        ) + " END"
    ))
    .withColumn("alert_summary", F.expr(
        "CASE " + " ".join(
            f"WHEN risk_type = '{t}' THEN '{summary}'" for t, (_, summary) in ALERT_COPY.items()
        ) + " END"
    ))
    .select(
        "alert_id", F.lit(RUN_TS).alias("run_ts"), "asset_id", "registration_plate",
        "operator_id", "operator_name", "risk_type", "primary_factor",
        "risk_score", "severity", "priority", "alert_title", "alert_summary",
        "recommended_action", "last_seen_ts", "last_seen_location",
    )
)

# history first, so first-seen timestamps include this run
(run_alerts.write.mode("append").saveAsTable(f"{CATALOG}.{SCHEMA}.gold_alert_history"))

first_seen = (
    spark.table(f"{CATALOG}.{SCHEMA}.gold_alert_history")
    .groupBy("alert_id")
    .agg(F.min("run_ts").alias("created_ts"))
)

run_ts_lit = RUN_TS.isoformat(sep=" ")
current_alerts = (
    run_alerts
    .join(first_seen, "alert_id")
    .withColumn("status", F.lit("open"))
    .withColumn("age_minutes", F.expr(
        f"round((unix_timestamp('{run_ts_lit}') - unix_timestamp(created_ts)) / 60.0, 0)"
    ).cast("int"))
    .select(
        "alert_id", "run_ts", "created_ts", "age_minutes", "status", "asset_id",
        "registration_plate", "operator_name", "risk_type", "primary_factor",
        "risk_score", "severity", "priority", "alert_title", "alert_summary",
        "recommended_action", "last_seen_ts", "last_seen_location",
    )
)

current_alerts.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.gold_alert"
)
print(f"gold_alert: {current_alerts.count()} open alerts at threshold {ALERT_THRESHOLD}")
current_alerts.select("registration_plate", "operator_name", "alert_title",
                     "last_seen_location", "risk_score", "severity").show(10, truncate=False)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Decision audit record
# MAGIC The assurance design: whoever reviews an alert, what evidence they viewed
# MAGIC and the disposition they recorded is retained. The table is created empty
# MAGIC here; the operations UI writes to it when an officer decides.

# COMMAND ----------

AUDIT_TABLE = f"{CATALOG}.{SCHEMA}.gold_alert_review_audit"
try:
    spark.table(AUDIT_TABLE)
except Exception:
    spark.sql(
        f"CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} ("
        "review_id string, alert_id string, reviewed_ts timestamp, "
        "officer_name string, disposition string, evidence_viewed string, notes string"
        ") USING DELTA"
    )
spark.sql(
    f"COMMENT ON TABLE {AUDIT_TABLE} IS '"
    "Human-in-the-loop decision record for alert reviews: officer, time, evidence "
    "viewed and disposition (route/monitor). Retained as the audit trail required "
    "before any risk score may direct enforcement attention at an identified operator."
    "'"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Operational metrics and risk-signal trend
# MAGIC The headline numbers on the operations dashboard: open alerts, sightings
# MAGIC today, identity-resolution rate, median signal-to-review lag and the
# MAGIC 8-hour risk-signal count, plus an hourly trend for the last 24 hours.

# COMMAND ----------

silver = spark.table(f"{CATALOG}.{SCHEMA}.silver_sighting")
quarantine = spark.table(f"{CATALOG}.{SCHEMA}.silver_sighting_quarantine")

resolved_count = silver.filter(F.col("asset_id").isNotNull()).count()
total_count = resolved_count + quarantine.count()

sightings_today = silver.filter(
    F.col("event_ts") >= F.lit(AS_OF).cast("date")
).count()

alert_asset_ids = run_alerts.select("asset_id").distinct()
risk_signals_8h = (
    silver
    .filter(F.col("event_ts") >= F.expr(
        f"timestamp '{run_ts_lit}' - INTERVAL 8 HOUR"))
    .join(alert_asset_ids, "asset_id")
    .count()
)

queue_minutes_expr = (
    f"percentile(round((unix_timestamp('{run_ts_lit}') - unix_timestamp(last_seen_ts)) / 60.0), 0.5)"
)
metrics_row = (
    current_alerts.agg(
        F.count("*").alias("open_alerts"),
        F.expr(queue_minutes_expr).alias("median_queue_time_minutes"),
    )
    .withColumn("run_ts", F.lit(RUN_TS))
    .withColumn("as_of_date", F.lit(AS_OF).cast("date"))
    .withColumn("sightings_today", F.lit(sightings_today).cast("long"))
    .withColumn("identity_resolution_rate", F.lit(
        resolved_count / total_count if total_count else 0.0
    ))
    .withColumn("risk_signals_last_8h", F.lit(risk_signals_8h).cast("long"))
    .select("run_ts", "as_of_date", "open_alerts", "sightings_today",
            "identity_resolution_rate", "median_queue_time_minutes", "risk_signals_last_8h")
)
metrics_row.write.mode("append").saveAsTable(f"{CATALOG}.{SCHEMA}.gold_ops_metrics")

signal_trend = (
    silver
    .filter(F.col("event_ts") >= F.expr(
        f"timestamp '{run_ts_lit}' - INTERVAL 24 HOUR"))
    .join(alert_asset_ids, "asset_id")
    .groupBy(F.date_trunc("hour", F.col("event_ts")).alias("hour_ts"))
    .agg(F.count("*").alias("risk_sightings"))
    .orderBy("hour_ts")
)
signal_trend.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.gold_risk_signal_trend"
)

metrics_row.show(truncate=False)
print(f"risk signal trend: {signal_trend.count()} hourly buckets in the last 24 hours")

# COMMAND ----------

print("Pipeline complete. Gold tables: gold_asset_risk_features, "
      "gold_asset_risk_score, gold_alert, gold_alert_history, "
      "gold_alert_review_audit, gold_ops_metrics, gold_risk_signal_trend")
