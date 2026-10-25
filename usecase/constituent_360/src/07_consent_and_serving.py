# Databricks notebook source
# MAGIC %md
# MAGIC # 07 Consent enforcement and serving
# MAGIC
# MAGIC Publishes what officers actually query. Consent and purpose of use are enforced **in Unity Catalog**
# MAGIC (row filters + column masks + `SQL SECURITY DEFINER` procedures), never in the application:
# MAGIC
# MAGIC 1. Staff directory and purpose authorisations (synthetic officers + the demo officer).
# MAGIC 2. `c360_v_active_grants` - for every active, authorised purpose session: each data domain's rule
# MAGIC    (`allow` / `consent` / `deny`), consent state and whether it is visible right now.
# MAGIC 3. Policy functions: `c360_rf_person_domain`, `c360_signals_ok`, `c360_rf_caseload`, `c360_rf_directory`
# MAGIC    and masks for DOB / email / phone / street, AI signals and restricted identity-graph nodes.
# MAGIC 4. Serving tables rebuilt as `<name>__build` -> policies attached -> swapped into place -> granted.
# MAGIC    A failure leaves a table missing or ungranted (fail closed), never unprotected.
# MAGIC 5. Small-cell-suppressed aggregates for the KPI strip and service insights page.
# MAGIC 6. Caller-scoped views (`v_my_*`) and procedures (`start_access_session`, `end_access_session`,
# MAGIC    `log_access_event`, `request_record_change`, `record_identity_decision`).
# MAGIC
# MAGIC Every object is created inside `catalog.schema` through the ownership guard in `_common`, so an
# MAGIC object this pipeline did not create is never replaced, altered, dropped or granted.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("run_id", "")
dbutils.widgets.text("staff_group", "")
dbutils.widgets.text("demo_officer_principal", "")
dbutils.widgets.text("small_cell_threshold", "5")
dbutils.widgets.text("session_minutes", "60")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
run_id = dbutils.widgets.get("run_id") or None
STAFF_GROUP = dbutils.widgets.get("staff_group").strip()
DEMO_OFFICER_W = dbutils.widgets.get("demo_officer_principal").strip()
K = int(dbutils.widgets.get("small_cell_threshold"))
SESSION_MINUTES = int(dbutils.widgets.get("session_minutes"))

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

