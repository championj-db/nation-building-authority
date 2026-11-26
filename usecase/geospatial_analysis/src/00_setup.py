# Databricks notebook source
# Step 0 of the geospatial analysis pipeline: idempotent environment setup.
#
# Creates the schema, the landing volume, and the three officer write-back tables the Spatial
# Service Planner app records into (review notes, saved views, decision briefs). Those tables are
# CREATE IF NOT EXISTS so a pipeline re-run never discards an officer's work.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
VOLUME = dbutils.widgets.get("volume").strip()

if not CATALOG or not SCHEMA or not VOLUME:
    raise ValueError(
        "catalog, schema and volume parameters are required - pass the Unity Catalog location for "
        "this use case (the bundle does this via its variables)"
    )

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} COMMENT 'Geospatial analysis: access to essential services'")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME} COMMENT 'Raw public spatial data as fetched'")

t = lambda name: f"{CATALOG}.{SCHEMA}.{name}"  # noqa: E731

# Officer write-back. Rows are inserted by the app as the signed-in officer (on-behalf-of-user),
# with officer = current_user(), so the record says who did what without trusting the client.
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {t('app_review_note')} (
  note_id STRING NOT NULL,
  created_ts TIMESTAMP NOT NULL,
  officer STRING NOT NULL,
  service_type STRING NOT NULL,
  geo_level STRING NOT NULL,
  region_code STRING NOT NULL,
  region_name STRING,
  threshold_km INT,
  evidence_status STRING NOT NULL COMMENT 'needs_validation | ready_for_review | validated | no_action',
  next_step STRING,
  note STRING
) COMMENT 'Officer review notes on regions in the evidence queue (append-only; latest per region wins)'
""")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {t('app_saved_view')} (
  view_id STRING NOT NULL,
  created_ts TIMESTAMP NOT NULL,
  officer STRING NOT NULL,
  name STRING NOT NULL,
  settings STRING NOT NULL COMMENT 'JSON: service, geography, scope, threshold, display options, proposed sites',
  deleted BOOLEAN NOT NULL
) COMMENT 'Named analysis settings officers can return to and share'
""")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {t('app_brief')} (
  brief_id STRING NOT NULL,
  created_ts TIMESTAMP NOT NULL,
  officer STRING NOT NULL,
  title STRING NOT NULL,
  policy_question STRING NOT NULL,
  access_basis STRING NOT NULL,
  audience STRING NOT NULL,
  settings STRING NOT NULL COMMENT 'JSON of the analysis settings the brief was prepared from',
  findings STRING NOT NULL COMMENT 'JSON snapshot of the headline figures at preparation time',
  suppression_applied BOOLEAN NOT NULL,
  status STRING NOT NULL COMMENT 'draft | signed_off',
  signed_off_by STRING,
  signed_off_ts TIMESTAMP
) COMMENT 'Decision briefs: recorded purpose, findings snapshot and officer sign-off'
""")

print(f"Schema ready: {CATALOG}.{SCHEMA}")
print(f"Landing volume ready: /Volumes/{CATALOG}/{SCHEMA}/{VOLUME}")
