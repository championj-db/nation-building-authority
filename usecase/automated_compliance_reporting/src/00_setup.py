# Databricks notebook source
# MAGIC %md
# MAGIC # Setup - Automated Compliance Reporting
# MAGIC
# MAGIC Creates the schema, the evidence volume and every **append-only** table with its governed
# MAGIC contract. Append-only tables carry `delta.appendOnly = true` (UPDATE/DELETE/MERGE rejected),
# MAGIC Change Data Feed, and long log/file retention so Delta time travel can back point-in-time
# MAGIC report reproduction for the configured retention period.
# MAGIC
# MAGIC `reset=true` drops every table in the use case schema and clears the volume. It exists only
# MAGIC so the synthetic demo can be rebuilt from scratch; it defaults to `false`.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "evidence")
dbutils.widgets.text("history_retention_days", "2555")
dbutils.widgets.dropdown("reset", "false", ["false", "true"])

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
retention_days = int(dbutils.widgets.get("history_retention_days"))
reset = dbutils.widgets.get("reset") == "true"

assert catalog, "catalog parameter is required"
assert schema, "schema parameter is required"
print(f"catalog={catalog} schema={schema} volume={volume} retention={retention_days}d reset={reset}")

# COMMAND ----------

# The catalog is a pre-provisioned prerequisite supplied via the bundle `catalog` variable.
# Don't create it here: workspaces without a metastore storage root reject CREATE CATALOG.
assert spark.sql(f"SHOW CATALOGS LIKE '{catalog}'").count() == 1, (
    f"Catalog '{catalog}' not found or not accessible - create it first or set the `catalog` bundle variable"
)
spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}` COMMENT 'Automated Compliance Reporting (synthetic). Obligation register, evidence, mapping, coverage, reports and immutable audit trail.'")
spark.sql(f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{schema}`.`{volume}` COMMENT 'Evidence landing zone, Auto Loader checkpoints and generated report packages.'")

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

if reset:
    for row in spark.sql(f"SHOW VIEWS IN `{catalog}`.`{schema}`").collect():
        spark.sql(f"DROP VIEW IF EXISTS {fqn(row['viewName'])}")
    for row in spark.sql(f"SHOW TABLES IN `{catalog}`.`{schema}`").collect():
        if not row["isTemporary"]:
            spark.sql(f"DROP TABLE IF EXISTS {fqn(row['tableName'])}")
    for sub in ("landing", "_checkpoints", "reports"):
        try:
            dbutils.fs.rm(f"{VOLUME_ROOT}/{sub}", recurse=True)
        except Exception as exc:  # noqa: BLE001 - directory may not exist yet
            print(f"skip {sub}: {exc.__class__.__name__}")
    print("Reset complete")

