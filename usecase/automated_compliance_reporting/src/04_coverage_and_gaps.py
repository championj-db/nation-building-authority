# Databricks notebook source
# MAGIC %md
# MAGIC # Coverage, gap and expiry detection - Automated Compliance Reporting
# MAGIC
# MAGIC Builds the gold layer the application reads, using the shared point-in-time coverage logic in
# MAGIC `_common`, and maintains the alert lifecycle so a gap **opens when evidence expires or goes
# MAGIC missing**, not when a report falls due.
# MAGIC
# MAGIC | Gold table / view | Screen in the design |
# MAGIC | --- | --- |
# MAGIC | `compliance_overview` | Overview metrics (obligations, covered, expiring, open gaps, accuracy) |
# MAGIC | `obligation_coverage` | Overview obligation table |
# MAGIC | `gate_coverage` | Coverage by gate |
# MAGIC | `gap_alerts` (+ view `needs_attention`) | Needs attention |
# MAGIC | `obligation_register_current` (view), `obligation_register`, `obligation_requirements` | Obligation register |
# MAGIC | `evidence_inbox`, `evidence_obligation_map` | Evidence mapping |
# MAGIC | `requirement_coverage` | Report preflight / obligation detail |
# MAGIC | `source_health` | Collection source status |
# MAGIC | `coverage_history` | Point-in-time coverage trend |

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "evidence")
dbutils.widgets.text("as_of_date", "")
dbutils.widgets.text("expiry_warning_days", "14")
dbutils.widgets.text("min_confidence", "0.5")
dbutils.widgets.text("source_offline_failures", "2")
dbutils.widgets.text("history_backfill_days", "0")
dbutils.widgets.text("history_step_days", "7")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
as_of_param = dbutils.widgets.get("as_of_date")
warn_days = int(dbutils.widgets.get("expiry_warning_days"))
min_confidence = float(dbutils.widgets.get("min_confidence"))
offline_failures = int(dbutils.widgets.get("source_offline_failures"))
backfill_days = int(dbutils.widgets.get("history_backfill_days"))
step_days = max(1, int(dbutils.widgets.get("history_step_days")))

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

as_of = resolve_as_of(as_of_param)
ARGS = {"as_of": as_of, "warn": warn_days}
print(f"as_of={as_of} warn={warn_days}d offline_after={offline_failures} failures")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Register (current view) and coverage

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {fqn('obligation_register_current')}
COMMENT 'Obligation versions in force today, with gate labels and any pending draft revision.'
AS
WITH cur AS (
  SELECT * FROM {fqn('obligation_register')}
  WHERE approval_state = 'Approved' AND effective_from <= current_date()
    AND (effective_to IS NULL OR effective_to > current_date()) AND (retired_on IS NULL OR retired_on > current_date())
),
drafts AS (
  SELECT obligation_id, max(version) AS draft_version, max(proposed_at) AS draft_proposed_at,
         max_by(change_reason, version) AS draft_change_reason
  FROM {fqn('obligation_register')} WHERE approval_state = 'Draft' GROUP BY obligation_id
)
SELECT c.obligation_id, c.version, c.title, c.description, c.gate_id, g.gate_label, g.gate_name, c.owner_role,
       c.framework, c.framework_url, c.effective_from, c.approved_at, c.approved_by, c.change_reason,
       c.requirement_count, d.draft_version, d.draft_proposed_at, d.draft_change_reason,
       CASE WHEN d.draft_version IS NOT NULL THEN 'Review' ELSE 'Active' END AS register_state
