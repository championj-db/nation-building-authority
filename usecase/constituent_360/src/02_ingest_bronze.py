# Databricks notebook source
# MAGIC %md
# MAGIC # 02 Ingest bronze (Auto Loader)
# MAGIC
# MAGIC Each landing folder is ingested incrementally with Auto Loader (`availableNow`), so only new deliveries are
# MAGIC read on each run. Bronze keeps every source column as delivered (CSV as strings, no type inference), plus
# MAGIC file lineage: `_source_file`, `_delivery` (from the `delivery=` folder) and `_ingested_at`. Unexpected
# MAGIC columns land in `_rescued_data` instead of failing the stream.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("run_id", "")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
run_id = dbutils.widgets.get("run_id") or None

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

run_id = run_id or new_run_id("BRONZE")
summary = []
for extract, (fmt, kind) in EXTRACTS.items():
    src = f"{LANDING_ROOT}/{extract}"
    try:
        if not dbutils.fs.ls(src):
            continue
    except Exception:  # noqa: BLE001 - folder not landed yet
        print(f"skip {extract}: nothing landed")
        continue
    target = f"bronze_{extract}"
    assert_owned(target)  # never append into a same-named table this pipeline did not create
    reader = (spark.readStream.format("cloudFiles")
              .option("cloudFiles.format", fmt)
              .option("cloudFiles.schemaLocation", f"{SCHEMA_ROOT}/{target}")
              .option("cloudFiles.schemaEvolutionMode", "rescue")
              .option("cloudFiles.inferColumnTypes", "false"))
    if fmt == "csv":
        reader = reader.option("header", "true").option("multiLine", "true").option("escape", '"')
    stream = (reader.load(src)
              .withColumn("_source_file", F.col("_metadata.file_path"))
              .withColumn("_delivery", F.regexp_extract(F.col("_metadata.file_path"), r"delivery=([^/]+)", 1))
              .withColumn("_ingested_at", F.current_timestamp()))
    q = (stream.writeStream
         .option("checkpointLocation", f"{CHECKPOINT_ROOT}/{target}")
         .option("mergeSchema", "true")
         .trigger(availableNow=True)
         .toTable(table_name(target)))
    q.awaitTermination()
    claim_object(target)
    spark.sql(f"COMMENT ON TABLE {fqn(target)} IS {sql_str(f'Bronze: raw {kind} extract {extract} as delivered ({fmt}), with file lineage.')}")
    tag_table(target, {**BASE_TAGS, "nba_layer": "bronze",
                       "nba_classification": "sensitive" if extract == "community_health_clients" else "protected"})
    n = spark.table(table_name(target)).count()
    deliveries = spark.table(table_name(target)).select("_delivery").distinct().count()
    summary.append((target, n, deliveries))
    print(f"{target}: {n} rows across {deliveries} deliveries")

failed = record_checks("02_ingest_bronze", run_id, [
    (f"{t}_not_empty", n > 0, "critical", n, "> 0") for t, n, _ in summary
] + [("all_extracts_ingested", len(summary) == len(EXTRACTS), "warning", len(summary), len(EXTRACTS))])
assert not failed, f"critical checks failed: {failed}"
