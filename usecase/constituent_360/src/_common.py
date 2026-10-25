# Databricks notebook source
# MAGIC %md
# MAGIC # Shared helpers - Citizen & Constituent 360
# MAGIC
# MAGIC Included by every task with `%run ./_common` after the caller has read its widgets into
# MAGIC `catalog`, `schema` and `volume`. Provides:
# MAGIC
# MAGIC * table / volume naming - nothing environment-specific is hard-coded
# MAGIC * the **reference model**: agencies, data domains, identity source systems, channels, intents,
# MAGIC   need signals, purposes of use and the purpose x domain access policy. `00_setup` publishes these
# MAGIC   as `ref_*` tables; the generator, the pipeline and the Unity Catalog policies all read the same values
# MAGIC * deterministic pseudo-random helpers (partitioning-independent, seeded)
# MAGIC * governed table writes (table + column comments, classification tags), run control and quality checks

# COMMAND ----------

import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

assert catalog, "catalog parameter is required"
assert schema, "schema parameter is required"
assert volume, "volume parameter is required"

spark.conf.set("spark.sql.session.timeZone", "UTC")
# Pin the session to the use case catalog/schema so no unqualified statement can land elsewhere.
spark.sql(f"USE CATALOG `{catalog}`")

USECASE = "constituent_360"
# Ownership marker stamped on every object this use case creates. Destructive operations (overwrite,
# drop, replace, rename) are only ever performed on objects that carry it - see claim_object / assert_owned.
OWNER_PROPERTY = "nba.managed_by"
OWNER_VALUE = "nba-constituent-360"


def fqn(table: str) -> str:
    return f"`{catalog}`.`{schema}`.`{table}`"


def table_name(table: str) -> str:
    return f"{catalog}.{schema}.{table}"


def fn_name(function: str) -> str:
    return f"`{catalog}`.`{schema}`.`{function}`"


def table_exists(table: str) -> bool:
    return spark.catalog.tableExists(table_name(table))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Object ownership guard
# MAGIC
# MAGIC The pipeline only creates objects inside `catalog.schema` and only modifies objects it created.
# MAGIC Tables and views carry the `nba.managed_by` table property; functions, procedures and every other
# MAGIC object are recorded in `pipeline_object_registry`. Any overwrite / drop / replace of an existing
# MAGIC object that is not ours fails loudly instead of touching it.

# COMMAND ----------

REGISTRY = "pipeline_object_registry"


def _registry_ready() -> bool:
    return table_exists(REGISTRY)


def ensure_registry() -> None:
    if not table_exists(REGISTRY):
        spark.sql(f"""CREATE TABLE {fqn(REGISTRY)}
                      (object_name STRING, object_type STRING, created_at TIMESTAMP, created_by STRING)
                      COMMENT 'Objects created by the constituent_360 pipeline. Only these are ever modified or dropped.'
                      TBLPROPERTIES ('{OWNER_PROPERTY}' = '{OWNER_VALUE}')""")


def registered(name: str) -> bool:
    if not _registry_ready():
        return False
    return spark.sql(f"SELECT 1 FROM {fqn(REGISTRY)} WHERE object_name = :n LIMIT 1", args={"n": name}).count() > 0


def has_owner_property(name: str) -> bool:
    try:
        rows = spark.sql(f"SHOW TBLPROPERTIES {fqn(name)} ('{OWNER_PROPERTY}')").collect()
    except Exception:  # noqa: BLE001
        return False
    return any(r.value == OWNER_VALUE for r in rows)


def is_owned(name: str, kind: str = "TABLE") -> bool:
    if kind in ("TABLE", "VIEW") and has_owner_property(name):
        return True
    return registered(name)


def object_exists(name: str, kind: str = "TABLE") -> bool:
    if kind in ("TABLE", "VIEW"):
        return table_exists(name)
    if kind == "VOLUME":
        return spark.sql(f"""SELECT 1 FROM `{catalog}`.information_schema.volumes
                             WHERE volume_schema = :s AND volume_name = :n LIMIT 1""",
                         args={"s": schema, "n": name}).count() > 0
    return spark.sql(f"""SELECT 1 FROM `{catalog}`.information_schema.routines
                         WHERE routine_schema = :s AND routine_name = :n LIMIT 1""",
                     args={"s": schema, "n": name}).count() > 0