run_id = run_id or new_run_id("SERVE")
spark.sql(f"USE SCHEMA `{schema}`")
T = fqn
RUNNER = spark.sql("SELECT current_user()").first()[0]
DEMO_OFFICER = DEMO_OFFICER_W or get_control("demo_officer_principal") or RUNNER
print("demo officer:", DEMO_OFFICER, "| runner:", RUNNER, "| staff group:", STAFF_GROUP or "(none - no grants)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Staff directory and purpose authorisations

# COMMAND ----------

staff = [(p, n, r, a) for p, n, r, a, _ in SYNTH_OFFICERS]
auth = [(p, pur) for p, _, _, _, purposes in SYNTH_OFFICERS for pur in purposes]
if DEMO_OFFICER not in {s[0] for s in staff}:
    staff.append((DEMO_OFFICER, "Demo officer", "Housing support officer", "HOUSING"))
    auth += [(DEMO_OFFICER, "housing_case_support"), (DEMO_OFFICER, "general_enquiry")]

spark.createDataFrame(staff, "principal string, display_name string, role string, agency_code string") \
     .createOrReplaceTempView("c360_staff_src")
spark.createDataFrame(auth, "principal string, purpose_code string").createOrReplaceTempView("c360_auth_src")

for t in ("staff_directory", "staff_purpose_authorisations"):
    assert_owned(t)
spark.sql(f"""
  MERGE INTO {T('staff_directory')} t USING c360_staff_src s ON t.principal = s.principal
  WHEN MATCHED THEN UPDATE SET display_name = s.display_name, role = s.role, agency_code = s.agency_code,
                               active = true, updated_at = current_timestamp()
  WHEN NOT MATCHED THEN INSERT (principal, display_name, role, agency_code, active, updated_at)
                        VALUES (s.principal, s.display_name, s.role, s.agency_code, true, current_timestamp())""")
spark.sql(f"""
  MERGE INTO {T('staff_purpose_authorisations')} t USING c360_auth_src s
  ON t.principal = s.principal AND t.purpose_code = s.purpose_code AND t.valid_to IS NULL
  WHEN NOT MATCHED THEN INSERT (principal, purpose_code, valid_from, valid_to, granted_by, granted_at, note)
       VALUES (s.principal, s.purpose_code, date_sub(current_date(), 1), NULL, current_user(), current_timestamp(),
               'Seeded by 07_consent_and_serving (synthetic demonstration)')""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Active grants view (internal - never granted to staff)

# COMMAND ----------

VALID_AUTH = "current_date() BETWEEN a.valid_from AND coalesce(a.valid_to, DATE'9999-12-31')"
owned_sql(f"""
  CREATE OR REPLACE VIEW {T('c360_v_active_grants')}
  COMMENT 'Internal: per active authorised purpose session, each data domain rule and whether it is visible now. Read by policy functions.'
  AS
  SELECT s.session_id, s.principal, s.purpose_code, s.case_id, s.subject_constituent_id, s.started_at, s.expires_at,
         p.data_domain, p.access_rule, p.identity_level, p.signals_allowed, p.rationale,
         c.decision AS consent_decision, c.expires_at AS consent_expires_at,
         (p.access_rule = 'allow'
          OR (p.access_rule = 'consent' AND c.decision = 'granted'
              AND coalesce(c.expires_at > current_timestamp(), true))) AS visible
  FROM {T('access_sessions')} s
  JOIN {T('ref_purpose_domain_policy')} p ON p.purpose_code = s.purpose_code
  LEFT JOIN {T('consent_current')} c ON c.constituent_id = s.subject_constituent_id AND c.purpose_code = s.purpose_code
                                     AND c.data_domain = p.data_domain
  WHERE s.ended_at IS NULL AND s.expires_at > current_timestamp()
    AND EXISTS (SELECT 1 FROM {T('staff_purpose_authorisations')} a
                WHERE a.principal = s.principal AND a.purpose_code = s.purpose_code AND {VALID_AUTH})""",
          "c360_v_active_grants", "VIEW")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Policy functions
# MAGIC
# MAGIC `session_user()` is the querying officer (also inside `SQL SECURITY DEFINER` procedures).

# COMMAND ----------

G = T("c360_v_active_grants")
ME = "g.principal = session_user() AND g.subject_constituent_id = p_constituent_id"
FUNCTIONS = {
    "c360_rf_person_domain": f"""(p_constituent_id STRING, p_data_domain STRING) RETURNS BOOLEAN
        COMMENT 'Row filter: caller has an active authorised session for the constituent and the purpose permits the domain (statutory or current consent).'
        RETURN EXISTS (SELECT 1 FROM {G} g WHERE {ME} AND g.data_domain = p_data_domain AND g.visible)""",
    "c360_identity_full": f"""(p_constituent_id STRING) RETURNS BOOLEAN
        COMMENT 'True when the purpose of the active caller session allows full identity attributes for the constituent.'
        RETURN EXISTS (SELECT 1 FROM {G} g WHERE {ME} AND g.data_domain = 'identity' AND g.identity_level = 'full')""",
    "c360_signals_ok": f"""(p_constituent_id STRING, p_data_domain STRING) RETURNS BOOLEAN
        COMMENT 'AI-derived signals visible: domain visible and the purpose allows derived signals for it. p_data_domain = * means any domain.'
        RETURN EXISTS (SELECT 1 FROM {G} g WHERE {ME} AND g.visible AND g.signals_allowed
                       AND (p_data_domain = '*' OR g.data_domain = p_data_domain))""",
    "c360_rf_caseload": f"""(p_case_purpose STRING, p_owner_principal STRING) RETURNS BOOLEAN
        COMMENT 'Row filter: open cases the caller owns or that are unassigned, for purposes the caller is authorised for.'
        RETURN (p_owner_principal IS NULL OR p_owner_principal = session_user())
           AND EXISTS (SELECT 1 FROM {T('staff_purpose_authorisations')} a
                       WHERE a.principal = session_user() AND a.purpose_code = p_case_purpose AND {VALID_AUTH})""",
    "c360_rf_directory": f"""(p_case_purposes ARRAY<STRING>, p_verified BOOLEAN) RETURNS BOOLEAN
        COMMENT 'Row filter: constituents with an open case under a purpose the caller holds; front-door officers also see verified constituents.'
        RETURN EXISTS (SELECT 1 FROM {T('staff_purpose_authorisations')} a
                       WHERE a.principal = session_user() AND {VALID_AUTH}
                         AND (array_contains(p_case_purposes, a.purpose_code)
                              OR (a.purpose_code = 'general_enquiry' AND coalesce(p_verified, false))))""",
    "c360_mask_email": """(v STRING, p_constituent_id STRING) RETURNS STRING
        COMMENT 'Mask: email in full only at the full identity level.'
        RETURN CASE WHEN v IS NULL OR {ID} THEN v ELSE concat(left(v, 1), '***@', substring_index(v, '@', -1)) END""",
    "c360_mask_phone": """(v STRING, p_constituent_id STRING) RETURNS STRING
        COMMENT 'Mask: phone in full only at the full identity level.'
        RETURN CASE WHEN v IS NULL OR {ID} THEN v ELSE concat('*** *** ', right(regexp_replace(v, '[^0-9]', ''), 3)) END""",
    "c360_mask_street": """(v STRING, p_constituent_id STRING) RETURNS STRING
        COMMENT 'Mask: street address only at the full identity level (suburb stays visible).'
        RETURN CASE WHEN v IS NULL OR {ID} THEN v ELSE 'Withheld - minimum necessary' END""",
    "c360_mask_dob": """(v DATE, p_constituent_id STRING) RETURNS DATE
        COMMENT 'Mask: date of birth only at the full identity level (birth_year stays visible).'
        RETURN CASE WHEN {ID} THEN v ELSE CAST(NULL AS DATE) END""",
    "c360_mask_sig_str": """(v STRING, p_constituent_id STRING, p_data_domain STRING) RETURNS STRING
        COMMENT 'Mask: AI-derived text signal (sentiment, intent, tone, summary) unless the purpose allows derived signals.'
        RETURN CASE WHEN {SIG} THEN v ELSE CAST(NULL AS STRING) END""",
    "c360_mask_sig_int": """(v INT, p_constituent_id STRING, p_data_domain STRING) RETURNS INT
        COMMENT 'Mask: AI-derived urgency unless the purpose allows derived signals.'
        RETURN CASE WHEN {SIG} THEN v ELSE CAST(NULL AS INT) END""",
    "c360_mask_sig_arr": """(v ARRAY<STRING>, p_constituent_id STRING, p_data_domain STRING) RETURNS ARRAY<STRING>
        COMMENT 'Mask: AI-derived need codes unless the purpose allows derived signals.'
        RETURN CASE WHEN {SIG} THEN v ELSE CAST(NULL AS ARRAY<STRING>) END""",
    "c360_mask_dom_str": """(v STRING, p_constituent_id STRING, p_data_domain STRING) RETURNS STRING
        COMMENT 'Mask: identity-graph node details from a domain the purpose cannot see.'
        RETURN CASE WHEN {DOM} THEN v ELSE 'Restricted' END""",
}
subst = {"ID": f"{fn_name('c360_identity_full')}(p_constituent_id)",
         "SIG": f"{fn_name('c360_signals_ok')}(p_constituent_id, p_data_domain)",
         "DOM": f"{fn_name('c360_rf_person_domain')}(p_constituent_id, p_data_domain)"}
for name, body in FUNCTIONS.items():
    for k, v in subst.items():
        body = body.replace("{" + k + "}", v)
    owned_sql(f"CREATE OR REPLACE FUNCTION {fn_name(name)}{body}", name, "FUNCTION")
    print("function", name)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Policy-protected serving tables
# MAGIC
# MAGIC String literals in the policy argument lists (e.g. `'identity'`) are constant arguments.

# COMMAND ----------

SIG = lambda f: (f, ["constituent_id", "data_domain"])  # noqa: E731
SERVING = {
    "constituent_360": dict(
        comment="Journey timeline: one row per interaction for the constituent in the caller's active purpose session, "
                "limited to permitted data domains; AI signals masked unless the purpose allows them.",
        sql=f"""
          SELECT i.interaction_id, i.constituent_id, p.display_name, i.case_id, c.service_type, i.channel, i.channel_label,
                 i.direction, i.agency_code, i.data_domain, i.event_ts, i.subject, i.interaction_text, i.outcome,
                 i.handled_by, i.duration_seconds, i.attachment_name,
                 CAST(i.sentiment AS STRING) AS sentiment, CAST(i.intent AS STRING) AS intent, CAST(i.tone AS STRING) AS tone,
                 CAST(i.urgency_score AS INT) AS urgency_score, CAST(i.needs AS ARRAY<STRING>) AS needs,
                 CAST(i.summary AS STRING) AS summary, i.follow_up_required, i.is_repeat_contact, i.resolution_method
          FROM {T('gold_interactions')} i
          LEFT JOIN {T('gold_constituent_profile')} p USING (constituent_id)
          LEFT JOIN (SELECT case_id, service_type FROM {T('gold_cases')}) c USING (case_id)
          WHERE i.constituent_id IS NOT NULL""",
        row_filter=("c360_rf_person_domain", ["constituent_id", "data_domain"]),
        masks={"sentiment": SIG("c360_mask_sig_str"), "intent": SIG("c360_mask_sig_str"), "tone": SIG("c360_mask_sig_str"),
               "summary": SIG("c360_mask_sig_str"), "urgency_score": SIG("c360_mask_sig_int"),
               "needs": SIG("c360_mask_sig_arr")},
        classification="sensitive"),
    "constituent_profile": dict(
        comment="Profile header and facts for the constituent in the caller's active purpose session. "
                "DOB, email, phone and street need the full identity level; AI signals need a signals-enabled purpose.",
        sql=f"""
          SELECT * EXCEPT (dob, email, mobile, street, urgency_score, latest_tone, latest_sentiment, run_id),
                 CAST(dob AS DATE) AS dob, CAST(email AS STRING) AS email, CAST(mobile AS STRING) AS mobile,
                 CAST(street AS STRING) AS street, CAST(urgency_score AS INT) AS urgency_score,
                 CAST(latest_tone AS STRING) AS latest_tone, CAST(latest_sentiment AS STRING) AS latest_sentiment
          FROM {T('gold_constituent_profile')}""",
        row_filter=("c360_rf_person_domain", ["constituent_id", "'identity'"]),
        masks={"dob": ("c360_mask_dob", ["constituent_id"]), "email": ("c360_mask_email", ["constituent_id"]),
               "mobile": ("c360_mask_phone", ["constituent_id"]), "street": ("c360_mask_street", ["constituent_id"]),
               "urgency_score": ("c360_mask_sig_int", ["constituent_id", "'*'"]),
               "latest_tone": ("c360_mask_sig_str", ["constituent_id", "'*'"]),
               "latest_sentiment": ("c360_mask_sig_str", ["constituent_id", "'*'"])},
        classification="sensitive"),
    "constituent_need_signals": dict(
        comment="Needs & signals card: AI-derived needs per data domain, only where the purpose allows derived signals.",
        sql=f"SELECT * EXCEPT (run_id) FROM {T('gold_need_signals')}",
        row_filter=("c360_signals_ok", ["constituent_id", "data_domain"]), masks={},
        classification="protected_inferred"),
    "constituent_identity_graph": dict(
        comment="Identity graph tab: source records linked to the constituent. Nodes from domains the purpose cannot see are shown as Restricted.",
        sql=f"""SELECT * EXCEPT (run_id, source_record_id, source_system, source_display_name, agency_code),
                       CAST(source_record_id AS STRING) AS source_record_id, CAST(source_system AS STRING) AS source_system,
                       CAST(source_display_name AS STRING) AS source_display_name, CAST(agency_code AS STRING) AS agency_code
                FROM {T('gold_identity_graph')}""",
        row_filter=("c360_rf_person_domain", ["constituent_id", "'identity'"]),
        masks={c: ("c360_mask_dom_str", ["constituent_id", "data_domain"])
               for c in ("source_record_id", "source_system", "source_display_name", "agency_code")},
        classification="sensitive"),
    "constituent_directory": dict(
        comment="Constituents page: minimum fields for constituents with an open case under a purpose the caller holds "
                "(front-door officers also see verified constituents).",
        sql=f"""
          SELECT p.constituent_id, p.display_name, p.initials, p.birth_year, p.suburb, p.open_cases, p.priority_band,
                 CAST(p.has_verified_source AS BOOLEAN) AS has_verified_source, p.source_record_count, p.last_interaction_ts,
                 CAST(coalesce(cp.case_purposes, array()) AS ARRAY<STRING>) AS case_purposes
          FROM {T('gold_constituent_profile')} p
          LEFT JOIN (SELECT constituent_id, collect_set(case_purpose) AS case_purposes FROM {T('gold_cases')}
                     WHERE is_open AND case_purpose IS NOT NULL GROUP BY constituent_id) cp USING (constituent_id)""",
        row_filter=("c360_rf_directory", ["case_purposes", "has_verified_source"]), masks={},
        classification="protected"),
    "priority_queue": dict(
        comment="Priority queue: open journeys the caller owns or that are unassigned, for purposes the caller is authorised for.",
        sql=f"""
          SELECT c.case_id, c.constituent_id, p.display_name, p.initials, c.agency_code, c.data_domain, c.service_type,
                 c.case_status, c.sla_status, c.opened_at, c.due_at, c.days_open, c.priority_score, c.priority_band,
                 c.recommended_action, c.high_need_awaiting, c.awaiting_agency, c.last_contact_ts, c.contacts_7d,
                 c.repeat_contacts_7d, CAST(c.case_purpose AS STRING) AS case_purpose,
                 CAST(c.owner_principal AS STRING) AS owner_principal, sd.display_name AS owner_display_name
          FROM {T('gold_cases')} c
          LEFT JOIN {T('gold_constituent_profile')} p USING (constituent_id)
          LEFT JOIN {T('staff_directory')} sd ON sd.principal = c.owner_principal
          WHERE c.is_open AND c.constituent_id IS NOT NULL""",
        row_filter=("c360_rf_caseload", ["case_purpose", "owner_principal"]), masks={},
        classification="sensitive"),
    "consent_decisions": dict(
        comment="Consent & access page: current consent decisions for the constituent in the caller's active session.",
        sql=f"SELECT * EXCEPT (run_id) FROM {T('consent_current')}",
        row_filter=("c360_rf_person_domain", ["constituent_id", "'identity'"]), masks={},
        classification="protected"),
}


def grant_select(name: str) -> None:
    if not STAFF_GROUP:
        return
    assert_owned(name, "VIEW" if name.startswith("v_") else "TABLE")
    spark.sql(f"GRANT SELECT ON TABLE {T(name)} TO `{STAFF_GROUP}`")


for name, spec in SERVING.items():
    build = f"{name}__build"
    drop_owned(build)  # leftover from a failed run
    n = write_table(spark.sql(spec["sql"]), build, spec["comment"], layer="serving", classification=spec["classification"])
    fn, args = spec["row_filter"]
    spark.sql(f"ALTER TABLE {T(build)} SET ROW FILTER {fn_name(fn)} ON ({', '.join(args)})")
    for col, (mfn, margs) in spec["masks"].items():
        spark.sql(f"ALTER TABLE {T(build)} ALTER COLUMN `{col}` SET MASK {fn_name(mfn)} USING COLUMNS ({', '.join(margs)})")
    rename_owned(build, name)
    grant_select(name)
    print(f"{name}: {n} rows | row filter {fn} | {len(spec['masks'])} masks")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Aggregates with small-cell suppression
# MAGIC
# MAGIC Counts between 1 and `small_cell_threshold - 1` are suppressed (NULL) for agency-level cells; rates are
# MAGIC suppressed when their denominator is below the threshold. `suppressed` flags any affected row.

# COMMAND ----------


def sup(col: str, denom: str = None) -> str:
    d = denom or col
    return f"IF({d} BETWEEN 1 AND {K - 1}, NULL, {col}) AS {col.split('.')[-1]}"


kpi_counts = ["open_journeys", "opened_today", "closed_today", "open_journeys_7d_ago", "high_need_awaiting",
              "high_need_consent_restricted", "overdue_journeys", "inbound_contacts_7d"]
AGG = {
    "service_kpis": (f"""
        SELECT snapshot_date, agency_code, {', '.join(sup(c) for c in kpi_counts)},
               IF(inbound_contacts_7d < {K}, NULL, repeat_contact_7d_rate) AS repeat_contact_7d_rate,
               IF(inbound_contacts_7d < {K}, NULL, repeat_contact_prev_7d_rate) AS repeat_contact_prev_7d_rate,
               repeat_contact_target, identity_confidence, multi_source_constituents,
               ({' OR '.join(f'{c} BETWEEN 1 AND {K - 1}' for c in kpi_counts)} OR inbound_contacts_7d < {K}) AS suppressed
        FROM {T('gold_service_kpis')}""",
        "KPI strip (open journeys, repeat contact 7d, high-need awaiting, identity confidence) per agency and ALL. Small cells suppressed."),
    "repeat_contact_by_service": (f"""
        SELECT week_start, agency_code, service_line, channel_label,
               IF(inbound_contacts < {K}, NULL, inbound_contacts) AS inbound_contacts,
               IF(inbound_contacts < {K}, NULL, repeat_contacts) AS repeat_contacts,
               IF(inbound_contacts < {K}, NULL, repeat_contact_rate) AS repeat_contact_rate,
               inbound_contacts < {K} AS suppressed
        FROM {T('gold_repeat_contact_by_service')}""",
        "Service insights: weekly repeat contact by service line and channel. Small cells suppressed."),
    "operational_signals": (f"""
        SELECT week_start, agency_code, data_domain, intent,
               IF(interactions < {K}, NULL, interactions) AS interactions,
               IF(interactions < {K}, NULL, negative_share) AS negative_share,
               IF(interactions < {K}, NULL, avg_urgency) AS avg_urgency,
               IF(interactions < {K}, NULL, follow_up_share) AS follow_up_share,
               IF(interactions < {K}, NULL, repeat_share) AS repeat_share,
               interactions < {K} AS suppressed
        FROM {T('gold_operational_signals')}""",
        "Service insights: weekly operational signals by agency, domain and AI intent. Small cells suppressed."),
}
for name, (sql, comment) in AGG.items():
    n = write_table(spark.sql(sql), name, comment, column_comments={"suppressed": f"At least one cell below {K} was suppressed."},
                    layer="serving", classification="official")
    grant_select(name)
    print(f"{name}: {n} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Caller-scoped views

# COMMAND ----------

VIEWS = {
    "v_my_session": (f"""
        SELECT g.session_id, g.purpose_code, rp.display_name AS purpose_name, g.case_id, g.subject_constituent_id,
               g.started_at, g.expires_at,
               max(IF(g.data_domain = 'identity', g.identity_level, NULL)) AS identity_level,
               count_if(g.data_domain <> 'identity' AND g.visible) AS visible_domains,
               count_if(g.data_domain <> 'identity' AND NOT g.visible) AS restricted_domains,
               IF(max(IF(g.data_domain = 'identity', g.identity_level, NULL)) = 'full', 0, 4) AS masked_identity_fields
        FROM {T('c360_v_active_grants')} g JOIN {T('ref_purposes')} rp USING (purpose_code)
        WHERE g.principal = session_user()
        GROUP BY ALL""", "Caller's active purpose-of-use session: purpose, subject, expiry and masked field count (policy toast)."),
    "v_my_access_scope": (f"""
        SELECT g.subject_constituent_id AS constituent_id, g.purpose_code, g.data_domain, dd.display_name AS domain_name,
               g.access_rule, g.visible,
               CASE WHEN g.access_rule = 'deny' THEN g.rationale
                    WHEN g.access_rule = 'allow' THEN g.rationale
                    WHEN g.visible THEN concat('Consent granted', coalesce(concat(' - expires ', date_format(g.consent_expires_at, 'd MMM yyyy')), ''))
                    WHEN g.consent_decision IS NOT NULL THEN concat('Consent ', g.consent_decision)
                    ELSE 'No consent on record' END AS reason,
               g.consent_expires_at, g.signals_allowed AND g.visible AS signals_visible, g.expires_at AS session_expires_at
        FROM {T('c360_v_active_grants')} g LEFT JOIN {T('ref_data_domains')} dd USING (data_domain)
        WHERE g.principal = session_user()""", "Current access scope card: per data domain decision and reason for the caller's active session."),
    "v_my_access_audit": (f"""
        SELECT e.event_ts, e.principal, sd.display_name AS officer_name, e.constituent_id, e.case_id, e.purpose_code,
               e.event_type, e.decision, e.detail
        FROM {T('access_audit_events')} e LEFT JOIN {T('staff_directory')} sd ON sd.principal = e.principal
        WHERE e.principal = session_user()
           OR e.constituent_id IN (SELECT g.subject_constituent_id FROM {T('c360_v_active_grants')} g WHERE g.principal = session_user())""",
        "Access audit tab: the caller's own events plus every access event for the constituent in the caller's active session."),
}
for name, (sql, comment) in VIEWS.items():
    owned_sql(f"CREATE OR REPLACE VIEW {T(name)} COMMENT {sql_str(comment)} AS {sql}", name, "VIEW")
    grant_select(name)
    print("view", name)

# Data lineage page: UC lineage system table, scoped to this schema (best effort - needs system table access).
try:
    owned_sql(f"""CREATE OR REPLACE VIEW {T('v_lineage_edges')}
                  COMMENT 'Data lineage page: table-to-table edges inside this use case schema (system.access.table_lineage, 90 days).'
                  AS SELECT source_table_full_name, target_table_full_name, max(event_time) AS last_seen,
                            count(*) AS events
                     FROM system.access.table_lineage
                     WHERE target_table_catalog = {sql_str(catalog)} AND target_table_schema = {sql_str(schema)}
                       AND source_table_full_name IS NOT NULL AND event_date >= current_date() - INTERVAL 90 DAYS
                     GROUP BY ALL""", "v_lineage_edges", "VIEW")
    grant_select("v_lineage_edges")
except Exception as exc:  # noqa: BLE001
    print(f"v_lineage_edges skipped: {str(exc).splitlines()[0][:160]}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Procedures (`SQL SECURITY DEFINER`)
# MAGIC
# MAGIC Officers hold `EXECUTE` only; the procedures write governance tables on their behalf and audit
# MAGIC every decision, including refusals.

# COMMAND ----------

AUDIT = f"INSERT INTO {T('access_audit_events')} (event_id, event_ts, principal, constituent_id, case_id, purpose_code, event_type, decision, detail, source)"
ACTIVE = "principal = session_user() AND ended_at IS NULL AND expires_at > current_timestamp()"
PROCEDURES = {
    "start_access_session": f"""(
          IN p_purpose STRING, IN p_case_id STRING DEFAULT NULL, IN p_constituent_id STRING DEFAULT NULL,
          IN p_justification STRING DEFAULT NULL)
        LANGUAGE SQL SQL SECURITY DEFINER MODIFIES SQL DATA
        COMMENT 'Declare a purpose of use for one case (or a verified constituent for non-case purposes). Ends any prior session.'
        AS BEGIN
          DECLARE v_requires BOOLEAN;
          DECLARE v_subject STRING;
          DECLARE v_sid STRING DEFAULT uuid();
          SET v_requires = (SELECT max(requires_case) FROM {T('ref_purposes')} WHERE purpose_code = p_purpose);
          IF v_requires IS NULL THEN
            SIGNAL SQLSTATE '22023' SET MESSAGE_TEXT = 'Unknown purpose of use';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM {T('staff_purpose_authorisations')} a
                         WHERE a.principal = session_user() AND a.purpose_code = p_purpose AND {VALID_AUTH}) THEN
            {AUDIT} VALUES (uuid(), current_timestamp(), session_user(), p_constituent_id, p_case_id, p_purpose,
                            'session_start', 'denied', 'Not authorised for this purpose', 'start_access_session');
            SIGNAL SQLSTATE '42501' SET MESSAGE_TEXT = 'You are not authorised to act under this purpose of use';
          END IF;
          IF v_requires THEN
            SET v_subject = (SELECT max(constituent_id) FROM {T('gold_cases')}
                             WHERE case_id = p_case_id AND case_purpose = p_purpose AND is_open
                               AND (owner_principal IS NULL OR owner_principal = session_user()));
          ELSE
            SET v_subject = (SELECT max(constituent_id) FROM {T('gold_constituent_profile')}
                             WHERE constituent_id = p_constituent_id AND has_verified_source);
          END IF;
          IF v_subject IS NULL THEN
            {AUDIT} VALUES (uuid(), current_timestamp(), session_user(), p_constituent_id, p_case_id, p_purpose,
                            'session_start', 'denied', 'Case not in caller caseload, or constituent not verified', 'start_access_session');
            SIGNAL SQLSTATE '42501' SET MESSAGE_TEXT = 'The case is not in your caseload for this purpose (or the constituent is not verified)';
          END IF;
          UPDATE {T('access_sessions')} SET ended_at = current_timestamp(), end_reason = 'superseded' WHERE {ACTIVE};
          INSERT INTO {T('access_sessions')} (session_id, principal, purpose_code, case_id, subject_constituent_id, justification,
                                              started_at, expires_at, ended_at, end_reason)
            VALUES (v_sid, session_user(), p_purpose, p_case_id, v_subject, p_justification, current_timestamp(),
                    current_timestamp() + INTERVAL {SESSION_MINUTES} MINUTES, NULL, NULL);
          {AUDIT} VALUES (uuid(), current_timestamp(), session_user(), v_subject, p_case_id, p_purpose,
                          'session_start', 'allowed', p_justification, 'start_access_session');
          SELECT v_sid AS session_id, v_subject AS constituent_id, p_purpose AS purpose_code,
                 current_timestamp() + INTERVAL {SESSION_MINUTES} MINUTES AS expires_at;
        END""",
    "end_access_session": f"""()
        LANGUAGE SQL SQL SECURITY DEFINER MODIFIES SQL DATA
        COMMENT 'End the active purpose session of the caller.'
        AS BEGIN
          {AUDIT} SELECT uuid(), current_timestamp(), session_user(), subject_constituent_id, case_id, purpose_code,
                         'session_end', 'allowed', NULL, 'end_access_session'
                  FROM {T('access_sessions')} WHERE {ACTIVE};
          UPDATE {T('access_sessions')} SET ended_at = current_timestamp(), end_reason = 'ended_by_user' WHERE {ACTIVE};
        END""",
    "log_access_event": f"""(IN p_event_type STRING, IN p_detail STRING DEFAULT NULL)
        LANGUAGE SQL SQL SECURITY DEFINER MODIFIES SQL DATA
        COMMENT 'Record an application access event (record opened, restricted attempt, assistant briefing) against the active session.'
        AS BEGIN
          IF NOT EXISTS (SELECT 1 FROM {T('access_sessions')} WHERE {ACTIVE}) THEN
            {AUDIT} VALUES (uuid(), current_timestamp(), session_user(), NULL, NULL, NULL, p_event_type, 'no_session', p_detail, 'log_access_event');
          ELSE
            {AUDIT} SELECT uuid(), current_timestamp(), session_user(), subject_constituent_id, case_id, purpose_code,
                           p_event_type, 'logged', p_detail, 'log_access_event'
                    FROM {T('access_sessions')} WHERE {ACTIVE};
          END IF;
        END""",
    "request_record_change": f"""(IN p_change_type STRING, IN p_details STRING, IN p_reason_code STRING)
        LANGUAGE SQL SQL SECURITY DEFINER MODIFIES SQL DATA
        COMMENT 'Stage a record change (contact details, consent change, ...) for review before write-back to the owning system.'
        AS BEGIN
          DECLARE v_rid STRING DEFAULT uuid();
          IF NOT EXISTS (SELECT 1 FROM {T('access_sessions')} WHERE {ACTIVE}) THEN
            SIGNAL SQLSTATE '42501' SET MESSAGE_TEXT = 'Start an access session for the constituent before requesting a change';
          END IF;
          INSERT INTO {T('record_change_requests')} (request_id, requested_at, principal, purpose_code, constituent_id, case_id,
                                                     change_type, details, reason_code, status, reviewed_by, reviewed_at)
            SELECT v_rid, current_timestamp(), session_user(), purpose_code, subject_constituent_id, case_id,
                   p_change_type, p_details, p_reason_code, 'pending_review', NULL, NULL
            FROM {T('access_sessions')} WHERE {ACTIVE};
          {AUDIT} SELECT uuid(), current_timestamp(), session_user(), subject_constituent_id, case_id, purpose_code,
                         'record_change_requested', 'staged', concat(p_change_type, ': ', p_reason_code), 'request_record_change'
                  FROM {T('access_sessions')} WHERE {ACTIVE};
          SELECT v_rid AS request_id, 'pending_review' AS status;
        END""",
    "record_identity_decision": f"""(IN p_decision STRING, IN p_source_record_id_l STRING, IN p_source_record_id_r STRING,
                                     IN p_reason STRING)
        LANGUAGE SQL SQL SECURITY DEFINER MODIFIES SQL DATA
        COMMENT 'Merge / split / review decision on two source records of the constituent in session; honoured by the next entity resolution run.'
        AS BEGIN
          IF p_decision NOT IN ('must_link', 'cannot_link') THEN
            SIGNAL SQLSTATE '22023' SET MESSAGE_TEXT = 'decision must be must_link or cannot_link';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM {T('gold_identity_graph')} ig JOIN {T('access_sessions')} s
                           ON s.subject_constituent_id = ig.constituent_id
                         WHERE s.principal = session_user() AND s.ended_at IS NULL AND s.expires_at > current_timestamp()
                           AND ig.source_record_id = p_source_record_id_l) THEN
            SIGNAL SQLSTATE '42501' SET MESSAGE_TEXT = 'The left record must belong to the constituent in your active session';
          END IF;
          INSERT INTO {T('identity_review_decisions')} (decision_id, decided_at, principal, decision, source_record_id_l,
                                                        source_record_id_r, reason, active)
            VALUES (uuid(), current_timestamp(), session_user(), p_decision, p_source_record_id_l, p_source_record_id_r, p_reason, true);
          {AUDIT} SELECT uuid(), current_timestamp(), session_user(), subject_constituent_id, case_id, purpose_code,
                         'identity_decision', p_decision, concat(p_source_record_id_l, ' / ', p_source_record_id_r), 'record_identity_decision'
                  FROM {T('access_sessions')} WHERE {ACTIVE};
        END""",
}
for name, body in PROCEDURES.items():
    owned_sql(f"CREATE OR REPLACE PROCEDURE {fn_name(name)}{body}", name, "PROCEDURE")
    if STAFF_GROUP:
        spark.sql(f"GRANT EXECUTE ON PROCEDURE {fn_name(name)} TO `{STAFF_GROUP}`")
    print("procedure", name)

if STAFF_GROUP:
    # schema-level USE only; never schema-level SELECT. USE CATALOG is granted by the catalog owner, not this pipeline.
    spark.sql(f"GRANT USE SCHEMA ON SCHEMA `{catalog}`.`{schema}` TO `{STAFF_GROUP}`")

# COMMAND ----------

pol = {r.table_name: r for r in spark.sql(f"""
    SELECT table_name, count(*) AS masks FROM `{catalog}`.information_schema.column_masks
    WHERE table_schema = :s GROUP BY table_name""", args={"s": schema}).collect()}
rf = {r.table_name for r in spark.sql(f"""SELECT table_name FROM `{catalog}`.information_schema.row_filters
                                          WHERE table_schema = :s""", args={"s": schema}).collect()}
checks = []
for name, spec in SERVING.items():
    checks.append((f"{name}_row_filter_attached", name in rf, "critical", name in rf, True))
    want = len(spec["masks"])
    got = pol[name].masks if name in pol else 0
    checks.append((f"{name}_masks_attached", got == want, "critical", got, want))
left = [n for n in SERVING if table_exists(f"{n}__build")]
checks.append(("no_build_tables_left", not left, "critical", left, []))
failed = record_checks("07_consent_and_serving", run_id, checks)
assert not failed, f"critical checks failed: {failed}"
