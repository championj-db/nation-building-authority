# Databricks notebook source
# MAGIC %md
# MAGIC # Collect evidence - Automated Compliance Reporting
# MAGIC
# MAGIC 1. **Connector simulation** (synthetic only, `simulate_connectors=true`): lands every delivery due
# MAGIC    since the last run from `synthetic_evidence_plan` into the volume as JSON, one folder per
# MAGIC    delivery date and connector, plus the matching connector run telemetry. With
# MAGIC    `simulate_reviewers=true` it also lands synthetic human mapping reviews that have fallen due.
# MAGIC    In a real deployment the connectors write to the same landing path and this step is off.
# MAGIC 2. **Bronze**: Auto Loader (`availableNow`) ingests new landing files into the append-only
# MAGIC    `evidence_bronze`, recording the landing file path.
# MAGIC 3. **Silver**: `evidence_artefacts` (one row per document version, with `valid_from`/`valid_to`,
# MAGIC    recomputed checksum and integrity verdict) and `evidence_documents` (one row per document).
# MAGIC 4. **Audit**: `evidence.collected`, `evidence.integrity_failed` and `collection.source_failed` events.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "evidence")
dbutils.widgets.text("as_of_date", "")
dbutils.widgets.dropdown("simulate_connectors", "true", ["true", "false"])
dbutils.widgets.dropdown("simulate_reviewers", "true", ["true", "false"])

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
as_of_param = dbutils.widgets.get("as_of_date")
simulate_connectors = dbutils.widgets.get("simulate_connectors") == "true"
simulate_reviewers = dbutils.widgets.get("simulate_reviewers") == "true"

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