FROM cur c
JOIN {fqn('review_gates')} g ON g.gate_id = c.gate_id
LEFT JOIN drafts d ON d.obligation_id = c.obligation_id
""")

req = requirement_coverage(as_of, warn_days, min_confidence)
req.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fqn("requirement_coverage"))
spark.sql(f"COMMENT ON TABLE {fqn('requirement_coverage')} IS 'Coverage of each evidence requirement in force at as_of_date: best approved evidence, expiry and status (Complete | Expiring | Gap).'")

obl = (
    obligation_coverage(spark.table(fqn("requirement_coverage")))
    .join(spark.table(fqn("review_gates")).select("gate_id", "gate_label", "gate_name", "gate_order"), "gate_id")
    .join(spark.table(fqn("obligation_register_current")).select("obligation_id", "register_state", "draft_version"), "obligation_id", "left")
)
obl.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(fqn("obligation_coverage"))
spark.sql(f"COMMENT ON TABLE {fqn('obligation_coverage')} IS 'One row per obligation in force: requirement counts, mapped evidence, status (worst requirement wins) and review date.'")

spark.sql(f"""
CREATE OR REPLACE TABLE {fqn('gate_coverage')} COMMENT 'Obligation coverage by Gateway gate.' AS
SELECT as_of_date, gate_id, gate_label, gate_name, gate_order,
       count(*) AS obligations_total,
       sum(CASE WHEN status = 'Complete' THEN 1 ELSE 0 END) AS obligations_complete,
       sum(CASE WHEN status = 'Expiring' THEN 1 ELSE 0 END) AS obligations_expiring,
       sum(CASE WHEN status = 'Gap' THEN 1 ELSE 0 END) AS obligations_gap,
       sum(CASE WHEN status <> 'Gap' THEN 1 ELSE 0 END) AS obligations_covered,
       round(100.0 * sum(CASE WHEN status <> 'Gap' THEN 1 ELSE 0 END) / count(*), 1) AS coverage_pct
FROM {fqn('obligation_coverage')} GROUP BY ALL
""")
display(spark.table(fqn("gate_coverage")).orderBy("gate_order"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Source health and evidence inbox

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {fqn('source_health')} COMMENT 'Connector health per source system from collection_runs.' AS
WITH runs AS (SELECT * FROM {fqn('collection_runs')} WHERE run_date <= CAST(:as_of AS DATE)),
latest AS (SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY source_id ORDER BY run_date DESC) AS rn FROM runs) WHERE rn = 1),
last_ok AS (SELECT source_id, max(run_date) AS last_success_date FROM runs WHERE status = 'Succeeded' GROUP BY source_id),
streak AS (
  SELECT r.source_id, count(*) AS consecutive_failures, min(r.run_date) AS failing_since
  FROM runs r LEFT JOIN last_ok l USING (source_id)
  WHERE r.run_date > coalesce(l.last_success_date, DATE'1900-01-01') GROUP BY r.source_id
),
vol AS (
  SELECT source_id, sum(records_collected) AS records_last_30d,
         sum(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) AS failed_runs_last_30d
  FROM runs WHERE run_date > date_sub(CAST(:as_of AS DATE), 30) GROUP BY source_id
)
SELECT CAST(:as_of AS DATE) AS as_of_date, s.source_id, s.source_name, s.connector,
       l.status AS last_run_status, l.run_date AS last_run_date, l.error_message AS last_error,
       o.last_success_date, coalesce(k.consecutive_failures, 0) AS consecutive_failures, k.failing_since,
       coalesce(v.records_last_30d, 0) AS records_last_30d, coalesce(v.failed_runs_last_30d, 0) AS failed_runs_last_30d,
       CASE WHEN coalesce(k.consecutive_failures, 0) >= :offline THEN 'Offline'
            WHEN coalesce(k.consecutive_failures, 0) > 0 THEN 'Degraded' ELSE 'Online' END AS health
FROM {fqn('source_systems')} s
LEFT JOIN latest l USING (source_id) LEFT JOIN last_ok o USING (source_id)
LEFT JOIN streak k USING (source_id) LEFT JOIN vol v USING (source_id)
""", args={"as_of": as_of, "offline": offline_failures})