def assert_owned(name: str, kind: str = "TABLE") -> None:
    """Raise before modifying an existing object this pipeline did not create. New names are fine."""
    if object_exists(name, kind) and not is_owned(name, kind):
        raise PermissionError(
            f"{kind} {catalog}.{schema}.{name} exists but was not created by {OWNER_VALUE}; refusing to modify it. "
            f"Choose a different schema or remove the object manually.")


def claim_object(name: str, kind: str = "TABLE") -> None:
    """Mark an object as created by this pipeline (table property + registry row)."""
    if kind == "TABLE":
        spark.sql(f"ALTER TABLE {fqn(name)} SET TBLPROPERTIES ('{OWNER_PROPERTY}' = '{OWNER_VALUE}')")
    elif kind == "VIEW":
        spark.sql(f"ALTER VIEW {fqn(name)} SET TBLPROPERTIES ('{OWNER_PROPERTY}' = '{OWNER_VALUE}')")
    ensure_registry()
    spark.sql(f"""MERGE INTO {fqn(REGISTRY)} t USING (SELECT :n AS object_name, :k AS object_type) s
                  ON t.object_name = s.object_name
                  WHEN MATCHED THEN UPDATE SET object_type = s.object_type
                  WHEN NOT MATCHED THEN INSERT (object_name, object_type, created_at, created_by)
                       VALUES (s.object_name, s.object_type, current_timestamp(), current_user())""",
              args={"n": name, "k": kind})


def unregister(name: str) -> None:
    if _registry_ready():
        spark.sql(f"DELETE FROM {fqn(REGISTRY)} WHERE object_name = :n", args={"n": name})


def owned_sql(statement: str, name: str, kind: str = "TABLE"):
    """Run a CREATE OR REPLACE / ALTER / DROP statement against `name` only if it is new or ours,
    then claim it (unless the statement dropped it)."""
    assert_owned(name, kind)
    out = spark.sql(statement)
    if statement.lstrip().upper().startswith("DROP"):
        unregister(name)
    else:
        claim_object(name, kind)
    return out


def drop_owned(name: str, kind: str = "TABLE") -> bool:
    if not object_exists(name, kind):
        unregister(name)
        return False
    assert_owned(name, kind)
    keyword = {"TABLE": "TABLE", "VIEW": "VIEW", "FUNCTION": "FUNCTION", "PROCEDURE": "PROCEDURE"}[kind]
    spark.sql(f"DROP {keyword} IF EXISTS {fqn(name)}")
    unregister(name)
    return True


def rename_owned(src: str, dst: str) -> None:
    """Swap a freshly built `<name>__build` table into place (fail-closed for policy-protected tables)."""
    assert_owned(src)
    drop_owned(dst)
    spark.sql(f"ALTER TABLE {fqn(src)} RENAME TO {fqn(dst)}")
    unregister(src)
    claim_object(dst)


