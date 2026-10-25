# Databricks notebook source
# MAGIC %md
# MAGIC # 00 Setup
# MAGIC
# MAGIC Creates the use case schema and landing volume (the catalog must already exist), the run-control
# MAGIC table, the published reference model (`ref_*`) and the governance tables that officers only ever
# MAGIC touch through SQL procedures (`07_consent_and_serving`).
# MAGIC
# MAGIC `reset=true` drops **only the objects this pipeline created** (tables/views stamped with the
# MAGIC `nba.managed_by` property or listed in `pipeline_object_registry`) and clears the pipeline's own
# MAGIC sub-folders of the landing volume, so the bootstrap job rebuilds the synthetic world from scratch.
# MAGIC Anything else that happens to live in the schema is left untouched; a pre-existing object with a
# MAGIC colliding name makes the run fail rather than overwrite it.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.dropdown("reset", "false", ["true", "false"])

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
reset = dbutils.widgets.get("reset").lower() == "true"

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

# The catalog must already exist - this pipeline never creates or alters catalogs.
assert spark.sql(f"SHOW CATALOGS LIKE '{catalog}'").count() == 1, f"catalog {catalog} does not exist"

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}` COMMENT "
          f"{sql_str('Citizen & Constituent 360 - synthetic, consented, resolved constituent view')} "
          f"WITH DBPROPERTIES ('{OWNER_PROPERTY}' = '{OWNER_VALUE}')")
spark.sql(f"USE SCHEMA `{schema}`")
ensure_registry()

if object_exists(volume, "VOLUME"):
    assert_owned(volume, "VOLUME")
else:
    spark.sql(f"CREATE VOLUME `{catalog}`.`{schema}`.`{volume}` COMMENT "
              f"{sql_str('Landing zone for raw channel, identity, case and consent extracts')}")
    claim_object(volume, "VOLUME")

if reset:
    owned = spark.sql(f"SELECT object_name, object_type FROM {fqn(REGISTRY)} "
                      f"WHERE object_type IN ('TABLE', 'VIEW', 'FUNCTION', 'PROCEDURE')").collect()
    # views and routines first (they depend on tables), never the registry itself
    order = {"VIEW": 0, "PROCEDURE": 1, "FUNCTION": 2, "TABLE": 3}
    for r in sorted(owned, key=lambda r: order[r.object_type]):
        if r.object_name == REGISTRY:
            continue
        if r.object_type in ("TABLE", "VIEW") and object_exists(r.object_name) and not has_owner_property(r.object_name):
            # registered name, but the live object was replaced by someone else - leave it alone
            print(f"skip {r.object_name}: no ownership property on the live object")
            continue
        try:
            # functions still referenced by row filters / masks may fail here; retried after the tables go
            if drop_owned(r.object_name, r.object_type):
                print(f"dropped {r.object_type.lower()} {r.object_name}")
        except Exception as exc:  # noqa: BLE001
            print(f"could not drop {r.object_type.lower()} {r.object_name}: {str(exc).splitlines()[0][:160]}")
    # second pass for functions still referenced by row filters / masks at the first attempt
    for r in spark.sql(f"SELECT object_name, object_type FROM {fqn(REGISTRY)} "
                       f"WHERE object_type IN ('FUNCTION', 'PROCEDURE')").collect():
        if drop_owned(r.object_name, r.object_type):
            print(f"dropped {r.object_type.lower()} {r.object_name}")
    for p in (LANDING_ROOT, CHECKPOINT_ROOT, SCHEMA_ROOT, MODEL_ROOT):
        try:
            dbutils.fs.rm(p, recurse=True)
        except Exception as exc:  # noqa: BLE001
            print(f"skip rm {p}: {str(exc).splitlines()[0][:120]}")

for p in (LANDING_ROOT, CHECKPOINT_ROOT, SCHEMA_ROOT, MODEL_ROOT):
    dbutils.fs.mkdirs(p)

if not table_exists("pipeline_control"):
    spark.sql(f"""CREATE TABLE {fqn('pipeline_control')}
                  (key STRING, value STRING, updated_at TIMESTAMP)
                  COMMENT 'Run control: synthetic world anchor and seed, landing watermarks, constituent id sequence'""")
    claim_object("pipeline_control")
assert_owned("pipeline_control")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Reference model

# COMMAND ----------

ref = {
    "ref_agencies": (spark.createDataFrame(AGENCIES, "agency_code string, agency_name string, description string"),
                     "Agencies participating in the hub-and-spoke constituent view. Each keeps ownership of its data."),
    "ref_data_domains": (spark.createDataFrame(DATA_DOMAINS, "data_domain string, display_name string, owning_agency string, "
                                                             "sensitivity string, description string"),
                         "Data domains: the unit of consent and purpose-of-use enforcement."),
    "ref_source_systems": (spark.createDataFrame(SOURCE_SYSTEMS, "source_system string, display_name string, agency_code string, "
                                                                 "data_domain string, identity_assurance string, "
                                                                 "survivorship_rank int, extract string"),
                           "Identity source systems. survivorship_rank orders attribute trust for the golden record (1 = most trusted)."),
    "ref_channels": (spark.createDataFrame(CHANNELS, "channel string, channel_label string"), "Contact channels."),
    "ref_intents": (spark.createDataFrame(INTENTS, "intent string, intent_label string"),
                    "Interaction intent labels used by ai_classify."),
    "ref_needs": (spark.createDataFrame(NEEDS, "need string, need_label string"),
                  "Need signals extracted from interaction text with ai_query structured output."),
    "ref_service_types": (spark.createDataFrame(SERVICE_TYPES, "data_domain string, service_type string, service_line string"),
                          "Case service types and the service line they report under."),
    "ref_purposes": (spark.createDataFrame(PURPOSES, "purpose_code string, display_name string, agency_code string, "
                                                     "requires_case boolean, description string"),
                     "Purposes of use. requires_case = the access session must be anchored to a case in the officer's caseload."),
    "ref_purpose_domain_policy": (spark.createDataFrame(PURPOSE_DOMAIN_POLICY, "purpose_code string, data_domain string, access_rule string, "
                                                                               "identity_level string, signals_allowed boolean, rationale string"),
                                  "Purpose x data domain access policy enforced by Unity Catalog row filters and column masks. "
                                  "access_rule: allow (statutory basis) | consent (requires current constituent consent) | deny."),
}
for name, (df, comment) in ref.items():
    n = write_table(df, name, comment, layer="reference", classification="official")
    print(f"{name}: {n} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Governance tables
# MAGIC
# MAGIC Created once and never overwritten by the pipeline (except on reset). Officers have no direct
# MAGIC privileges on these tables; they act through `SQL SECURITY DEFINER` procedures.

# COMMAND ----------

GOVERNANCE_DDL = {
    "staff_directory": ("principal STRING, display_name STRING, role STRING, agency_code STRING, active BOOLEAN, updated_at TIMESTAMP",
                        "Staff directory for display names and agency membership (synthetic officers + the demo officer)."),
    "staff_purpose_authorisations": ("principal STRING, purpose_code STRING, valid_from DATE, valid_to DATE, granted_by STRING, "
                                     "granted_at TIMESTAMP, note STRING",
                                     "Which principals may act under which purposes of use. Maintained by data stewards."),
    "access_sessions": ("session_id STRING, principal STRING, purpose_code STRING, case_id STRING, subject_constituent_id STRING, "
                        "justification STRING, started_at TIMESTAMP, expires_at TIMESTAMP, ended_at TIMESTAMP, end_reason STRING",
                        "Declared purpose-of-use sessions. Row filters and masks evaluate the caller's active session. "
                        "Written only by start_access_session / end_access_session."),
    "access_audit_events": ("event_id STRING, event_ts TIMESTAMP, principal STRING, constituent_id STRING, case_id STRING, "
                            "purpose_code STRING, event_type STRING, decision STRING, detail STRING, source STRING",
                            "Application-level access audit (session start/end, reveals, restricted attempts). "
                            "Complements system.access.audit."),
    "record_change_requests": ("request_id STRING, requested_at TIMESTAMP, principal STRING, purpose_code STRING, constituent_id STRING, "
                               "case_id STRING, change_type STRING, details STRING, reason_code STRING, status STRING, "
                               "reviewed_by STRING, reviewed_at TIMESTAMP",
                               "Governed record changes staged for review before write-back to the owning source system."),
    "identity_review_decisions": ("decision_id STRING, decided_at TIMESTAMP, principal STRING, decision STRING, "
                                  "source_record_id_l STRING, source_record_id_r STRING, reason STRING, active BOOLEAN",
                                  "Steward identity decisions honoured by entity resolution: must_link | cannot_link."),
    "pipeline_quality_checks": ("run_id STRING, task STRING, check_name STRING, passed BOOLEAN, severity STRING, observed STRING, "
                                "expected STRING, detail STRING, checked_at TIMESTAMP",
                                "Data, entity resolution, AI and policy assertions recorded by every task."),
}
for name, (cols, comment) in GOVERNANCE_DDL.items():
    if not table_exists(name):
        spark.sql(f"CREATE TABLE {fqn(name)} ({cols}) COMMENT {sql_str(comment)}")
        claim_object(name)
    assert_owned(name)  # fails if a same-named table pre-dates this pipeline
    tag_table(name, {**BASE_TAGS, "nba_layer": "governance", "nba_classification": "protected"})

print("setup complete:", catalog, schema, VOLUME_ROOT)