as_of = resolve_as_of(as_of_param)
print(f"as_of={as_of} simulate_connectors={simulate_connectors} simulate_reviewers={simulate_reviewers}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Connector simulation (synthetic)

# COMMAND ----------

WATERMARK = fqn("synthetic_landing_watermark")

if simulate_connectors and table_exists("synthetic_evidence_plan"):
    spark.sql(f"CREATE TABLE IF NOT EXISTS {WATERMARK} (landed_through DATE, updated_at TIMESTAMP) COMMENT 'Synthetic connector simulation progress.'")
    wm_row = spark.sql(f"SELECT max(landed_through) AS d FROM {WATERMARK}").first()
    watermark = wm_row["d"].isoformat() if wm_row and wm_row["d"] else "1900-01-01"
    window = (F.col("collection_date") > F.lit(watermark).cast("date")) & (F.col("collection_date") <= F.lit(as_of).cast("date"))

    due = spark.table(fqn("synthetic_evidence_plan")).filter(window)
    n_due = due.count()
    if n_due:
        (due.drop("collection_date")
            .withColumn("connector_source", F.col("source_id"))
            .write.mode("append").partitionBy("connector_source")
            .json(f"{LANDING_ROOT}/delivered_on={as_of}"))

    runs = (spark.table(fqn("synthetic_collection_runs_plan"))
            .filter((F.col("run_date") > F.lit(watermark).cast("date")) & (F.col("run_date") <= F.lit(as_of).cast("date"))))
    runs.select(*[f.name for f in spark.table(fqn("collection_runs")).schema.fields]).write.mode("append").saveAsTable(fqn("collection_runs"))

    n_reviews = 0
    if simulate_reviewers:
        reviews = (spark.table(fqn("synthetic_review_plan"))
                   .filter((F.col("reviewed_at") >= F.date_add(F.lit(watermark).cast("date"), 1).cast("timestamp"))
                           & (F.col("reviewed_at") < F.date_add(F.lit(as_of).cast("date"), 1).cast("timestamp"))))
        n_reviews = reviews.count()
        reviews.select(*[f.name for f in spark.table(fqn("mapping_reviews")).schema.fields]).write.mode("append").saveAsTable(fqn("mapping_reviews"))

    if as_of > watermark:
        spark.sql(f"INSERT INTO {WATERMARK} VALUES (DATE'{as_of}', current_timestamp())")
    print(f"landed deliveries={n_due} runs={runs.count()} reviews={n_reviews} window=({watermark}, {as_of}]")
else:
    print("Connector simulation disabled or no synthetic plan - ingesting whatever connectors have landed.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Bronze - Auto Loader

# COMMAND ----------

bronze_schema = spark.table(fqn("evidence_bronze")).drop("_landing_file", "_ingested_at").schema

query = (
    spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "json")
    .option("cloudFiles.includeExistingFiles", "true")
    .schema(bronze_schema)
    .load(LANDING_ROOT)
    .select("*", F.col("_metadata.file_path").alias("_landing_file"), F.current_timestamp().alias("_ingested_at"))
    .writeStream
    .option("checkpointLocation", f"{CHECKPOINT_ROOT}/evidence_bronze")
    .trigger(availableNow=True)
    .toTable(fqn("evidence_bronze"))
)
query.awaitTermination()
print(f"evidence_bronze rows: {spark.table(fqn('evidence_bronze')).count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Silver - versioned evidence
# MAGIC
# MAGIC Derived deterministically from the append-only bronze, so rebuilding it never changes history.
# MAGIC `checksum` is recomputed here and compared with the checksum the source system reported.

# COMMAND ----------

first_delivery = Window.partitionBy("evidence_id", "artefact_version").orderBy("_ingested_at", "record_id")
by_version = Window.partitionBy("evidence_id").orderBy("artefact_version")

artefacts = (
    spark.table(fqn("evidence_bronze"))
    .withColumn("_rn", F.row_number().over(first_delivery)).filter("_rn = 1").drop("_rn")
    .join(spark.table(fqn("source_systems")).select("source_id", "source_name"), "source_id", "left")
    .withColumn("checksum", F.sha2(F.concat_ws("|", "evidence_id", F.col("artefact_version").cast("string"), "content_excerpt"), 256))
    .withColumn("integrity_verified", F.col("checksum") == F.col("source_checksum"))
    .withColumn("is_acceptable", (F.col("approval_status") == "Approved") & F.col("integrity_verified"))
    .withColumn("valid_from", F.col("collected_at"))
    .withColumn("valid_to", F.lead("collected_at").over(by_version))
    .withColumn("is_latest_version", F.col("valid_to").isNull())
    .select(
        "evidence_id", "artefact_version", "source_id", "source_name", "connector", "title", "file_name", "file_format",
        "document_class", "approval_status", "signed", "source_modified_at", "collected_at", "checksum", "source_checksum",
        "integrity_verified", "is_acceptable", "content_excerpt", "size_bytes", "source_uri", "record_id",
        "valid_from", "valid_to", "is_latest_version", "_landing_file", "_ingested_at",
    )
)
artefacts.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fqn("evidence_artefacts"))
spark.sql(f"COMMENT ON TABLE {fqn('evidence_artefacts')} IS 'One row per evidence document version (valid_from/valid_to), with integrity verdict. Derived from evidence_bronze.'")

latest = Window.partitionBy("evidence_id").orderBy(F.desc("artefact_version"))
documents = (
    spark.table(fqn("evidence_artefacts"))
    .withColumn("first_collected_at", F.min("collected_at").over(Window.partitionBy("evidence_id")))
    .withColumn("version_count", F.count("*").over(Window.partitionBy("evidence_id")))
    .withColumn("_rn", F.row_number().over(latest)).filter("_rn = 1").drop("_rn")
    .select(
        "evidence_id", "source_id", "source_name", "connector", "title", "file_name", "file_format", "document_class",
        F.col("artefact_version").alias("latest_version"), "version_count", "first_collected_at",
        F.col("collected_at").alias("latest_collected_at"), F.col("source_modified_at").alias("latest_source_modified_at"),
        F.col("approval_status").alias("latest_approval_status"), "signed", F.col("checksum").alias("latest_checksum"),
        F.col("integrity_verified").alias("latest_integrity_verified"), "content_excerpt",
    )
)
documents.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fqn("evidence_documents"))
spark.sql(f"COMMENT ON TABLE {fqn('evidence_documents')} IS 'One row per evidence document (latest version attributes). Input to evidence mapping.'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Audit events

# COMMAND ----------

art = spark.table(fqn("evidence_artefacts"))
collected = audit_events_df(
    art, event_type="evidence.collected", entity_type="evidence", entity_id=F.col("evidence_id"),
    related_id=F.concat(F.lit("v"), F.col("artefact_version").cast("string")),
    summary=F.format_string("%s ingested %s v%d (%s) and recorded its source checksum", "connector", "evidence_id", "artefact_version", "title"),
    actor=F.col("connector"), occurred_at=F.col("collected_at"),
    payload=F.to_json(F.struct("title", "file_name", "source_checksum", "approval_status", "_landing_file")),
    dedup_key=F.format_string("evidence.collected|%s|%d", "evidence_id", "artefact_version"),
)
integrity = audit_events_df(
    art.filter(~F.col("integrity_verified")), event_type="evidence.integrity_failed", entity_type="evidence",
    entity_id=F.col("evidence_id"), related_id=F.concat(F.lit("v"), F.col("artefact_version").cast("string")),
    summary=F.format_string("Checksum mismatch on %s v%d: reported by source does not match content", "evidence_id", "artefact_version"),
    actor=F.lit("integrity.check"), occurred_at=F.col("_ingested_at"),
    payload=F.to_json(F.struct("checksum", "source_checksum")),
    dedup_key=F.format_string("evidence.integrity_failed|%s|%d", "evidence_id", "artefact_version"),
)
source_failed = audit_events_df(
    spark.table(fqn("collection_runs")).filter("status = 'Failed'"), event_type="collection.source_failed",
    entity_type="source", entity_id=F.col("source_id"), related_id=F.col("run_id"),
    summary=F.format_string("%s run failed: %s", "connector", "error_message"),
    actor=F.col("connector"), occurred_at=F.col("started_at"),
    payload=F.to_json(F.struct("run_date", "error_message")),
    dedup_key=F.format_string("collection.source_failed|%s", "run_id"),
)
print(f"audit events appended: {append_audit_events(collected.unionByName(integrity).unionByName(source_failed))}")

# COMMAND ----------

display(spark.sql(f"""
  SELECT source_name, count(DISTINCT evidence_id) AS documents, count(*) AS versions,
         sum(CASE WHEN NOT integrity_verified THEN 1 ELSE 0 END) AS integrity_failures,
         max(collected_at) AS last_collected_at
  FROM {fqn('evidence_artefacts')} GROUP BY source_name ORDER BY source_name"""))