spark.sql(f"""
CREATE OR REPLACE TABLE {fqn('evidence_inbox')} COMMENT 'Evidence mapping workspace: one row per collected document with mapping state, provenance and freshness.' AS
WITH reg AS (
  SELECT obligation_id, version FROM {fqn('obligation_register')}
  WHERE approval_state = 'Approved' AND effective_from <= CAST(:as_of AS DATE)
    AND (effective_to IS NULL OR effective_to > CAST(:as_of AS DATE)) AND (retired_on IS NULL OR retired_on > CAST(:as_of AS DATE))
),
thresholds AS (
  SELECT q.artefact_type, min(q.max_age_days) AS max_age_days
  FROM {fqn('obligation_requirements')} q JOIN reg USING (obligation_id, version) GROUP BY q.artefact_type
),
best AS (
  SELECT evidence_id, max_by(named_struct('v', artefact_version, 'modified', source_modified_at), source_modified_at)
           FILTER (WHERE is_acceptable) AS b
  FROM {fqn('evidence_artefacts')} GROUP BY evidence_id
),
links AS (
  SELECT evidence_id,
         array_sort(collect_set(CASE WHEN link_state = 'Mapped' THEN obligation_id END)) AS mapped_obligations,
         array_sort(collect_set(CASE WHEN link_state = 'Suggested' THEN obligation_id END)) AS suggested_obligations
  FROM {fqn('evidence_obligation_map')} GROUP BY evidence_id
),
base AS (
  SELECT d.*, m.mapping_state, m.mapping_method, coalesce(m.mapped_type, m.suggested_type) AS artefact_type,
         m.ai_confidence, m.ai_rationale, m.model_endpoint, m.reviewer, m.reviewed_at,
         coalesce(k.mapped_obligations, array()) AS mapped_obligations,
         coalesce(k.suggested_obligations, array()) AS suggested_obligations,
         t.max_age_days AS freshness_threshold_days, b.b.v AS approved_version,
         date_add(to_date(b.b.modified), t.max_age_days) AS expires_on
  FROM {fqn('evidence_documents')} d
  LEFT JOIN {fqn('evidence_mappings')} m USING (evidence_id)
  LEFT JOIN links k USING (evidence_id)
  LEFT JOIN thresholds t ON t.artefact_type = coalesce(m.mapped_type, m.suggested_type)
  LEFT JOIN best b USING (evidence_id)
)
SELECT CAST(:as_of AS DATE) AS as_of_date, evidence_id, title, file_format,
       concat_ws(' · ', evidence_id, file_format,
         CASE WHEN NOT latest_integrity_verified THEN 'checksum mismatch'
              WHEN latest_approval_status = 'Draft' THEN 'unsigned draft'
              WHEN signed THEN 'signed'
              WHEN source_id IN ('SRC-DOC', 'SRC-MTG') THEN 'parsed'
              ELSE 'checksum recorded' END) AS artefact_tag,
       source_id, source_name, connector, latest_version, version_count, approved_version,
       first_collected_at, latest_collected_at AS collected_at, latest_source_modified_at AS source_modified_at,
       latest_approval_status AS approval_status, signed, latest_checksum AS checksum,
       latest_integrity_verified AS integrity_verified, content_excerpt,
       mapping_state, mapping_method, artefact_type, mapped_obligations, suggested_obligations,
       ai_confidence, ai_rationale, model_endpoint, reviewer, reviewed_at,
       freshness_threshold_days, expires_on, datediff(expires_on, CAST(:as_of AS DATE)) AS days_to_expiry,
       CASE WHEN mapping_state = 'Rejected' THEN 'Not evidence'
            WHEN freshness_threshold_days IS NULL THEN 'No threshold'
            WHEN expires_on IS NULL THEN 'No approved version'
            WHEN expires_on < CAST(:as_of AS DATE) THEN 'Expired'
            WHEN datediff(expires_on, CAST(:as_of AS DATE)) <= :warn THEN 'Expiring'
            ELSE 'Current' END AS freshness_status
FROM base
""", args=ARGS)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Gap and expiry alerts (lifecycle)
# MAGIC
# MAGIC An alert is **Open** while its condition holds and is **Resolved** automatically the first run
# MAGIC after it clears. `gap_opened_on` is when the condition actually began (e.g. the day evidence
# MAGIC expired); `first_detected_at` is when this pipeline first saw it.

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {fqn('gap_alerts')} (
  alert_id STRING, alert_key STRING, alert_type STRING, severity STRING, status STRING,
  obligation_id STRING, requirement_id STRING, evidence_id STRING, source_id STRING,
  headline STRING, detail STRING, gap_opened_on DATE, due_date DATE,
  first_detected_at TIMESTAMP, last_detected_at TIMESTAMP, resolved_at TIMESTAMP
) COMMENT 'Gap, expiry, source and integrity alerts with open/resolved lifecycle.'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")

