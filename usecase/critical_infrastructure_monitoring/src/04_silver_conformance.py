# Databricks notebook source
# Step 4 of the critical infrastructure monitoring pipeline: silver conformance.
#
# Turns raw operator telemetry into trusted readings, and raw warnings into a current warnings
# table:
#   silver_reading             deduplicated, registered, physically plausible readings, conformed
#                              to the asset registry with their engineering limits and exceedance
#   silver_reading_quarantine  readings that failed a check, with the reason (unregistered sensor,
#                              implausible value) - kept, not dropped, so operators can be told
#   silver_hazard_warning      the latest version of each warning
#
# Silver is rebuilt from bronze each run for the current synthetic generation only (see
# common.generation_tag), so ordering and late arrival are resolved here, not at ingest.

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

from common import exceedance_expr, generation_tag, get_params, resolve_as_of, use_local_time

params = get_params({"catalog": "", "schema": "", "as_of": ""}, dbutils)
if not params["catalog"] or not params["schema"]:
    raise ValueError("catalog and schema parameters are required")

use_local_time(spark)
CATALOG, SCHEMA = params["catalog"], params["schema"]
GENERATION = generation_tag(resolve_as_of(params["as_of"]))


def table(name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{name}"


# COMMAND ----------

# MAGIC %md
# MAGIC ## Readings: current generation, deduplicated

# COMMAND ----------

raw = (
    spark.table(table("bronze_readings"))
    .filter(F.col("_source_file").contains(f"/{GENERATION}/"))
    .dropDuplicates(["reading_id"])
    .withColumn("event_ts", F.expr("timestamp_millis(event_ts_epoch_ms)"))
    .withColumn("arrival_ts", F.expr("timestamp_millis(arrival_ts_epoch_ms)"))
)
raw_count = raw.count()
if raw_count == 0:
    raise ValueError(f"No bronze readings for {GENERATION}; run generate_telemetry for this as_of first")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Conform to the registry and check plausibility
# MAGIC A reading is implausible when it sits more than five alarm bands from the sensor's
# MAGIC baseline - a stuck or spiking instrument, not a real condition. Those are quarantined, never
# MAGIC scored, because an alert on a broken sensor wastes a crew.

# COMMAND ----------

sensors = spark.table(table("dim_sensor"))
assets = spark.table(table("dim_asset")).select("asset_id", "asset_code", "asset_name", "asset_class", "sector", "state")

joined = raw.join(sensors, "sensor_id", "left")
checked = joined.withColumn(
    "quarantine_reason",
    F.expr(
        "CASE WHEN asset_id IS NULL THEN 'unregistered_sensor' "
        "WHEN abs(value - baseline) > 5 * abs(alarm_limit - baseline) THEN 'implausible_value' END"
    ),
)

quarantine = checked.filter("quarantine_reason IS NOT NULL").select(
    "reading_id", "sensor_id", "event_ts", "arrival_ts", "value", "metric", "quarantine_reason", "_source_file")
quarantine.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("silver_reading_quarantine"))

silver = (
    checked.filter("quarantine_reason IS NULL")
    .join(assets, "asset_id")
    .withColumn("exceedance", F.expr(exceedance_expr("metric", "value")))
    .withColumn("lateness_minutes", F.expr("round((unix_timestamp(arrival_ts) - unix_timestamp(event_ts)) / 60.0, 1)"))
    .select(
        "reading_id", "sensor_id", "asset_id", "asset_code", "asset_name", "asset_class", "sector", "state",
        "metric", "metric_label", "unit", "event_ts", "arrival_ts", "lateness_minutes", "value",
        "baseline", "warn_limit", "alarm_limit", "direction", "kind", "exceedance",
    )
)
silver.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("silver_reading"))

kept = spark.table(table("silver_reading")).count()
reasons = {r["quarantine_reason"]: r["count"] for r in spark.table(table("silver_reading_quarantine")).groupBy("quarantine_reason").count().collect()}
print(f"silver_reading: {kept:,} trusted readings of {raw_count:,} deduplicated ({kept / raw_count:.2%}); quarantined {reasons}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Hazard warnings: latest version of each

# COMMAND ----------

latest = Window.partitionBy("warning_id").orderBy(F.desc("_ingest_ts"))
warnings = (
    spark.table(table("bronze_hazard_warnings"))
    .filter(F.col("_source_file").contains(f"/{GENERATION}/"))
    .withColumn("rn", F.row_number().over(latest)).filter("rn = 1").drop("rn")
    .withColumn("valid_from", F.to_timestamp("valid_from"))
    .withColumn("valid_to", F.to_timestamp("valid_to"))
    .select("warning_id", "title", "hazard_type", "severity", "centre_lat", "centre_lon", "radius_km",
            "valid_from", "valid_to", "issuer")
)
warnings.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("silver_hazard_warning"))
print(f"silver_hazard_warning: {spark.table(table('silver_hazard_warning')).count()} warnings")
