# Databricks notebook source
# MAGIC %md
# MAGIC # Shared helpers - Automated Compliance Reporting
# MAGIC
# MAGIC Included by every task with `%run ./_common` after the caller has read its widgets into
# MAGIC `catalog`, `schema` and `volume`. Provides:
# MAGIC
# MAGIC * table / volume naming (nothing environment-specific is hard-coded)
# MAGIC * `append_audit_events` - the only writer of the hash-chained, append-only audit trail
# MAGIC * `resolved_mappings`, `requirement_coverage`, `obligation_coverage` - the point-in-time
# MAGIC   coverage logic shared by the daily gold build and report generation, so a report
# MAGIC   regenerated for a past date applies exactly the same rules to the evidence as it stood then.

# COMMAND ----------

import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F
from pyspark.sql import types as T

assert catalog, "catalog parameter is required"
assert schema, "schema parameter is required"
assert volume, "volume parameter is required"

# Every timestamp is stored, formatted and hashed in UTC so audit hashes are reproducible.
spark.conf.set("spark.sql.session.timeZone", "UTC")


def fqn(table: str) -> str:
    return f"`{catalog}`.`{schema}`.`{table}`"


VOLUME_ROOT = f"/Volumes/{catalog}/{schema}/{volume}"
LANDING_ROOT = f"{VOLUME_ROOT}/landing"
CHECKPOINT_ROOT = f"{VOLUME_ROOT}/_checkpoints"
REPORTS_ROOT = f"{VOLUME_ROOT}/reports"

GENESIS_HASH = "0" * 64
TS_FMT = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"


def resolve_as_of(value: str) -> str:
    """'' -> today's date (UTC). Returns ISO yyyy-mm-dd."""
    if value:
        return date.fromisoformat(value).isoformat()
    return datetime.now(timezone.utc).date().isoformat()


