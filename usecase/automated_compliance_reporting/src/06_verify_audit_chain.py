# Databricks notebook source
# MAGIC %md
# MAGIC # Verify audit chain - Automated Compliance Reporting
# MAGIC
# MAGIC Proves the audit trail has not been altered, using three independent checks:
# MAGIC
# MAGIC 1. **Hash chain** (Spark-native, no driver loop): for every event, the stored canonical form is
# MAGIC    recomputed from its columns, `event_hash = sha256(prev_hash || canonical)` is recomputed, each
# MAGIC    `prev_hash` equals the previous event's hash, and `event_seq` has no gaps.
# MAGIC 2. **Storage guarantee**: `delta.appendOnly` is still `true` on `audit_events`.
# MAGIC 3. **Table history**: Delta history contains no operation that can rewrite rows.
# MAGIC
# MAGIC The result is appended to `audit_chain_verifications` and itself recorded in the chain. A broken
# MAGIC chain fails the task, which triggers the job's failure notification.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "evidence")
dbutils.widgets.text("requested_by", "audit.verifier")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
requested_by = dbutils.widgets.get("requested_by") or "audit.verifier"

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

import uuid

audit = spark.table(fqn("audit_events"))
ordered = Window.orderBy("event_seq")
checked = (
    audit
    .withColumn("expected_prev", F.coalesce(F.lag("event_hash").over(ordered), F.lit(GENESIS_HASH)))
    .withColumn("expected_seq", F.row_number().over(ordered).cast("long"))
    .withColumn("recomputed_canonical", canonical_expr())
    .withColumn("recomputed_hash", F.sha2(F.concat(F.col("prev_hash"), F.col("recomputed_canonical")), 256))
    .withColumn("problem",
        F.when(F.col("event_seq") != F.col("expected_seq"), "sequence gap or duplicate")
         .when(F.col("prev_hash") != F.col("expected_prev"), "chain link broken")
         .when(F.col("canonical") != F.col("recomputed_canonical"), "event content altered")
         .when(F.col("event_hash") != F.col("recomputed_hash"), "event hash mismatch"))
)
stats = checked.agg(
    F.count("*").alias("n"),
    F.max("event_seq").alias("head_seq"),
    F.max_by("event_hash", "event_seq").alias("head_hash"),
    F.min(F.when(F.col("problem").isNotNull(), F.col("event_seq"))).alias("first_broken_seq"),
    F.sum(F.col("problem").isNotNull().cast("int")).alias("broken"),
).first()
first_problem = (checked.filter(F.col("event_seq") == stats["first_broken_seq"]).select("problem").first()
                 if stats["first_broken_seq"] is not None else None)

props = {r["key"]: r["value"] for r in spark.sql(f"SHOW TBLPROPERTIES {fqn('audit_events')}").collect()}
append_only = props.get("delta.appendOnly") == "true"

REWRITE_OPS = {"DELETE", "UPDATE", "MERGE", "RESTORE", "TRUNCATE", "REPLACE TABLE", "CREATE OR REPLACE TABLE",
               "REPLACE TABLE AS SELECT", "CREATE OR REPLACE TABLE AS SELECT", "OPTIMIZE WITH REWRITE"}
history_ops = [r["operation"] for r in spark.sql(f"DESCRIBE HISTORY {fqn('audit_events')}").select("operation").collect()]
rewrites = sorted({op for op in history_ops if op in REWRITE_OPS})

verified = stats["broken"] == 0 and append_only and not rewrites
detail = json.dumps({
    "chain_problems": int(stats["broken"] or 0),
    "first_problem": first_problem["problem"] if first_problem else None,
    "append_only": append_only,
    "rewrite_operations_in_history": rewrites,
    "history_versions": len(history_ops),
})
verification_id = f"VER-{uuid.uuid4().hex[:10].upper()}"
verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
spark.createDataFrame(
    [(verification_id, verified_at, int(stats["n"]), stats["head_seq"], stats["head_hash"],
      "Verified" if verified else "Broken", stats["first_broken_seq"], detail)],
    spark.table(fqn("audit_chain_verifications")).schema,
).write.mode("append").saveAsTable(fqn("audit_chain_verifications"))

append_audit_events(spark.createDataFrame([dict(
    event_type="audit.chain_verified", entity_type="audit", entity_id=verification_id, related_id=str(stats["head_seq"]),
    summary=f"Audit chain {'verified' if verified else 'BROKEN'}: {stats['n']} events up to EVT-{stats['head_seq']:07d}",
    actor=requested_by, occurred_at=verified_at, payload=detail, dedup_key=f"audit.chain_verified|{verification_id}")],
    "event_type STRING, entity_type STRING, entity_id STRING, related_id STRING, summary STRING, actor STRING, occurred_at TIMESTAMP, payload STRING, dedup_key STRING"))

print(f"{verification_id}: {'VERIFIED' if verified else 'BROKEN'} events={stats['n']} head={stats['head_hash'][:12]} detail={detail}")
assert verified, f"Audit chain verification failed: {detail}"
