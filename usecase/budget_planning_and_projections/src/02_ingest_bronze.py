# Databricks notebook source
# MAGIC %md
# MAGIC # 02 Ingest bronze (Auto Loader)
# MAGIC
# MAGIC Incrementally ingests every landed extract into a `bronze_<extract>` Delta table exactly as
# MAGIC delivered, plus lineage columns:
# MAGIC
# MAGIC * `_source_file` - the landing file the record came from
# MAGIC * `_delivery_date` / `period` - from the Hive-style landing folder
# MAGIC * `_ingested_at` - when the record entered the lakehouse
# MAGIC * `_rescued_data` - anything that did not fit the inferred schema (never silently dropped)
# MAGIC
# MAGIC CSV extracts are kept as strings in bronze; typing and validation happen in silver. Each stream
# MAGIC runs with `availableNow`, so the task is a batch-style incremental load on serverless.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

# extract -> (format, partition column in the landing path)
EXTRACTS = {
    "programs": ("csv", "delivery_date"),
    "projects": ("csv", "delivery_date"),
    "plan_versions": ("csv", "delivery_date"),
    "plan_phasing": ("csv", "delivery_date"),
    "gl_transactions": ("csv", "period"),
    "suppliers": ("csv", "delivery_date"),
    "change_register": ("json", "delivery_date"),
    "gateway_reviews": ("json", "delivery_date"),
    "assumptions_register": ("json", "delivery_date"),
    "escalation_rates": ("csv", "delivery_date"),
    "price_deflator": ("csv", "delivery_date"),
    "funding_envelope": ("csv", "delivery_date"),
    "capacity_categories": ("csv", "delivery_date"),
    "market_capacity": ("csv", "delivery_date"),
    "demand_intensity": ("csv", "delivery_date"),
    "scenario_definitions": ("json", "delivery_date"),
    "scenario_levers": ("json", "delivery_date"),
}

existing = {f.name.rstrip("/") for f in dbutils.fs.ls(LANDING_ROOT)}
summary = []
for extract, (fmt, part_col) in EXTRACTS.items():
    if extract not in existing:
        print(f"skip {extract}: nothing landed yet")
        continue
    reader = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", fmt)
        .option("cloudFiles.schemaLocation", f"{CHECKPOINT_ROOT}/bronze_{extract}/_schema")
        .option("cloudFiles.partitionColumns", part_col)
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        .option("rescuedDataColumn", "_rescued_data")
    )
    if fmt == "csv":
        reader = reader.option("header", "true").option("cloudFiles.inferColumnTypes", "false")
    else:
        reader = reader.option("cloudFiles.inferColumnTypes", "true")
    stream = (
        reader.load(f"{LANDING_ROOT}/{extract}")
        .withColumn("_source_file", F.col("_metadata.file_path"))
        .withColumn("_ingested_at", F.current_timestamp())
    )
    if part_col == "delivery_date":
        stream = stream.withColumnRenamed("delivery_date", "_delivery_date")
    before = spark.table(table_name(f"bronze_{extract}")).count() if table_exists(f"bronze_{extract}") else 0
    query = (
        stream.writeStream
        .option("checkpointLocation", f"{CHECKPOINT_ROOT}/bronze_{extract}")
        .option("mergeSchema", "true")
        .trigger(availableNow=True)
        .toTable(table_name(f"bronze_{extract}"))
    )
    query.awaitTermination()
    rows = spark.table(table_name(f"bronze_{extract}")).count() - before
    summary.append((extract, rows))
    print(f"bronze_{extract:<22} +{rows:>8} rows")

# COMMAND ----------

for extract, _ in summary:
    spark.sql(f"COMMENT ON TABLE {fqn('bronze_' + extract)} IS "
              f"{sql_str(f'Bronze: raw {extract} extract as delivered to the landing volume (synthetic). Lineage in _source_file / _ingested_at.')}")
    tag_table(f"bronze_{extract}", {**BASE_TAGS, "nba_layer": "bronze"})
print(f"Ingested {sum(r for _, r in summary):,} new records across {len(summary)} extracts")