def table_exists(table: str) -> bool:
    return spark.catalog.tableExists(f"{catalog}.{schema}.{table}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Immutable audit trail
# MAGIC
# MAGIC `audit_events` is a Delta table with `delta.appendOnly = true`, so UPDATE / DELETE / MERGE
# MAGIC are rejected by the storage layer, not just by convention. On top of that every event is
# MAGIC hash-chained: `event_hash = sha256(prev_hash || canonical)`, where `canonical` is a fixed
# MAGIC serialisation of the event. Any edit, deletion or reordering breaks the chain and is caught
# MAGIC by `06_verify_audit_chain`. Emission is idempotent via `dedup_key`, so re-running a task never
# MAGIC duplicates a fact.

# COMMAND ----------

AUDIT_INPUT_COLUMNS = [
    "event_type", "entity_type", "entity_id", "related_id", "summary", "actor", "occurred_at", "payload", "dedup_key",
]


def canonical_expr() -> F.Column:
    """Canonical event serialisation. Used identically when writing and when verifying."""
    return F.concat_ws(
        "|",
        F.col("event_seq").cast("string"),
        F.col("event_id"),
        F.col("event_type"),
        F.col("entity_type"),
        F.coalesce(F.col("entity_id"), F.lit("")),
        F.coalesce(F.col("related_id"), F.lit("")),
        F.coalesce(F.col("actor"), F.lit("")),
        F.date_format("occurred_at", TS_FMT),
        F.date_format("recorded_at", TS_FMT),
        F.coalesce(F.col("summary"), F.lit("")),
        F.coalesce(F.col("payload"), F.lit("")),
    )


def append_audit_events(events: DataFrame) -> int:
    """Append events to the hash-chained audit trail, skipping facts already recorded.

    `events` must provide AUDIT_INPUT_COLUMNS. `occurred_at` is the business time of the fact;
    `recorded_at` (set here) is when it entered the trail. `dedup_key` must be stable per fact.
    """
    audit = fqn("audit_events")
    new = (
        events.select(
            *[c for c in AUDIT_INPUT_COLUMNS if c not in ("occurred_at", "payload")],
            F.col("occurred_at").cast("timestamp").alias("occurred_at"),
            F.col("payload").cast("string").alias("payload"),
        )
        .dropDuplicates(["dedup_key"])
        .join(spark.table(audit).select("dedup_key"), "dedup_key", "left_anti")
    )

    last = spark.sql(f"SELECT event_seq, event_hash FROM {audit} ORDER BY event_seq DESC LIMIT 1").collect()
    base_seq, prev_hash = (int(last[0]["event_seq"]), last[0]["event_hash"]) if last else (0, GENESIS_HASH)
    recorded_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")

    staged = (
        new.withColumn("event_seq", (F.row_number().over(Window.orderBy("occurred_at", "dedup_key")) + F.lit(base_seq)).cast("long"))
        .withColumn("event_id", F.format_string("EVT-%07d", F.col("event_seq")))
        .withColumn("recorded_at", F.to_timestamp(F.lit(recorded_at)))
        .withColumn("canonical", canonical_expr())
        # Timestamps travel through the driver as canonical strings so they round-trip exactly.
        .withColumn("occurred_at_s", F.date_format("occurred_at", TS_FMT))
        .withColumn("recorded_at_s", F.date_format("recorded_at", TS_FMT))
        .drop("occurred_at", "recorded_at")
    )
    rows = staged.orderBy("event_seq").collect()
    if not rows:
        return 0

    cols = ["event_seq", "event_id", "event_type", "entity_type", "entity_id", "related_id", "summary", "actor",
            "occurred_at_s", "recorded_at_s", "payload", "dedup_key", "canonical", "prev_hash", "event_hash"]
    out = []
    for r in rows:
        event_hash = hashlib.sha256((prev_hash + r["canonical"]).encode("utf-8")).hexdigest()
        d = r.asDict()
        out.append(tuple({**d, "prev_hash": prev_hash, "event_hash": event_hash}[c] for c in cols))
        prev_hash = event_hash

    schema_ = T.StructType([T.StructField(c, T.LongType() if c == "event_seq" else T.StringType()) for c in cols])
    final = (
        spark.createDataFrame(out, schema_)
        .withColumn("occurred_at", F.to_timestamp("occurred_at_s"))
        .withColumn("recorded_at", F.to_timestamp("recorded_at_s"))
        .select(*[f.name for f in spark.table(audit).schema.fields])
    )
    final.write.mode("append").saveAsTable(audit)
    return len(out)


def audit_events_df(rows: DataFrame, *, event_type: str, entity_type: str, entity_id, summary, actor,
                    occurred_at, dedup_key, related_id=None, payload=None) -> DataFrame:
    """Project an arbitrary DataFrame into the audit input shape. Arguments are Columns or literals."""
    def col(v):
        return v if isinstance(v, F.Column) else F.lit(v)
    return rows.select(
        F.lit(event_type).alias("event_type"),
        F.lit(entity_type).alias("entity_type"),
        col(entity_id).cast("string").alias("entity_id"),
        col(related_id).cast("string").alias("related_id"),
        col(summary).cast("string").alias("summary"),
        col(actor).cast("string").alias("actor"),
        col(occurred_at).cast("timestamp").alias("occurred_at"),
        col(payload).cast("string").alias("payload"),
        col(dedup_key).cast("string").alias("dedup_key"),
    )

# COMMAND ----------

# MAGIC %md
# MAGIC ## Point-in-time coverage
# MAGIC
# MAGIC Everything below filters on timestamps `< as_of + 1 day`, using only append-only or
# MAGIC versioned inputs (register effective dates, evidence versions, rule mappings, human reviews,
# MAGIC AI suggestions). Running it for a past date therefore reproduces what was knowable then.
# MAGIC
# MAGIC Mapping precedence: human review > deterministic rule > AI suggestion. AI suggestions never
# MAGIC count towards coverage on their own - they surface as **Needs review** until a person confirms.

# COMMAND ----------

def resolved_mappings(as_of: str, min_confidence: float = 0.5) -> DataFrame:
    """One row per evidence document known at `as_of`, with its effective mapping."""
    return spark.sql(
        f"""
        WITH docs AS (
          SELECT evidence_id, source_id, title, first_collected_at
          FROM {fqn('evidence_documents')}
          WHERE first_collected_at < date_add(CAST(:as_of AS DATE), 1)
        ),
        human AS (
          SELECT evidence_id, decision, artefact_type AS human_type, reviewed_at, reviewer
          FROM (
            SELECT *, row_number() OVER (PARTITION BY evidence_id ORDER BY reviewed_at DESC, review_id DESC) AS rn
            FROM {fqn('mapping_reviews')}
            WHERE reviewed_at < date_add(CAST(:as_of AS DATE), 1)
          ) WHERE rn = 1
        ),
        rule AS (
          SELECT evidence_id, artefact_type AS rule_type, mapped_at
          FROM {fqn('evidence_rule_mappings')}
          WHERE mapped_at < date_add(CAST(:as_of AS DATE), 1)
        ),
        ai AS (
          SELECT evidence_id, artefact_type AS ai_type, confidence AS ai_confidence, rationale AS ai_rationale,
                 model_endpoint, suggested_at
          FROM (
            SELECT *, row_number() OVER (PARTITION BY evidence_id ORDER BY suggested_at DESC) AS rn
            FROM {fqn('mapping_ai_suggestions')}
            WHERE suggested_at < date_add(CAST(:as_of AS DATE), 1)
          ) WHERE rn = 1
        )
        SELECT
          d.evidence_id, d.source_id, d.title, d.first_collected_at,
          CASE WHEN h.decision = 'confirm' THEN h.human_type
               WHEN h.decision = 'reject' THEN NULL
               ELSE r.rule_type END AS mapped_type,
          CASE WHEN h.decision IS NOT NULL THEN 'human'
               WHEN r.rule_type IS NOT NULL THEN 'rule'
               WHEN a.ai_type IS NOT NULL THEN 'ai' END AS mapping_method,
          CASE WHEN h.decision = 'confirm' THEN 'Mapped'
               WHEN h.decision = 'reject' THEN 'Rejected'
               WHEN r.rule_type IS NOT NULL THEN 'Mapped'
               WHEN a.ai_type IS NOT NULL AND a.ai_type <> 'NONE' AND a.ai_confidence >= :min_conf THEN 'Needs review'
               ELSE 'Unmapped' END AS mapping_state,
          CASE WHEN h.decision IS NULL AND r.rule_type IS NULL AND a.ai_type <> 'NONE' THEN a.ai_type END AS suggested_type,
          a.ai_type, a.ai_confidence, a.ai_rationale, a.model_endpoint, a.suggested_at,
          h.decision AS review_decision, h.reviewer, h.reviewed_at,
          r.rule_type, r.mapped_at AS rule_mapped_at
        FROM docs d
        LEFT JOIN human h USING (evidence_id)
        LEFT JOIN rule r USING (evidence_id)
        LEFT JOIN ai a USING (evidence_id)
        """,
        args={"as_of": as_of, "min_conf": float(min_confidence)},
    )


def requirement_coverage(as_of: str, warn_days: int = 14, min_confidence: float = 0.5) -> DataFrame:
    """Coverage of every requirement of every obligation version in force at `as_of`."""
    # Unique per as_of: DataFrames are resolved lazily, so a shared view name could be rebound.
    view = f"_resolved_mappings_{as_of.replace('-', '_')}"
    resolved_mappings(as_of, min_confidence).createOrReplaceTempView(view)
    return spark.sql(
        f"""
        WITH reg AS (
          SELECT * FROM {fqn('obligation_register')}
          WHERE approval_state = 'Approved'
            AND effective_from <= CAST(:as_of AS DATE)
            AND (effective_to IS NULL OR effective_to > CAST(:as_of AS DATE))
            AND (retired_on IS NULL OR retired_on > CAST(:as_of AS DATE))
        ),
        req AS (
          SELECT q.obligation_id, q.version AS obligation_version, g.title AS obligation_title, g.gate_id,
                 g.owner_role, g.framework, q.requirement_id, q.artefact_type, q.requirement_description,
                 q.expected_source_id, q.max_age_days, q.mandatory
          FROM {fqn('obligation_requirements')} q
          JOIN reg g ON g.obligation_id = q.obligation_id AND g.version = q.version
        ),
        v AS (
          SELECT a.*, m.mapped_type
          FROM {fqn('evidence_artefacts')} a
          JOIN {view} m USING (evidence_id)
          WHERE a.collected_at < date_add(CAST(:as_of AS DATE), 1) AND m.mapping_state = 'Mapped'
        ),
        agg AS (
          SELECT q.requirement_id,
                 count(DISTINCT v.evidence_id) AS mapped_evidence_count,
                 max_by(
                   named_struct('evidence_id', v.evidence_id, 'artefact_version', v.artefact_version,
                                'title', v.title, 'checksum', v.checksum,
                                'modified_on', to_date(v.source_modified_at), 'collected_at', v.collected_at),
                   v.source_modified_at
                 ) FILTER (WHERE v.is_acceptable) AS best,
                 count(v.evidence_id) FILTER (WHERE NOT v.is_acceptable) AS unacceptable_versions
          FROM req q LEFT JOIN v ON v.mapped_type = q.artefact_type
          GROUP BY q.requirement_id
        ),
        pend AS (
          SELECT suggested_type AS artefact_type, count(*) AS pending_review_count
          FROM {view} WHERE mapping_state = 'Needs review' GROUP BY suggested_type
        ),
        joined AS (
          SELECT q.*, coalesce(agg.mapped_evidence_count, 0) AS mapped_evidence_count,
                 coalesce(agg.unacceptable_versions, 0) AS unacceptable_versions,
                 agg.best.evidence_id AS best_evidence_id, agg.best.artefact_version AS best_artefact_version,
                 agg.best.title AS best_evidence_title, agg.best.checksum AS best_checksum,
                 agg.best.modified_on AS evidence_modified_on, agg.best.collected_at AS evidence_collected_at,
                 date_add(agg.best.modified_on, q.max_age_days) AS expires_on,
                 coalesce(p.pending_review_count, 0) AS pending_review_count
          FROM req q
          LEFT JOIN agg ON agg.requirement_id = q.requirement_id
          LEFT JOIN pend p ON p.artefact_type = q.artefact_type
        )
        SELECT CAST(:as_of AS DATE) AS as_of_date, *,
          datediff(expires_on, CAST(:as_of AS DATE)) AS days_to_expiry,
          CASE WHEN best_evidence_id IS NULL THEN 'Gap'
               WHEN expires_on < CAST(:as_of AS DATE) THEN 'Gap'
               WHEN datediff(expires_on, CAST(:as_of AS DATE)) <= :warn THEN 'Expiring'
               ELSE 'Complete' END AS status,
          CASE WHEN best_evidence_id IS NULL AND mapped_evidence_count > 0 THEN 'No approved evidence'
               WHEN best_evidence_id IS NULL AND pending_review_count > 0 THEN 'Awaiting mapping review'
               WHEN best_evidence_id IS NULL THEN 'No evidence mapped'
               WHEN expires_on < CAST(:as_of AS DATE) THEN 'Evidence expired' END AS gap_reason
        FROM joined
        """,
        args={"as_of": as_of, "warn": int(warn_days)},
    )


def obligation_coverage(req: DataFrame) -> DataFrame:
    """Roll requirement coverage up to one row per obligation (worst requirement wins)."""
    severity = F.when(F.col("status") == "Gap", 3).when(F.col("status") == "Expiring", 2).otherwise(1)
    return (
        req.groupBy("as_of_date", "obligation_id", "obligation_version", "obligation_title", "gate_id", "owner_role", "framework")
        .agg(
            F.count("*").alias("requirements_total"),
            F.sum((F.col("status") == "Complete").cast("int")).alias("requirements_complete"),
            F.sum((F.col("status") == "Expiring").cast("int")).alias("requirements_expiring"),
            F.sum((F.col("status") == "Gap").cast("int")).alias("requirements_gap"),
            F.sum(F.col("best_evidence_id").isNotNull().cast("int")).alias("evidence_mapped"),
            F.sum("pending_review_count").alias("pending_review_count"),
            F.max(severity).alias("_severity"),
            F.min("expires_on").alias("_next_expiry"),
            F.array_sort(F.collect_set("gap_reason")).alias("gap_reasons"),
            F.array_sort(F.collect_set("best_evidence_id")).alias("evidence_ids"),
        )
        .withColumn("status", F.when(F.col("_severity") == 3, "Gap").when(F.col("_severity") == 2, "Expiring").otherwise("Complete"))
        # Review date = when the earliest-expiring evidence lapses; not set while a gap is open.
        .withColumn("review_date", F.when(F.col("_severity") < 3, F.col("_next_expiry")))
        .withColumn("days_to_review", F.datediff("review_date", "as_of_date"))
        .drop("_severity", "_next_expiry")
    )
