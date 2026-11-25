# Databricks notebook source
# Step 3 of the critical infrastructure monitoring pipeline: bronze ingest.
#
# Auto Loader incrementally streams both landing feeds - operator telemetry and weather warnings -
# into append-only bronze tables. The run uses a bounded (availableNow) trigger: each job run
# drains whatever new files have landed since the last run, the standard triggered-streaming
# pattern for scheduled pipelines. Late and out-of-order readings land exactly as they arrived;
# ordering, deduplication and quality are silver concerns.

# COMMAND ----------

import os
import sys

from pyspark.sql import functions as F, types as T

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir")
_candidates = [_src, os.path.dirname(_src) if _src.endswith(".py") else None, "src", "."]
_src_dir = next((c for c in _candidates if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import get_params, volume_dir

params = get_params({"catalog": "", "schema": "", "volume": "landing"}, dbutils)
if not params["catalog"] or not params["schema"] or not params["volume"]:
    raise ValueError("catalog, schema and volume parameters are required")
CATALOG, SCHEMA, VOLUME = params["catalog"], params["schema"], params["volume"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## Source contracts
# MAGIC Schemas are pinned rather than inferred, so a malformed producer fails loudly at the
# MAGIC boundary instead of silently reshaping bronze. Reading timestamps travel as epoch
# MAGIC milliseconds - unambiguous across writers, readers and time zones.

# COMMAND ----------

FEEDS = {
    "telemetry": (
        "bronze_readings",
        T.StructType([
            T.StructField("reading_id", T.StringType()),
            T.StructField("sensor_id", T.StringType()),
            T.StructField("event_ts_epoch_ms", T.LongType()),
            T.StructField("arrival_ts_epoch_ms", T.LongType()),
            T.StructField("value", T.DoubleType()),
        ]),
    ),
    "hazards": (
        "bronze_hazard_warnings",
        T.StructType([
            T.StructField("warning_id", T.StringType()),
            T.StructField("title", T.StringType()),
            T.StructField("hazard_type", T.StringType()),
            T.StructField("severity", T.StringType()),
            T.StructField("centre_lat", T.DoubleType()),
            T.StructField("centre_lon", T.DoubleType()),
            T.StructField("radius_km", T.DoubleType()),
            T.StructField("valid_from", T.StringType()),
            T.StructField("valid_to", T.StringType()),
            T.StructField("issuer", T.StringType()),
        ]),
    ),
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Drain new files from each feed
# MAGIC A bounded drain needs four pieces: an append-capable sink, a durable checkpoint, the
# MAGIC availableNow trigger, and an awaited query that finishes before the sink is verified.

# COMMAND ----------

for feed, (table_name, schema) in FEEDS.items():
    target = f"{CATALOG}.{SCHEMA}.{table_name}"
    # pre-create so an empty first run (no files yet) cannot break silver; tableExists is eager
    if not spark.catalog.tableExists(target):
        bronze_schema = T.StructType(schema.fields + [
            T.StructField("_ingest_ts", T.TimestampType()), T.StructField("_source_file", T.StringType())])
        spark.createDataFrame([], bronze_schema).write.mode("overwrite").saveAsTable(target)

    query = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "json")
        # landing is split into generation=<tag> folders; keep them out of the pinned schema
        .option("cloudFiles.partitionColumns", "")
        .schema(schema)
        .load(volume_dir(CATALOG, SCHEMA, VOLUME, feed))
        .withColumn("_ingest_ts", F.current_timestamp())
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .writeStream.format("delta")
        .option("checkpointLocation", volume_dir(CATALOG, SCHEMA, VOLUME, "checkpoints", table_name))
        .trigger(availableNow=True)
        .toTable(target)
    )
    query.awaitTermination()
    stats = spark.table(target).agg(F.count("*").alias("rows"), F.max("_ingest_ts").alias("latest")).collect()[0]
    print(f"{table_name}: {stats['rows']:,} rows, latest ingest {stats['latest']}")
