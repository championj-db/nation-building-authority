# Databricks notebook source
# MAGIC %md
# MAGIC # 00 Setup - Budget Planning & Financial Projections
# MAGIC
# MAGIC Creates the use case schema, the landing volume, and the tables whose contract must exist
# MAGIC before any data arrives:
# MAGIC
# MAGIC | Table | Purpose |
# MAGIC | --- | --- |
# MAGIC | `pipeline_control` | Synthetic world anchor, seed and landing watermarks |
# MAGIC | `scenario_definitions`, `scenario_levers` | Scenario inputs **as data**. Seeded by the pipeline; the application will insert user drafts here |
# MAGIC | `forecast_runs` | Append-only register of every forecast run and the assumption versions it used |
# MAGIC | `dq_results` | Append-only data-quality results per run |
# MAGIC | `scenario_events`, `forecast_submissions`, `variance_commentary`, `assurance_actions`, `briefing_packs` | Append-only workflow records written by the application (latest event = current state) |
# MAGIC
# MAGIC `reset=true` drops every table in the schema and clears the volume so the synthetic demo can be
# MAGIC rebuilt from scratch. It defaults to `false`.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.dropdown("reset", "false", ["false", "true"])

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
reset = dbutils.widgets.get("reset") == "true"

assert catalog, "catalog parameter is required"
assert schema, "schema parameter is required"
print(f"catalog={catalog} schema={schema} volume={volume} reset={reset}")

# COMMAND ----------

