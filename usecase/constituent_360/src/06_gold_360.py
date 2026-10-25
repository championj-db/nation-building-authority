# Databricks notebook source
# MAGIC %md
# MAGIC # 06 Gold 360
# MAGIC
# MAGIC Builds the **unfiltered** gold layer (pipeline-only; staff read the policy-protected serving copies
# MAGIC built in `07_consent_and_serving`):
# MAGIC
# MAGIC | Table | Feeds (design) |
# MAGIC | --- | --- |
# MAGIC | `consent_current` | Consent & access page, row filter consent check |
# MAGIC | `gold_interactions` | Journey timeline, Interactions page, case briefing assistant |
# MAGIC | `gold_cases` | Priority queue, recommended follow-up, KPI cards |
# MAGIC | `gold_constituent_profile` | Profile header + facts, Constituents page |
# MAGIC | `gold_need_signals` | Needs & signals card / tab |
# MAGIC | `gold_identity_graph` | Identity graph tab |
# MAGIC | `gold_service_kpis` | KPI strip (open journeys, repeat contact, high-need awaiting, identity confidence) |
# MAGIC | `gold_repeat_contact_by_service`, `gold_operational_signals` | Service insights page |
# MAGIC
# MAGIC Interactions are resolved to constituents by (in order) quoted case, quoted agency reference, then
# MAGIC contact point. A contact point shared by several constituents (household landline) is left
# MAGIC `ambiguous_contact` rather than guessed.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("run_id", "")
dbutils.widgets.text("repeat_contact_target", "0.15")
dbutils.widgets.text("due_soon_days", "3")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
run_id = dbutils.widgets.get("run_id") or None
REPEAT_TARGET = float(dbutils.widgets.get("repeat_contact_target"))
DUE_SOON = int(dbutils.widgets.get("due_soon_days"))

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

run_id = run_id or new_run_id("GOLD")
# "now" for the synthetic world = the latest landed delivery, so a replayed demo stays coherent
as_of = get_control("last_landed_ts")
AS_OF = f"to_timestamp({sql_str(as_of)})" if as_of else "current_timestamp()"
print("as of", spark.sql(f"SELECT {AS_OF}").first()[0])
T = fqn  # brevity in SQL
purpose_of_domain = sql_map(DOMAIN_PURPOSE)


def publish(sql: str, name: str, comment: str, cols: dict = None, classification: str = "protected") -> int:
    return write_table(spark.sql(sql).withColumn("run_id", F.lit(run_id)), name, comment, column_comments=cols,
                       layer="gold", classification=classification)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Consent resolved to constituents

# COMMAND ----------

publish(f"""
  WITH e AS (
    SELECT x.constituent_id, c.* EXCEPT (_delivery)
    FROM {T('silver_consent_events')} c JOIN {T('silver_identity_xref')} x ON x.source_record_id = c.client_record_id)
  SELECT constituent_id, purpose_code, data_domain,
         max_by(decision, captured_at) AS decision,
         max(captured_at) AS decided_at,
         max_by(expires_at, captured_at) AS expires_at,
         max_by(agency_code, captured_at) AS captured_by_agency,
         max_by(capture_channel, captured_at) AS capture_channel,
         max_by(consent_event_id, captured_at) AS consent_event_id,
         max_by(notice_version, captured_at) AS notice_version,
         max_by(decision, captured_at) = 'granted' AND coalesce(max_by(expires_at, captured_at) > {AS_OF}, true) AS is_active
  FROM e GROUP BY constituent_id, purpose_code, data_domain""",
        "consent_current", "Latest consent decision per constituent x purpose of use x data domain (resolved through entity resolution).",
        {"is_active": "Consent is granted and unexpired as of the pipeline run.",
         "decision": "Latest decision: granted | declined | withdrawn."})

# COMMAND ----------

# MAGIC %md
# MAGIC ## Interactions resolved to constituents and journeys

# COMMAND ----------