spark.sql(f"""
CREATE OR REPLACE TEMP VIEW _active_alerts AS
WITH req AS (SELECT * FROM {fqn('requirement_coverage')}),
conditions AS (
  SELECT CASE gap_reason WHEN 'Evidence expired' THEN 'EVIDENCE_EXPIRED' WHEN 'No approved evidence' THEN 'NO_APPROVED_EVIDENCE'
                         WHEN 'Awaiting mapping review' THEN 'AWAITING_REVIEW' ELSE 'NO_EVIDENCE' END AS alert_type,
         'High' AS severity, obligation_id, requirement_id, best_evidence_id AS evidence_id, CAST(NULL AS STRING) AS source_id,
         CASE gap_reason WHEN 'Evidence expired' THEN concat('Evidence expired ', -days_to_expiry, ' days ago')
                         WHEN 'No approved evidence' THEN 'No approved evidence'
                         WHEN 'Awaiting mapping review' THEN 'Evidence awaiting mapping review'
                         ELSE 'No evidence mapped' END AS headline,
         concat(artefact_type, ' · ', obligation_id) AS detail,
         CASE WHEN gap_reason = 'Evidence expired' THEN date_add(expires_on, 1) END AS gap_opened_on,
         CAST(NULL AS DATE) AS due_date, requirement_id AS entity
  FROM req WHERE status = 'Gap'
  UNION ALL
  SELECT 'EVIDENCE_EXPIRING', 'Medium', obligation_id, requirement_id, best_evidence_id, NULL,
         concat('Evidence expires in ', days_to_expiry, CASE WHEN days_to_expiry = 1 THEN ' day' ELSE ' days' END),
         concat(best_evidence_title, ' · ', obligation_id), date_sub(expires_on, :warn), expires_on, requirement_id
  FROM req WHERE status = 'Expiring'
  UNION ALL
  SELECT 'SOURCE_OFFLINE', CASE WHEN health = 'Offline' THEN 'High' ELSE 'Medium' END, NULL, NULL, NULL, source_id,
         CASE WHEN health = 'Offline' THEN 'Collection source offline' ELSE 'Collection source degraded' END,
         concat(source_name, ' connector · ', consecutive_failures, ' failed runs'), failing_since, NULL, source_id
  FROM {fqn('source_health')} WHERE health <> 'Online'
  UNION ALL
  SELECT 'INTEGRITY_FAILURE', 'High', NULL, NULL, evidence_id, source_id, 'Checksum mismatch on latest version',
         concat(title, ' · ', evidence_id), to_date(collected_at), NULL, evidence_id
  FROM {fqn('evidence_inbox')} WHERE NOT integrity_verified AND coalesce(mapping_state, '') <> 'Rejected'
)
SELECT concat_ws('|', alert_type, entity) AS alert_key, * EXCEPT (entity) FROM conditions
""", args={"warn": warn_days})

spark.sql(f"""
MERGE INTO {fqn('gap_alerts')} t
USING _active_alerts s
ON t.alert_key = s.alert_key AND t.status = 'Open'
WHEN MATCHED THEN UPDATE SET
  severity = s.severity, headline = s.headline, detail = s.detail, evidence_id = s.evidence_id,
  due_date = s.due_date, last_detected_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT (
  alert_id, alert_key, alert_type, severity, status, obligation_id, requirement_id, evidence_id, source_id,
  headline, detail, gap_opened_on, due_date, first_detected_at, last_detected_at, resolved_at
) VALUES (
  concat('ALT-', upper(substr(sha2(concat(s.alert_key, '|', CAST(current_timestamp() AS STRING)), 256), 1, 10))),
  s.alert_key, s.alert_type, s.severity, 'Open', s.obligation_id, s.requirement_id, s.evidence_id, s.source_id,
  s.headline, s.detail, coalesce(s.gap_opened_on, current_date()), s.due_date, current_timestamp(), current_timestamp(), NULL
)
WHEN NOT MATCHED BY SOURCE AND t.status = 'Open' THEN UPDATE SET status = 'Resolved', resolved_at = current_timestamp()
""")

spark.sql(f"""
CREATE OR REPLACE VIEW {fqn('needs_attention')} COMMENT 'Open alerts ordered for the Needs attention panel.' AS
SELECT * FROM {fqn('gap_alerts')} WHERE status = 'Open'
ORDER BY CASE severity WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, coalesce(due_date, gap_opened_on), alert_key
""")