# The catalog is a pre-provisioned prerequisite supplied via the bundle `catalog` variable.
# It is not created here: workspaces without a metastore storage root reject CREATE CATALOG.
assert spark.sql(f"SHOW CATALOGS LIKE '{catalog}'").count() == 1, (
    f"Catalog '{catalog}' not found or not accessible - create it first or set the `catalog` bundle variable"
)
spark.sql(
    f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}` COMMENT "
    "'Budget Planning & Financial Projections (synthetic). Portfolio model, expenditure forecast, "
    "scenarios, capacity analysis and variance reporting. Working figures - protected.'"
)
spark.sql(
    f"CREATE VOLUME IF NOT EXISTS `{catalog}`.`{schema}`.`{volume}` COMMENT "
    "'Landing zone for raw portfolio, ledger, assurance and market capacity extracts, plus Auto Loader checkpoints.'"
)

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

if reset:
    for row in spark.sql(f"SHOW VIEWS IN `{catalog}`.`{schema}`").collect():
        spark.sql(f"DROP VIEW IF EXISTS {fqn(row['viewName'])}")
    for row in spark.sql(f"SHOW TABLES IN `{catalog}`.`{schema}`").collect():
        if not row["isTemporary"]:
            spark.sql(f"DROP TABLE IF EXISTS {fqn(row['tableName'])}")
    for sub in ("extracts", "_checkpoints"):
        try:
            dbutils.fs.rm(f"{VOLUME_ROOT}/{sub}", recurse=True)
        except Exception as exc:  # noqa: BLE001 - directory may not exist yet
            print(f"skip {sub}: {exc.__class__.__name__}")
    print("Reset complete")

for sub in ("extracts", "_checkpoints"):
    dbutils.fs.mkdirs(f"{VOLUME_ROOT}/{sub}")

# COMMAND ----------

DDL = {
    "pipeline_control": (
        "key STRING NOT NULL, value STRING, updated_at TIMESTAMP",
        "Pipeline control values: synthetic world anchor date and seed, landing watermarks.",
        "",
    ),
    "scenario_definitions": (
        """scenario_id STRING NOT NULL COMMENT 'Scenario identifier',
           scenario_name STRING NOT NULL, version INT NOT NULL COMMENT 'Scenario version; levers are versioned with it',
           base_scenario_id STRING COMMENT 'Scenario this one starts from (null = forecast from recorded drivers only)',
           method STRING NOT NULL COMMENT 'as_forecast | levers | auto_sequence (capacity-aware sequencing optimiser)',
           status STRING NOT NULL COMMENT 'Locked | Draft | Submitted | Endorsed | Archived',
           decision_purpose STRING, description STRING, created_by STRING, created_at TIMESTAMP,
           source STRING COMMENT 'seed (pipeline) | app (user-created)'""",
        "Allocation scenario definitions. Inputs as data so every scenario can be re-run and audited. The application inserts user drafts here.",
        "TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')",
    ),
    "scenario_levers": (
        """lever_id STRING NOT NULL, scenario_id STRING NOT NULL, scenario_version INT NOT NULL,
           lever_type STRING NOT NULL COMMENT 'defer_months | accelerate_months | escalation_delta_pp | capacity_uplift_pct | scope_change_aud_m | exclude_project',
           target_type STRING NOT NULL COMMENT 'project | program | sector | capacity_category | portfolio',
           target_id STRING COMMENT 'Identifier of the target (null for portfolio)',
           value DOUBLE NOT NULL COMMENT 'Lever value in the unit implied by lever_type',
           rationale STRING, assumption_id STRING COMMENT 'Assumption register record supporting the lever',
           created_by STRING, created_at TIMESTAMP, source STRING COMMENT 'seed | app | optimizer'""",
        "Scenario levers: the explicit, versioned adjustments that distinguish a scenario from the forecast.",
        "TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')",
    ),
    "forecast_runs": (
        """run_id STRING NOT NULL, run_type STRING, as_of_date DATE, actuals_through DATE,
           first_forecast_month DATE, horizon_start_fy INT, horizon_end_fy INT, plan_version STRING,
           capacity_model_version STRING, assumption_versions STRING COMMENT 'JSON: assumption_id -> version used',
           scenario_versions STRING COMMENT 'JSON: scenario_id -> version used', parameters STRING COMMENT 'JSON run parameters',
           started_at TIMESTAMP, completed_at TIMESTAMP, status STRING""",
        "Append-only register of forecast runs: the traceable basis (inputs, versions, parameters) of every published number.",
        "TBLPROPERTIES ('delta.appendOnly' = 'true')",
    ),
    "dq_results": (
        """run_id STRING, checked_at TIMESTAMP, table_name STRING, rule STRING, severity STRING COMMENT 'error rows are dropped; warn rows are kept',
           failed_rows BIGINT, total_rows BIGINT, passed BOOLEAN""",
        "Append-only data quality results for the silver conformance step.",
        "TBLPROPERTIES ('delta.appendOnly' = 'true')",
    ),
    # ---- written by the Portfolio Command Centre app (append-only events; latest event = current state) ----
    "scenario_events": (
        """event_id STRING NOT NULL, scenario_id STRING NOT NULL, scenario_version INT NOT NULL,
           event STRING NOT NULL COMMENT 'Created | Recompute requested | Submitted | Returned | Endorsed | Archived',
           note STRING, job_run_id BIGINT COMMENT 'budget_forecast run triggered by the event, if any',
           actor STRING, created_at TIMESTAMP""",
        "Scenario workflow and audit log written by the app: creation, recompute requests, submission, endorsement.",
        "TBLPROPERTIES ('delta.appendOnly' = 'true')",
    ),
    "forecast_submissions": (
        """submission_id STRING NOT NULL, cycle STRING NOT NULL COMMENT 'Forecast cycle, YYYY-MM of the actuals month being closed',
           program_id STRING NOT NULL, status STRING NOT NULL COMMENT 'Submitted | Returned | Approved | Locked',
           forecast_aud_m DOUBLE COMMENT 'Program horizon forecast at submission, AUD m', commentary STRING,
           actor STRING, actor_role STRING COMMENT 'Program office | Portfolio office', created_at TIMESTAMP""",
        "Monthly forecast cycle: program office submissions and portfolio office review decisions.",
        "TBLPROPERTIES ('delta.appendOnly' = 'true')",
    ),
    "variance_commentary": (
        """commentary_id STRING NOT NULL, period STRING NOT NULL COMMENT 'YTD | CURRENT_FY | HORIZON',
           scope_level STRING NOT NULL COMMENT 'portfolio | program | project', scope_id STRING NOT NULL,
           reason_code STRING COMMENT 'Attribution for unexplained variance (e.g. Contractor claim, Productivity, Data timing)',
           amount_aud_m DOUBLE COMMENT 'Variance attributed by this entry, AUD m', commentary STRING,
           source STRING COMMENT 'user | ai_draft (accepted by the author)', actor STRING, created_at TIMESTAMP""",
        "Variance explanations and attributions recorded against the variance bridge by program and portfolio offices.",
        "TBLPROPERTIES ('delta.appendOnly' = 'true')",
    ),
    "assurance_actions": (
        """action_id STRING NOT NULL, record_id STRING NOT NULL,
           action STRING NOT NULL COMMENT 'Attested | Comment | Action raised | Closed', comment STRING,
           actor STRING, created_at TIMESTAMP""",
        "Owner attestations, comments and actions on assurance register records.",
        "TBLPROPERTIES ('delta.appendOnly' = 'true')",
    ),
    "briefing_packs": (
        """pack_id STRING NOT NULL, version INT NOT NULL, title STRING, scenario_id STRING, forecast_run_id STRING,
           narrative STRING COMMENT 'Markdown briefing narrative', status STRING NOT NULL COMMENT 'Draft | Approved',
           model STRING COMMENT 'Serving endpoint that drafted the first version (null if written by hand)',
           sources STRING COMMENT 'JSON: figures the draft was grounded on', actor STRING, created_at TIMESTAMP""",
        "Executive briefing packs: AI-drafted, human-edited and approved narratives tied to a forecast run.",
        "TBLPROPERTIES ('delta.appendOnly' = 'true')",
    ),
}

for name, (cols, comment, props) in DDL.items():
    spark.sql(f"CREATE TABLE IF NOT EXISTS {fqn(name)} ({cols}) COMMENT {sql_str(comment)} {props}")
    tag_table(name, BASE_TAGS)

print("Setup complete:", ", ".join(DDL))