publish(f"""
  WITH xr AS (SELECT source_record_id, constituent_id FROM {T('silver_identity_xref')}),
  case_c AS (SELECT c.case_id, x.constituent_id FROM {T('silver_cases')} c JOIN xr x ON x.source_record_id = c.client_record_id),
  i AS (SELECT * FROM {T('silver_interactions')}),
  by_case AS (SELECT i.interaction_id, cc.constituent_id FROM i JOIN case_c cc ON cc.case_id = i.case_ref),
  by_ref AS (SELECT i.interaction_id, x.constituent_id FROM i JOIN xr x ON x.source_record_id = i.agency_ref_record_id),
  by_cp AS (SELECT i.interaction_id, array_sort(collect_set(x.constituent_id)) AS cs
            FROM i JOIN {T('silver_contact_points')} cp ON cp.contact_type = i.contact_type AND cp.contact_value = i.contact_value
            JOIN xr x ON x.source_record_id = cp.source_record_id GROUP BY i.interaction_id),
  r AS (
    SELECT i.*, coalesce(bc.constituent_id, br.constituent_id, IF(size(cp.cs) = 1, cp.cs[0], NULL)) AS constituent_id,
           CASE WHEN bc.constituent_id IS NOT NULL THEN 'case_reference' WHEN br.constituent_id IS NOT NULL THEN 'agency_reference'
                WHEN size(cp.cs) = 1 THEN 'contact_point' WHEN size(cp.cs) > 1 THEN 'ambiguous_contact' ELSE 'unresolved' END AS resolution_method
    FROM i LEFT JOIN by_case bc USING (interaction_id) LEFT JOIN by_ref br USING (interaction_id) LEFT JOIN by_cp cp USING (interaction_id)),
  cases AS (SELECT c.*, x.constituent_id FROM {T('silver_cases')} c JOIN xr x ON x.source_record_id = c.client_record_id),
  inferred AS (   -- an interaction without a quoted case belongs to the constituent's open case in that domain at the time
    SELECT r.interaction_id, max_by(c.case_id, c.opened_at) AS case_id
    FROM r JOIN cases c ON c.constituent_id = r.constituent_id AND c.data_domain = r.data_domain
                       AND c.opened_at <= r.event_ts AND (c.closed_at IS NULL OR c.closed_at >= r.event_ts)
    WHERE r.case_ref IS NULL GROUP BY r.interaction_id),
  j AS (
    SELECT r.*, coalesce(r.case_ref, inf.case_id) AS case_id, s.sentiment, s.intent, s.tone, s.urgency_score, s.needs,
           s.summary, s.follow_up_required
    FROM r LEFT JOIN inferred inf USING (interaction_id)
    LEFT JOIN {T('ai_interaction_signals')} s ON s.interaction_id = r.interaction_id AND s.text_hash = r.text_hash)
  SELECT interaction_id, constituent_id, resolution_method, case_id, channel, channel_label, direction, agency_code, data_domain,
         event_ts, subject, interaction_text, outcome, handled_by, duration_seconds, attachment_name,
         sentiment, intent, tone, urgency_score, needs, summary, follow_up_required,
         direction = 'inbound' AND constituent_id IS NOT NULL AND
           coalesce(event_ts - lag(event_ts) OVER (PARTITION BY constituent_id, data_domain, direction ORDER BY event_ts)
                    <= INTERVAL 7 DAYS, false) AS is_repeat_contact
  FROM j""", "gold_interactions",
        "Every interaction resolved to a constituent and journey, with AI signals. Unfiltered - staff read constituent_360.",
        {"resolution_method": "case_reference | agency_reference | contact_point | ambiguous_contact | unresolved",
         "is_repeat_contact": "Inbound contact within 7 days of the constituent's previous inbound contact in the same domain.",
         "interaction_text": "Transcript, message or note. Personal information."},
        classification="sensitive")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cases (journeys), priority and recommended action

# COMMAND ----------

