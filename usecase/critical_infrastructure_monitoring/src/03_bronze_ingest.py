# Databricks notebook source
# Step 3 of the critical infrastructure monitoring pipeline: bronze ingest.
#
# Auto Loader incrementally streams the JSON telemetry files from the landing
# volume into the bronze table. The run uses a bounded (availableNow) trigger:
# each job run drains whatever new files have landed since the last run -
# the standard triggered-streaming pattern for scheduled pipelines. Because
# bronze is append-only and keyed by the file checkpoint, out-of-order and
# late-arriving events land exactly as they arrived; ordering is a silver
# concern.

# COMMAND ----------

import sys

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

from common import get_params, volume_dir

params = get_params(
    {
        "catalog": "",
        "schema": "",
        "volume": "landing",
    },
    dbutils,
)
if not params["catalog"] or not params["schema"] or not params["volume"]:
    raise ValueError("catalog, schema and volume parameters are required")

CATALOG = params["catalog"]
SCHEMA = params["schema"]
VOLUME = params["volume"]
LANDING_DIR = volume_dir(CATALOG, SCHEMA, VOLUME, "telemetry")
CHECKPOINT_DIR = volume_dir(CATALOG, SCHEMA, VOLUME, "checkpoints", "bronze")
BRONZE_TABLE = f"{CATALOG}.{SCHEMA}.bronze_sightings"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Source contract
# MAGIC The JSON schema is pinned explicitly rather than inferred, so a malformed
# MAGIC producer fails loudly at the boundary instead of silently shaping bronze.
# MAGIC Timestamps travel as epoch milliseconds - unambiguous across writers,
# MAGIC readers and timezones.

# COMMAND ----------

source_schema = T.StructType([
    T.StructField("sighting_id", T.StringType(), True),
    T.StructField("event_ts_epoch_ms", T.LongType(), True),
    T.StructField("hour_of_day", T.IntegerType(), True),
    T.StructField("sighted_plate_raw", T.StringType(), True),
    T.StructField("site_id", T.IntegerType(), True),
    T.StructField("road_name", T.StringType(), True),
    T.StructField("locality", T.StringType(), True),
    T.StructField("state", T.StringType(), True),
    T.StructField("latitude", T.DoubleType(), True),
    T.StructField("longitude", T.DoubleType(), True),
    T.StructField("heading", T.StringType(), True),
    T.StructField("source_type", T.StringType(), True),
    T.StructField("speed_kph", T.DoubleType(), True),
    T.StructField("axle_count_est", T.IntegerType(), True),
    T.StructField("mass_estimate_kg", T.LongType(), True),
])
# the persisted bronze table additionally carries ingest metadata
bronze_schema = source_schema.add(T.StructField("_ingest_ts", T.TimestampType(), True)) \
                            .add(T.StructField("_source_file", T.StringType(), True))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Ensure the bronze table exists
# MAGIC The streaming sink only creates the table when the first batch arrives;
# pre-creating it keeps an empty first run (no files yet) from breaking silver.

# COMMAND ----------

try:
    spark.table(BRONZE_TABLE)
except Exception:
    (spark.createDataFrame([], bronze_schema)
        .write
        .mode("overwrite")
        .saveAsTable(BRONZE_TABLE))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Drain new files
# MAGIC A bounded drain needs all four pieces: an append-capable sink, a durable
# MAGIC checkpoint, the availableNow trigger, and an awaited query that finishes
# MAGIC before the sink is verified.

# COMMAND ----------

raw = (
    spark.readStream
    .format("cloudFiles")
    .option("cloudFiles.format", "json")
    .schema(source_schema)
    .load(LANDING_DIR)
    .withColumn("_ingest_ts", F.current_timestamp())
    .withColumn("_source_file", F.col("_metadata.file_path"))
)

query = (
    raw.writeStream
    .format("delta")
    .option("checkpointLocation", CHECKPOINT_DIR)
    .trigger(availableNow=True)
    .toTable(BRONZE_TABLE)
)
query.awaitTermination()

# COMMAND ----------

bronze = spark.table(BRONZE_TABLE)
latest = bronze.agg(F.max("_ingest_ts").alias("latest_ingest")).collect()[0]["latest_ingest"]
print(f"bronze_sightings: {bronze.count()} total rows after this drain")
print(f"latest ingest timestamp: {latest}")
print(f"checkpoint: {CHECKPOINT_DIR}")