def sql_str(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


VOLUME_ROOT = f"/Volumes/{catalog}/{schema}/{volume}"
LANDING_ROOT = f"{VOLUME_ROOT}/extracts"
CHECKPOINT_ROOT = f"{VOLUME_ROOT}/_checkpoints"
SCHEMA_ROOT = f"{VOLUME_ROOT}/_schemas"
MODEL_ROOT = f"{VOLUME_ROOT}/_models"


def new_run_id(prefix: str = "RUN") -> str:
    return f"{prefix}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Reference model
# MAGIC
# MAGIC Agencies own their data (hub-and-spoke). A **data domain** is the unit of consent and purpose-of-use
# MAGIC enforcement: every interaction row carries one, and the `identity` domain covers the resolved identity
# MAGIC attributes themselves.

# COMMAND ----------

AGENCIES = [
    # agency_code, agency_name, description
    ("SNSW", "Service NSW", "Front-door service agency: contact centre, service centres and the web account"),
    ("HOUSING", "Housing support", "Social and emergency housing assistance"),
    ("TRANSPORT", "Transport licensing", "Driver licensing, toll relief and concession travel"),
    ("REVENUE", "Cost of living", "Rebates, concessions and cost-of-living support"),
    ("HEALTH", "Community health", "Community health and care coordination"),
]

DATA_DOMAINS = [
    # data_domain, display_name, owning_agency, sensitivity, description
    ("identity", "Identity attributes", None, "protected", "Resolved identity attributes: name, date of birth, contact points, address"),
    ("customer_service", "Customer service interactions", "SNSW", "protected", "General enquiries through Service NSW channels"),
    ("housing", "Housing interactions", "HOUSING", "protected", "Housing support applications, evidence and case contact"),
    ("transport_licensing", "Licensing interactions", "TRANSPORT", "protected", "Licence, toll relief and concession travel contact"),
    ("cost_of_living", "Cost of living interactions", "REVENUE", "protected", "Rebate and concession contact"),
    ("health", "Health service history", "HEALTH", "sensitive", "Community health contact - sensitive information"),
]

SOURCE_SYSTEMS = [
    # source_system, display_name, agency_code, data_domain, identity_assurance, survivorship_rank, extract
    ("snsw_customer", "Service NSW", "SNSW", "customer_service", "verified", 1, "snsw_customers"),
    ("transport_licence", "Transport licensing", "TRANSPORT", "transport_licensing", "verified", 2, "transport_licence_holders"),
    ("revenue_concession", "Cost of living", "REVENUE", "cost_of_living", "documented", 3, "revenue_concession_applicants"),
    ("housing_crm", "Housing CRM", "HOUSING", "housing", "documented", 4, "housing_crm_clients"),
    ("community_health", "Community health", "HEALTH", "health", "documented", 5, "community_health_clients"),
    ("web_account", "Web account", "SNSW", "customer_service", "self_asserted", 6, "web_accounts"),
]
SOURCE_BY_SYSTEM = {s[0]: s for s in SOURCE_SYSTEMS}

# extract -> (format, kind)
EXTRACTS = {
    "snsw_customers": ("csv", "identity"),
    "transport_licence_holders": ("csv", "identity"),
    "revenue_concession_applicants": ("json", "identity"),
    "housing_crm_clients": ("csv", "identity"),
    "community_health_clients": ("csv", "identity"),
    "web_accounts": ("json", "identity"),
    "contact_centre_calls": ("json", "interaction"),
    "web_form_submissions": ("json", "interaction"),
    "email_messages": ("json", "interaction"),
    "shopfront_visits": ("csv", "interaction"),
    "service_cases": ("csv", "case"),
    "consent_events": ("json", "consent"),
}

CHANNELS = [("phone", "Phone"), ("web", "Web form"), ("email", "Email"), ("shopfront", "Shopfront")]

INTENTS = [
    ("status_enquiry", "Status enquiry"),
    ("document_submission", "Document submission"),
    ("new_application", "New application"),
    ("evidence_question", "Evidence question"),
    ("payment_or_debt", "Payment or debt"),
    ("complaint", "Complaint"),
    ("change_of_details", "Change of details"),
    ("appointment_booking", "Appointment booking"),
    ("general_information", "General information"),
]
INTENT_CODES = [i[0] for i in INTENTS]

NEEDS = [
    ("housing_stability", "Housing stability"),
    ("financial_pressure", "Financial pressure"),
    ("mobility_access", "Mobility and transport access"),
    ("health_wellbeing", "Health and wellbeing"),
    ("document_burden", "Evidence and document burden"),
    ("digital_access", "Digital access"),
]
NEED_CODES = [n[0] for n in NEEDS]

# Case service types: (data_domain, service_type, service_line)
SERVICE_TYPES = [
    ("housing", "Housing Support application", "Housing"),
    ("housing", "Emergency accommodation", "Housing"),
    ("housing", "Rent relief", "Housing"),
    ("transport_licensing", "Licence renewal", "Licensing"),
    ("transport_licensing", "Licence class upgrade", "Licensing"),
    ("transport_licensing", "Toll relief", "Transport"),
    ("transport_licensing", "Concession travel", "Transport"),
    ("cost_of_living", "Energy rebate", "Cost of living"),
    ("cost_of_living", "Cost of living concession", "Cost of living"),
    ("health", "Community care plan", "Health"),
]

PURPOSES = [
    # purpose_code, display_name, agency_code, requires_case, description
    ("housing_case_support", "Housing case support", "HOUSING", True, "Assessing and progressing a housing support case"),
    ("licence_renewal", "Licence renewal", "TRANSPORT", True, "Processing a licence, toll relief or concession travel case"),
    ("cost_of_living_support", "Cost of living support", "REVENUE", True, "Assessing a rebate or concession case"),
    ("general_enquiry", "General enquiry", "SNSW", False, "Answering a verified constituent's enquiry at the front door"),
    ("health_service_coordination", "Health service coordination", "HEALTH", True, "Coordinating a community care plan"),
]

# purpose x domain policy: access_rule allow (statutory) | consent | deny; identity_level (identity domain only)
# full | minimum; signals_allowed = AI-derived sentiment / intent / need signals may be shown.
PURPOSE_DOMAIN_POLICY = [
    ("housing_case_support", "identity", "allow", "minimum", False, "Minimum necessary identity attributes"),
    ("housing_case_support", "housing", "allow", None, True, "Statutory basis: the agency's own case"),
    ("housing_case_support", "customer_service", "consent", None, False, "Front-door history only with consent"),
    ("housing_case_support", "cost_of_living", "consent", None, True, "Related support history only with consent"),
    ("housing_case_support", "transport_licensing", "deny", None, False, "Not required for the purpose"),
    ("housing_case_support", "health", "deny", None, False, "Restricted - incompatible purpose"),
    ("licence_renewal", "identity", "allow", "minimum", False, "Minimum necessary identity attributes"),
    ("licence_renewal", "transport_licensing", "allow", None, False, "Statutory basis: the agency's own case"),
    ("licence_renewal", "customer_service", "consent", None, False, "Front-door history only with consent"),
    ("licence_renewal", "housing", "deny", None, False, "Not required for the purpose"),
    ("licence_renewal", "cost_of_living", "deny", None, False, "Not required for the purpose"),
    ("licence_renewal", "health", "deny", None, False, "Restricted - incompatible purpose"),
    ("cost_of_living_support", "identity", "allow", "minimum", False, "Minimum necessary identity attributes"),
    ("cost_of_living_support", "cost_of_living", "allow", None, True, "Statutory basis: the agency's own case"),
    ("cost_of_living_support", "housing", "consent", None, True, "Related support history only with consent"),
    ("cost_of_living_support", "customer_service", "consent", None, False, "Front-door history only with consent"),
    ("cost_of_living_support", "transport_licensing", "consent", None, False, "Concession history only with consent"),
    ("cost_of_living_support", "health", "deny", None, False, "Restricted - incompatible purpose"),
    ("general_enquiry", "identity", "allow", "minimum", False, "Minimum necessary identity attributes"),
    ("general_enquiry", "customer_service", "allow", None, False, "Statutory basis: Service NSW's own records"),
    ("general_enquiry", "housing", "consent", None, False, "Status visibility only with consent"),
    ("general_enquiry", "cost_of_living", "consent", None, False, "Status visibility only with consent"),
    ("general_enquiry", "transport_licensing", "consent", None, False, "Status visibility only with consent"),
    ("general_enquiry", "health", "deny", None, False, "Restricted - incompatible purpose"),
    ("health_service_coordination", "identity", "allow", "full", False, "Clinical coordination needs verified identity"),
    ("health_service_coordination", "health", "allow", None, True, "Statutory basis: the agency's own care plan"),
    ("health_service_coordination", "housing", "consent", None, True, "Social determinants only with consent"),
    ("health_service_coordination", "customer_service", "consent", None, False, "Front-door history only with consent"),
    ("health_service_coordination", "transport_licensing", "deny", None, False, "Not required for the purpose"),
    ("health_service_coordination", "cost_of_living", "deny", None, False, "Not required for the purpose"),
]

# Synthetic staff (example.gov.au is a reserved, non-routable demonstration domain).
SYNTH_OFFICERS = [
    # principal, display_name, role, agency_code, purposes
    ("s.kim@example.gov.au", "S. Kim", "Housing support officer", "HOUSING", ["housing_case_support"]),
    ("a.patel@example.gov.au", "A. Patel", "Housing support officer", "HOUSING", ["housing_case_support"]),
    ("r.walker@example.gov.au", "R. Walker", "Licensing officer", "TRANSPORT", ["licence_renewal"]),
    ("m.davis@example.gov.au", "M. Davis", "Concessions officer", "REVENUE", ["cost_of_living_support"]),
    ("t.brown@example.gov.au", "T. Brown", "Contact centre officer", "SNSW", ["general_enquiry"]),
    ("l.hassan@example.gov.au", "L. Hassan", "Community health coordinator", "HEALTH", ["health_service_coordination"]),
]

# formal given name -> common short form; silver reverses it to a canonical given name
NICKNAMES = {
    "William": "Bill", "Robert": "Bob", "Elizabeth": "Liz", "Katherine": "Kate", "Michael": "Mike",
    "Christopher": "Chris", "Jennifer": "Jen", "Margaret": "Maggie", "Thomas": "Tom", "Alexander": "Alex",
    "Benjamin": "Ben", "Samantha": "Sam", "Daniel": "Dan", "Joseph": "Joe", "Matthew": "Matt",
    "Rebecca": "Bec", "Jessica": "Jess", "Patricia": "Trish", "Nicholas": "Nick", "Anthony": "Tony",
    "James": "Jim", "Samuel": "Sammy", "Mohammed": "Muhammad", "Ahmed": "Ahmad", "Sarah": "Sara",
    "Oliver": "Ollie", "Charlotte": "Charlie", "Alexandra": "Lexi", "Jonathan": "Jon", "Hannah": "Hanna",
}

STREET_TYPES = [("Street", "St"), ("Road", "Rd"), ("Avenue", "Ave"), ("Crescent", "Cres"), ("Parade", "Pde"),
                ("Drive", "Dr"), ("Place", "Pl"), ("Court", "Ct"), ("Lane", "Ln"), ("Highway", "Hwy")]
AU_STATES = ["NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"]

# The agency whose own case anchors each case-scoped purpose
DOMAIN_PURPOSE = {"housing": "housing_case_support", "transport_licensing": "licence_renewal",
                  "cost_of_living": "cost_of_living_support", "health": "health_service_coordination"}
AGENCY_DOMAIN = {"SNSW": "customer_service", "HOUSING": "housing", "TRANSPORT": "transport_licensing",
                 "REVENUE": "cost_of_living", "HEALTH": "health"}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Deterministic pseudo-random helpers
# MAGIC
# MAGIC `u_sql(seed, salt, *cols)` is a uniform [0, 1) derived from a hash of the seed, a salt and key columns,
# MAGIC so the same seed always produces the same synthetic world regardless of partitioning or retries.

# COMMAND ----------

_U_MOD = 1000003


def u_sql(seed, salt: str, *cols: str) -> str:
    args = ", ".join([str(int(seed)), sql_str(salt)] + list(cols))
    return f"(pmod(xxhash64({args}), {_U_MOD}) / {float(_U_MOD)})"


def u_col(seed, salt: str, *cols: str):
    return F.expr(u_sql(seed, salt, *cols))


def sql_array(values) -> str:
    return "array(" + ", ".join(sql_str(v) for v in values) + ")"


def pick_sql(values, u: str) -> str:
    """element of a literal list chosen by a uniform SQL expression."""
    return f"element_at({sql_array(values)}, cast(floor({u} * {len(values)}) + 1 AS INT))"


def pick_arr_sql(arr: str, u: str) -> str:
    """element of an array-valued SQL expression chosen by a uniform SQL expression."""
    return f"element_at({arr}, cast(floor({u} * size({arr})) + 1 AS INT))"


def sql_map(d: dict) -> str:
    return "map(" + ", ".join(f"{sql_str(k)}, {sql_str(v)}" for k, v in d.items()) + ")"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Governed writes, run control and quality checks

# COMMAND ----------

COLUMN_DOCS = {
    "constituent_id": "Resolved constituent identifier (C-nnnnn), stable across runs. Assigned by entity resolution; there is no common identifier in the source systems.",
    "source_record_id": "Source identity record: <source_system>:<native id>. Join to silver_source_identities.",
    "source_system": "Identity source system code (see ref_source_systems).",
    "agency_code": "Owning agency code (see ref_agencies). Each agency keeps ownership of its data.",
    "data_domain": "Data domain used for consent and purpose-of-use enforcement (see ref_data_domains).",
    "purpose_code": "Purpose of use (see ref_purposes).",
    "interaction_id": "Interaction identifier from the channel system.",
    "case_id": "Service case (journey) identifier from the owning agency.",
    "channel": "Contact channel: phone, web, email or shopfront.",
    "channel_label": "Display label of the channel.",
    "event_ts": "When the interaction happened (UTC).",
    "intent": "AI-derived intent of the interaction (ai_classify). Inferred personal information.",
    "sentiment": "AI-derived sentiment of the interaction (ai_analyze_sentiment). Inferred personal information.",
    "tone": "AI-derived tone (calm, concerned, frustrated, distressed, satisfied). Inferred personal information.",
    "urgency_score": "AI-derived service urgency 0-100. Inferred personal information.",
    "identity_confidence": "Confidence that the source records grouped under the constituent belong to one person (0-1).",
    "match_probability": "Splink posterior probability that two source records refer to the same person.",
    "owner_principal": "Principal (user or service principal) that owns the case, NULL when unassigned.",
    "run_id": "Pipeline run that produced the row.",
}

# Namespaced keys so they never collide with workspace governed-tag policies.
BASE_TAGS = {"nba_usecase": USECASE, "nba_synthetic": "true"}


def tag_table(name: str, tags: dict) -> None:
    """Best effort: governed-tag policies may restrict tag keys/values in some workspaces."""
    pairs = ", ".join(f"{sql_str(k)} = {sql_str(v)}" for k, v in tags.items())
    try:
        spark.sql(f"ALTER TABLE {fqn(name)} SET TAGS ({pairs})")
    except Exception as exc:  # noqa: BLE001
        print(f"tagging skipped for {name}: {str(exc).splitlines()[0][:160]}")


def write_table(df, name: str, comment: str, column_comments: dict = None, mode: str = "overwrite",
                layer: str = None, classification: str = "protected", tags: dict = None) -> int:
    """Write a governed table: column comments travel as field metadata, then table comment and tags.
    Refuses to write to an existing table this pipeline did not create."""
    assert_owned(name)
    docs = {**COLUMN_DOCS, **(column_comments or {})}
    for c in df.columns:
        if c in docs:
            df = df.withMetadata(c, {"comment": docs[c]})
    writer = df.write.mode(mode)
    if mode == "overwrite":
        writer = writer.option("overwriteSchema", "true")
    else:
        writer = writer.option("mergeSchema", "true")
    writer.saveAsTable(table_name(name))
    claim_object(name)
    spark.sql(f"COMMENT ON TABLE {fqn(name)} IS {sql_str(comment)}")
    all_tags = {**BASE_TAGS, "nba_classification": classification, **({"nba_layer": layer} if layer else {}), **(tags or {})}
    tag_table(name, all_tags)
    return spark.table(table_name(name)).count()


def get_control(key: str, default=None):
    if not table_exists("pipeline_control"):
        return default
    rows = spark.sql(f"SELECT value FROM {fqn('pipeline_control')} WHERE key = :k", args={"k": key}).collect()
    return rows[0][0] if rows else default


def set_control(key: str, value) -> None:
    assert_owned("pipeline_control")
    spark.sql(
        f"""MERGE INTO {fqn('pipeline_control')} t
            USING (SELECT :k AS key, :v AS value) s ON t.key = s.key
            WHEN MATCHED THEN UPDATE SET value = s.value, updated_at = current_timestamp()
            WHEN NOT MATCHED THEN INSERT (key, value, updated_at) VALUES (s.key, s.value, current_timestamp())""",
        args={"k": key, "v": str(value)},
    )


def record_checks(task: str, run_id: str, checks: list) -> list:
    """Append quality checks: list of (check_name, passed, severity, observed, expected, detail)."""
    rows = [(run_id, task, c[0], bool(c[1]), c[2], str(c[3]), str(c[4]), str(c[5] if len(c) > 5 else ""))
            for c in checks]
    if rows:
        df = spark.createDataFrame(rows, "run_id string, task string, check_name string, passed boolean, severity string, "
                                         "observed string, expected string, detail string") \
                  .withColumn("checked_at", F.current_timestamp())
        assert_owned("pipeline_quality_checks")
        df.write.mode("append").option("mergeSchema", "true").saveAsTable(table_name("pipeline_quality_checks"))
    for c in checks:
        print(f"[{'PASS' if c[1] else 'FAIL'}] {c[2]:8s} {c[0]}: observed={c[3]} expected={c[4]} {c[5] if len(c) > 5 else ''}")
    return [c for c in checks if not c[1] and c[2] == "critical"]