publish(f"""
  WITH c AS (SELECT c.* EXCEPT (_delivery), x.constituent_id FROM {T('silver_cases')} c
             LEFT JOIN {T('silver_identity_xref')} x ON x.source_record_id = c.client_record_id),
  gi AS (SELECT * FROM {T('gold_interactions')} WHERE case_id IS NOT NULL),
  m AS (
    SELECT case_id,
           max(event_ts) AS last_contact_ts,
           max(IF(direction = 'inbound', event_ts, NULL)) AS last_inbound_ts,
           max(IF(direction = 'outbound', event_ts, NULL)) AS last_outbound_ts,
           count_if(direction = 'inbound' AND event_ts > {AS_OF} - INTERVAL 7 DAYS) AS contacts_7d,
           count_if(is_repeat_contact AND event_ts > {AS_OF} - INTERVAL 7 DAYS) AS repeat_contacts_7d,
           count(*) AS interactions_total,
           max_by(sentiment, IF(direction = 'inbound', event_ts, NULL)) AS latest_sentiment,
           max_by(tone, IF(direction = 'inbound', event_ts, NULL)) AS latest_tone,
           max_by(intent, IF(direction = 'inbound', event_ts, NULL)) AS latest_intent,
           max(IF(event_ts > {AS_OF} - INTERVAL 14 DAYS, urgency_score, NULL)) AS max_urgency_14d,
           array_sort(array_distinct(flatten(collect_list(IF(event_ts > {AS_OF} - INTERVAL 30 DAYS, needs, array()))))) AS needs_30d,
           max(IF(intent = 'document_submission', event_ts, NULL)) AS last_document_ts,
           max_by(summary, IF(direction = 'inbound', event_ts, NULL)) AS latest_summary
    FROM gi GROUP BY case_id),
  b AS (
    SELECT c.*, m.* EXCEPT (case_id),
           c.case_status NOT IN ('closed', 'withdrawn', 'approved', 'declined') AS is_open,
           datediff({AS_OF}, c.opened_at) AS days_open,
           CASE WHEN c.case_status IN ('closed', 'withdrawn', 'approved', 'declined') THEN 'closed'
                WHEN c.due_at < {AS_OF} THEN 'overdue'
                WHEN c.due_at < {AS_OF} + make_interval(0, 0, 0, {DUE_SOON}, 0, 0, 0) THEN 'due_soon' ELSE 'on_track' END AS sla_status,
           coalesce(m.last_inbound_ts > coalesce(m.last_outbound_ts, c.last_updated_at, c.opened_at), false) AS awaiting_agency
    FROM c LEFT JOIN m USING (case_id)),
  s AS (
    SELECT *, round(0.35 * coalesce(max_urgency_14d, 0) / 100
                    + 0.20 * IF(coalesce(repeat_contacts_7d, 0) > 0, 1, 0)
                    + 0.20 * CASE sla_status WHEN 'overdue' THEN 1 WHEN 'due_soon' THEN 0.6 ELSE 0 END
                    + 0.15 * IF(latest_sentiment IN ('negative', 'mixed') OR latest_tone IN ('frustrated', 'distressed'), 1, 0)
                    + 0.10 * least(coalesce(size(needs_30d), 0), 3) / 3, 3) AS priority_score
    FROM b)
  SELECT *,
         CASE WHEN NOT is_open THEN 'none' WHEN priority_score >= 0.55 THEN 'high' WHEN priority_score >= 0.30 THEN 'medium' ELSE 'low' END AS priority_band,
         is_open AND priority_score >= 0.55 AND (awaiting_agency OR case_status IN ('awaiting_evidence', 'in_review')) AS high_need_awaiting,
         CASE WHEN NOT is_open THEN NULL
              WHEN last_document_ts IS NOT NULL AND case_status IN ('awaiting_evidence', 'in_review')
                   AND last_document_ts > coalesce(last_outbound_ts, opened_at) THEN 'Review the newly submitted evidence and confirm receipt'
              WHEN coalesce(repeat_contacts_7d, 0) > 0 THEN 'Call back today - repeat contact within 7 days'
              WHEN sla_status = 'overdue' THEN 'Escalate - case is past its due date'
              WHEN latest_tone = 'distressed' OR coalesce(max_urgency_14d, 0) >= 80 THEN 'Contact the constituent and check immediate support needs'
              WHEN awaiting_agency THEN 'Respond to the latest contact'
              WHEN sla_status = 'due_soon' THEN 'Progress the case before it falls due'
              ELSE 'No action needed - monitor' END AS recommended_action,
         try_element_at({purpose_of_domain}, data_domain) AS case_purpose
  FROM s""", "gold_cases",
        "Service journeys (cases) with contact metrics, SLA state, AI-informed priority and recommended action. Unfiltered.",
        {"priority_score": "0-1 rules score: urgency, repeat contact, SLA, negative sentiment/tone, breadth of needs.",
         "priority_band": "high | medium | low | none (closed).",
         "high_need_awaiting": "Open high-priority case waiting on the agency (latest contact unanswered, or evidence awaiting review).",
         "recommended_action": "Rule-based next best action shown as 'Recommended follow-up'.",
         "case_purpose": "Purpose of use an officer declares to work this case.",
         "awaiting_agency": "The constituent's latest inbound contact has not been answered."},
        classification="sensitive")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Profile, needs and identity graph