alerts = spark.table(fqn("gap_alerts"))
raised = audit_events_df(
    alerts, event_type="alert.raised", entity_type="alert", entity_id=F.col("alert_id"),
    related_id=F.coalesce("requirement_id", "source_id", "evidence_id"),
    summary=F.concat_ws(": ", "headline", "detail"), actor=F.lit("gap.detector"), occurred_at=F.col("first_detected_at"),
    payload=F.to_json(F.struct("alert_type", "severity", "gap_opened_on", "due_date")),
    dedup_key=F.format_string("alert.raised|%s", "alert_id"),
)
resolved = audit_events_df(
    alerts.filter(F.col("resolved_at").isNotNull()), event_type="alert.resolved", entity_type="alert",
    entity_id=F.col("alert_id"), related_id=F.coalesce("requirement_id", "source_id", "evidence_id"),
    summary=F.concat(F.lit("Resolved: "), F.col("headline"), F.lit(" · "), F.col("detail")),
    actor=F.lit("gap.detector"), occurred_at=F.col("resolved_at"),
    payload=F.to_json(F.struct("alert_type", "first_detected_at")),
    dedup_key=F.format_string("alert.resolved|%s", "alert_id"),
)
print(f"audit events appended: {append_audit_events(raised.unionByName(resolved))}")
display(spark.table(fqn("needs_attention")).select("severity", "alert_type", "headline", "detail", "gap_opened_on", "due_date"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Overview metrics and point-in-time history

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {fqn('compliance_overview')} COMMENT 'Single-row headline metrics for the Overview screen, including review accuracy against the labelled set.' AS
WITH o AS (SELECT * FROM {fqn('obligation_coverage')}),
r AS (SELECT * FROM {fqn('requirement_coverage')}),
ev AS (
  SELECT max_by(run_id, evaluated_at) AS run_id FROM {fqn('mapping_evaluation')}
),
acc AS (
  SELECT max(CASE WHEN method = 'resolved' THEN accuracy END) AS mapping_accuracy,
         max(CASE WHEN method = 'resolved' THEN labelled_items END) AS mapping_labelled_items,
         max(CASE WHEN method = 'ai' THEN accuracy END) AS ai_suggestion_accuracy,
         max(CASE WHEN method = 'ai' THEN labelled_items END) AS ai_labelled_items,
         max(evaluated_at) AS evaluated_at
  FROM {fqn('mapping_evaluation')} WHERE run_id = (SELECT run_id FROM ev)
)
SELECT CAST(:as_of AS DATE) AS as_of_date,
  (SELECT count(*) FROM o) AS obligations,
  (SELECT count(*) FROM o WHERE status <> 'Gap') AS obligations_covered,
  (SELECT count(*) FROM o WHERE status = 'Complete') AS obligations_complete,
  (SELECT count(*) FROM o WHERE status = 'Expiring') AS obligations_expiring,
  (SELECT count(*) FROM o WHERE status = 'Gap') AS obligations_gap,
  (SELECT count(*) FROM r) AS requirements_total,
  (SELECT count(*) FROM r WHERE status <> 'Gap') AS requirements_met,
  round(100.0 * (SELECT count(*) FROM r WHERE status <> 'Gap') / (SELECT count(*) FROM r), 1) AS evidence_coverage_pct,
  (SELECT count(*) FROM {fqn('gap_alerts')} WHERE status = 'Open') AS open_alerts,
  (SELECT count(*) FROM {fqn('gap_alerts')} WHERE status = 'Open' AND severity = 'High') AS open_high_alerts,
  (SELECT count(*) FROM {fqn('evidence_mappings')} WHERE mapping_state = 'Needs review') AS evidence_needs_review,
  (SELECT count(*) FROM {fqn('evidence_mappings')} WHERE mapping_state = 'Unmapped') AS evidence_unmapped,
  (SELECT count(*) FROM {fqn('source_health')} WHERE health <> 'Online') AS sources_not_online,
  (SELECT max(collected_at) FROM {fqn('evidence_artefacts')}) AS last_collected_at,
  acc.mapping_accuracy, acc.mapping_labelled_items, acc.ai_suggestion_accuracy, acc.ai_labelled_items,
  acc.evaluated_at AS accuracy_evaluated_at,
  :warn AS expiry_warning_days,
  current_timestamp() AS refreshed_at
FROM acc
""", args=ARGS)
display(spark.table(fqn("compliance_overview")))

# COMMAND ----------

# Point-in-time coverage history: the same logic replayed for earlier dates (only inputs that
# existed at each date are visible), plus today's snapshot. Re-running replaces those dates.
history_dates = sorted({(date.fromisoformat(as_of) - timedelta(days=d)).isoformat() for d in range(0, backfill_days + 1, step_days)} | {as_of})
snapshots = None
for d in history_dates:
    snap = obligation_coverage(requirement_coverage(d, warn_days, min_confidence))
    snapshots = snap if snapshots is None else snapshots.unionByName(snap)
writer = snapshots.write.mode("overwrite")
if table_exists("coverage_history"):
    writer = writer.option("replaceWhere", f"as_of_date IN ({', '.join(repr(x) for x in history_dates)})")
writer.saveAsTable(fqn("coverage_history"))
spark.sql(f"COMMENT ON TABLE {fqn('coverage_history')} IS 'Obligation coverage snapshots by as_of_date, computed point-in-time.'")
print(f"coverage_history dates written: {len(history_dates)}")