for sub in ("landing", "_checkpoints", "reports"):
    dbutils.fs.mkdirs(f"{VOLUME_ROOT}/{sub}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Append-only tables

# COMMAND ----------

APPEND_ONLY = f"""TBLPROPERTIES (
  'delta.appendOnly' = 'true',
  'delta.enableChangeDataFeed' = 'true',
  'delta.logRetentionDuration' = 'interval {retention_days} days',
  'delta.deletedFileRetentionDuration' = 'interval {retention_days} days'
)"""

TABLES = {
    "audit_events": (
        """event_seq BIGINT NOT NULL COMMENT 'Monotonic position in the hash chain',
           event_id STRING NOT NULL, event_type STRING NOT NULL, entity_type STRING NOT NULL,
           entity_id STRING, related_id STRING, summary STRING, actor STRING,
           occurred_at TIMESTAMP COMMENT 'Business time of the fact (UTC)',
           recorded_at TIMESTAMP COMMENT 'Time the event entered the trail (UTC)',
           payload STRING COMMENT 'JSON detail', dedup_key STRING NOT NULL COMMENT 'Stable identity of the fact; makes emission idempotent',
           canonical STRING NOT NULL COMMENT 'Canonical serialisation that is hashed',
           prev_hash STRING NOT NULL, event_hash STRING NOT NULL COMMENT 'sha256(prev_hash || canonical)'""",
        "Immutable, hash-chained audit trail of register, evidence, mapping, alert and report events.",
    ),
    "evidence_bronze": (
        """record_id STRING, source_id STRING, connector STRING, evidence_id STRING, artefact_version INT,
           title STRING, file_name STRING, file_format STRING, document_class STRING, approval_status STRING,
           signed BOOLEAN, source_modified_at TIMESTAMP, collected_at TIMESTAMP, source_checksum STRING,
           content_excerpt STRING, size_bytes BIGINT, source_uri STRING,
           _landing_file STRING, _ingested_at TIMESTAMP""",
        "Raw evidence collection records exactly as delivered by source-system connectors (Auto Loader).",
    ),
    "collection_runs": (
        """run_id STRING, source_id STRING, connector STRING, run_date DATE, started_at TIMESTAMP,
           status STRING, records_collected INT, error_message STRING""",
        "Connector run telemetry; drives source health and SOURCE_OFFLINE alerts.",
    ),
    "mapping_reviews": (
        """review_id STRING, evidence_id STRING, decision STRING COMMENT 'confirm | reject',
           artefact_type STRING COMMENT 'Confirmed artefact type (null when rejected)', reviewer STRING,
           reviewed_at TIMESTAMP, comment STRING, channel STRING COMMENT 'synthetic | app'""",
        "Human evidence-mapping decisions. Highest-precedence mapping source. Written by the app (OBO) and the synthetic reviewer.",
    ),
    "mapping_ai_suggestions": (
        """suggestion_id STRING, evidence_id STRING, artefact_type STRING COMMENT 'Suggested type or NONE',
           confidence DOUBLE, rationale STRING, candidate_types ARRAY<STRING>, model_endpoint STRING,
           prompt_version STRING, suggested_at TIMESTAMP, run_id STRING""",
        "AI-suggested evidence classifications. Recommendations only: never counted as coverage until a human confirms.",
    ),
    "mapping_evaluation": (
        """run_id STRING, evaluated_at TIMESTAMP, method STRING, labelled_items BIGINT, correct BIGINT,
           accuracy DOUBLE, false_maps BIGINT COMMENT 'Mapped to a type when the label says not evidence',
           missed BIGINT COMMENT 'Said not evidence when the label has a type', notes STRING""",
        "Mapping accuracy against the labelled evaluation set (evidence_labels).",
    ),
    "compliance_reports": (
        """report_id STRING, report_type STRING, title STRING, gate_id STRING, as_of_date DATE,
           register_fingerprint STRING, register_version_label STRING, evidence_snapshot_id STRING,
           template_version STRING, report_version INT, obligations_in_scope INT, obligations_complete INT,
           obligations_expiring INT, obligations_gap INT, evidence_items INT, findings_digest STRING,
           executive_summary STRING, summary_ai_generated BOOLEAN, model_endpoint STRING, prompt_version STRING,
           table_versions STRING, output_path STRING, generated_at TIMESTAMP, generated_by STRING""",
        "Generated compliance reports. Each row is immutable; status lives in report_status_events.",
    ),
    "report_findings": (
        """report_id STRING, obligation_id STRING, obligation_version INT, obligation_title STRING, gate_id STRING,
           owner_role STRING, requirement_id STRING, artefact_type STRING, status STRING, gap_reason STRING,
           evidence_id STRING, artefact_version INT, checksum STRING, evidence_modified_on DATE,
           expires_on DATE, days_to_expiry INT""",
        "Requirement-level findings exactly as reported.",
    ),
    "evidence_snapshots": (
        """snapshot_id STRING, report_id STRING, evidence_id STRING, artefact_version INT, title STRING,
           source_id STRING, checksum STRING, source_modified_at TIMESTAMP, collected_at TIMESTAMP, captured_at TIMESTAMP""",
        "Evidence manifest captured for each report (versions and checksums relied upon).",
    ),
    "report_status_events": (
        """report_id STRING, status STRING COMMENT 'Draft | Ready for approval | Issued | Withdrawn',
           changed_by STRING, changed_at TIMESTAMP, comment STRING""",
        "Report lifecycle transitions. Current status = latest event.",
    ),
    "report_reproductions": (
        """reproduction_id STRING, report_id STRING, reproduced_at TIMESTAMP, original_digest STRING,
           reproduced_digest STRING, matches BOOLEAN, reproduced_by STRING""",
        "Results of regenerating a past report from point-in-time inputs.",
    ),
    "audit_chain_verifications": (
        """verification_id STRING, verified_at TIMESTAMP, events_checked BIGINT, head_seq BIGINT, head_hash STRING,
           status STRING, first_broken_seq BIGINT, detail STRING""",
        "Results of recomputing the audit hash chain.",
    ),
}

for name, (columns, comment) in TABLES.items():
    spark.sql(f"CREATE TABLE IF NOT EXISTS {fqn(name)} ({columns}) USING DELTA COMMENT '{comment}' {APPEND_ONLY}")
    print(f"ready: {name}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify

# COMMAND ----------

props = spark.sql(f"SHOW TBLPROPERTIES {fqn('audit_events')}").filter("key LIKE 'delta.%'")
display(props)
assert props.filter("key = 'delta.appendOnly' AND value = 'true'").count() == 1