# COMMAND ----------

publish(f"""
  WITH gi AS (SELECT constituent_id, count(*) AS interactions_total,
                     count_if(event_ts > {AS_OF} - INTERVAL 90 DAYS) AS interactions_90d,
                     max(event_ts) AS last_interaction_ts, max_by(channel_label, event_ts) AS last_channel,
                     count_if(is_repeat_contact AND event_ts > {AS_OF} - INTERVAL 30 DAYS) AS repeat_contacts_30d,
                     max(IF(event_ts > {AS_OF} - INTERVAL 14 DAYS, urgency_score, NULL)) AS urgency_score,
                     max_by(tone, IF(direction = 'inbound', event_ts, NULL)) AS latest_tone,
                     max_by(sentiment, IF(direction = 'inbound', event_ts, NULL)) AS latest_sentiment
              FROM {T('gold_interactions')} WHERE constituent_id IS NOT NULL GROUP BY constituent_id),
  gc AS (SELECT constituent_id, count_if(is_open) AS open_cases, collect_set(IF(is_open, service_type, NULL)) AS open_services,
                max_by(recommended_action, IF(is_open, priority_score, NULL)) AS recommended_action,
                max(IF(is_open, priority_score, NULL)) AS priority_score,
                max_by(priority_band, IF(is_open, priority_score, NULL)) AS priority_band
         FROM {T('gold_cases')} WHERE constituent_id IS NOT NULL GROUP BY constituent_id)
  SELECT p.constituent_id, p.display_name, p.given_name, p.family_name, p.initials, p.dob, p.birth_year,
         CAST(floor(months_between({AS_OF}, p.dob) / 12) AS INT) AS age, p.email, p.mobile, p.street, p.suburb, p.postcode,
         p.identity_confidence, p.source_record_count, p.has_verified_source, p.source_systems, p.data_domains,
         coalesce(gc.open_cases, 0) AS open_cases, gc.open_services, gc.priority_score, gc.priority_band, gc.recommended_action,
         coalesce(gi.interactions_total, 0) AS interactions_total, coalesce(gi.interactions_90d, 0) AS interactions_90d,
         gi.last_interaction_ts, gi.last_channel, coalesce(gi.repeat_contacts_30d, 0) AS repeat_contacts_30d,
         gi.urgency_score, gi.latest_tone, gi.latest_sentiment
  FROM {T('silver_constituents')} p LEFT JOIN gi USING (constituent_id) LEFT JOIN gc USING (constituent_id)""",
        "gold_constituent_profile", "One row per resolved constituent: golden record, journeys, contact summary and signals. Unfiltered.",
        {"urgency_score": "Highest AI urgency in the last 14 days. Inferred personal information.",
         "recommended_action": "Recommended follow-up for the highest-priority open case."},
        classification="sensitive")

need_label = sql_map(dict(NEEDS))
publish(f"""
  WITH x AS (SELECT constituent_id, data_domain, event_ts, urgency_score, interaction_id, explode(needs) AS need_code
             FROM {T('gold_interactions')} WHERE constituent_id IS NOT NULL AND needs IS NOT NULL
               AND event_ts > {AS_OF} - INTERVAL 90 DAYS)
  SELECT constituent_id, data_domain, need_code, try_element_at({need_label}, need_code) AS need_label,
         count(*) AS evidence_count, max(event_ts) AS last_seen_ts, round(avg(urgency_score), 1) AS avg_urgency,
         CASE WHEN count(*) >= 3 OR max(urgency_score) >= 75 THEN 'high' WHEN count(*) = 2 OR max(urgency_score) >= 50 THEN 'medium'
              ELSE 'low' END AS strength,
         transform(slice(array_sort(collect_list(named_struct('ts', event_ts, 'id', interaction_id)),
                                    (a, b) -> CASE WHEN a.ts > b.ts THEN -1 WHEN a.ts < b.ts THEN 1 ELSE 0 END), 1, 3), e -> e.id)
           AS evidence_interaction_ids
  FROM x GROUP BY constituent_id, data_domain, need_code""",
        "gold_need_signals", "AI-derived need signals per constituent x data domain over 90 days, with evidence. Inferred personal information.",
        {"strength": "high | medium | low from evidence volume and urgency.",
         "evidence_interaction_ids": "Most recent interactions evidencing the need."},
        classification="protected_inferred")

publish(f"""
  SELECT l.constituent_id, l.source_record_id, l.source_system, l.source_display_name, l.agency_code, l.data_domain,
         l.link_state, round(l.link_probability, 3) AS link_probability, l.linked_constituent_id,
         s.identity_assurance, s.updated_at AS record_updated_at
  FROM {T('silver_identity_links')} l JOIN {T('silver_source_identities')} s USING (source_record_id)""",
        "gold_identity_graph", "Identity graph per constituent: linked source records and review-band candidates.",
        {"link_state": "verified | anchor | matched | review"})

# COMMAND ----------

# MAGIC %md
# MAGIC ## KPIs and service insights (unsuppressed - serving applies small-cell suppression)

# COMMAND ----------

consent_rules = spark.createDataFrame([(p, d) for p, d, rule, *_ in PURPOSE_DOMAIN_POLICY if rule == "consent"],
                                      "purpose_code string, data_domain string")
consent_rules.createOrReplaceTempView("c360_consent_rules")
publish(f"""
  WITH c0 AS (SELECT * FROM {T('gold_cases')}),
  restricted AS (   -- high-need cases where the constituent has history in a consent domain the purpose cannot yet see
    SELECT DISTINCT c0.case_id FROM c0
    JOIN c360_consent_rules r ON r.purpose_code = c0.case_purpose
    JOIN {T('gold_interactions')} i ON i.constituent_id = c0.constituent_id AND i.data_domain = r.data_domain
    LEFT JOIN {T('consent_current')} cc ON cc.constituent_id = c0.constituent_id AND cc.purpose_code = r.purpose_code
                                    AND cc.data_domain = r.data_domain AND cc.is_active
    WHERE c0.high_need_awaiting AND cc.constituent_id IS NULL),
  c AS (SELECT c0.*, rs.case_id IS NOT NULL AS consent_restricted FROM c0 LEFT JOIN restricted rs USING (case_id)),
  i7 AS (SELECT agency_code, count_if(is_repeat_contact) AS rep, count(*) AS n FROM {T('gold_interactions')}
         WHERE direction = 'inbound' AND event_ts > {AS_OF} - INTERVAL 7 DAYS GROUP BY agency_code),
  i7p AS (SELECT agency_code, count_if(is_repeat_contact) AS rep, count(*) AS n FROM {T('gold_interactions')}
          WHERE direction = 'inbound' AND event_ts > {AS_OF} - INTERVAL 14 DAYS AND event_ts <= {AS_OF} - INTERVAL 7 DAYS GROUP BY agency_code),
  k AS (
    SELECT coalesce(agency_code, 'ALL') AS agency_code,
           count_if(is_open) AS open_journeys,
           count_if(opened_at > date_trunc('DAY', {AS_OF})) AS opened_today,
           count_if(closed_at > date_trunc('DAY', {AS_OF})) AS closed_today,
           count_if(opened_at <= {AS_OF} - INTERVAL 7 DAYS AND (closed_at IS NULL OR closed_at > {AS_OF} - INTERVAL 7 DAYS)) AS open_journeys_7d_ago,
           count_if(high_need_awaiting) AS high_need_awaiting,
           count_if(high_need_awaiting AND consent_restricted) AS high_need_consent_restricted,
           count_if(is_open AND sla_status = 'overdue') AS overdue_journeys
    FROM c GROUP BY ROLLUP (agency_code)),
  idc AS (SELECT round(avg(identity_confidence), 4) AS identity_confidence, count(*) AS multi_source_constituents
          FROM {T('silver_constituents')} WHERE source_record_count > 1)
  SELECT date({AS_OF}) AS snapshot_date, k.*,
         round(coalesce(a.rep, 0) / nullif(a.n, 0), 4) AS repeat_contact_7d_rate,
         round(coalesce(b.rep, 0) / nullif(b.n, 0), 4) AS repeat_contact_prev_7d_rate,
         coalesce(a.n, 0) AS inbound_contacts_7d,
         {REPEAT_TARGET} AS repeat_contact_target,
         idc.identity_confidence, idc.multi_source_constituents
  FROM k
  LEFT JOIN (SELECT coalesce(agency_code, 'ALL') AS agency_code, sum(rep) AS rep, sum(n) AS n FROM i7 GROUP BY ROLLUP (agency_code)) a USING (agency_code)
  LEFT JOIN (SELECT coalesce(agency_code, 'ALL') AS agency_code, sum(rep) AS rep, sum(n) AS n FROM i7p GROUP BY ROLLUP (agency_code)) b USING (agency_code)
  CROSS JOIN idc""",
        "gold_service_kpis", "KPI strip per agency (and ALL) as of the latest delivery. Unsuppressed.",
        {"repeat_contact_7d_rate": "Share of inbound contacts in the last 7 days that repeat a contact within 7 days.",
         "high_need_consent_restricted": "High-need awaiting cases with history in a consent domain the case purpose cannot see.",
         "identity_confidence": "Mean identity confidence across constituents resolved from more than one source record."})

publish(f"""
  SELECT date_trunc('WEEK', i.event_ts) AS week_start, i.agency_code, coalesce(c.service_line, 'General enquiry') AS service_line,
         i.channel_label, count(*) AS inbound_contacts, count_if(i.is_repeat_contact) AS repeat_contacts,
         round(count_if(i.is_repeat_contact) / count(*), 4) AS repeat_contact_rate
  FROM {T('gold_interactions')} i LEFT JOIN {T('gold_cases')} c USING (case_id)
  WHERE i.direction = 'inbound' AND i.event_ts > {AS_OF} - INTERVAL 182 DAYS
  GROUP BY ALL""", "gold_repeat_contact_by_service", "Weekly repeat contact by service line and channel. Unsuppressed.")

publish(f"""
  SELECT date_trunc('WEEK', event_ts) AS week_start, agency_code, data_domain, intent,
         count(*) AS interactions,
         round(count_if(sentiment IN ('negative', 'mixed')) / count(*), 4) AS negative_share,
         round(avg(urgency_score), 1) AS avg_urgency,
         round(count_if(follow_up_required) / count(*), 4) AS follow_up_share,
         round(count_if(is_repeat_contact) / count(*), 4) AS repeat_share
  FROM {T('gold_interactions')}
  WHERE direction = 'inbound' AND event_ts > {AS_OF} - INTERVAL 182 DAYS AND intent IS NOT NULL
  GROUP BY ALL""", "gold_operational_signals",
        "Weekly operational signals by agency, domain and AI intent: volume, negative share, urgency, follow-up, repeat. Unsuppressed.")

# COMMAND ----------

q = spark.sql(f"""SELECT avg(IF(constituent_id IS NOT NULL, 1.0, 0.0)) resolved, avg(IF(case_id IS NOT NULL, 1.0, 0.0)) with_case,
                         avg(IF(intent IS NOT NULL, 1.0, 0.0)) with_signals FROM {T('gold_interactions')}""").first()
k = spark.sql(f"SELECT * FROM {T('gold_service_kpis')} WHERE agency_code = 'ALL'").first()
print(q, k)
failed = record_checks("06_gold_360", run_id, [
    ("interactions_resolved_rate", (q.resolved or 0) >= 0.8, "critical", round(q.resolved or 0, 4), ">= 0.80"),
    ("interactions_with_signals", (q.with_signals or 0) >= 0.9, "warning", round(q.with_signals or 0, 4), ">= 0.90"),
    ("open_journeys_present", (k.open_journeys or 0) > 0, "critical", k.open_journeys, "> 0"),
])
assert not failed, f"critical checks failed: {failed}"
