# Databricks notebook source
# MAGIC %md
# MAGIC # Queue Prioritisation & Audit Trail
# MAGIC
# MAGIC Builds the caseworker queue by combining rules results, agent recommendations,
# MAGIC and application metadata into a single prioritised view. Also seeds the
# MAGIC audit trail with every system action taken so far.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

assert catalog, "catalog parameter is required"
assert schema, "schema parameter is required"

fqn = lambda table: f"{catalog}.{schema}.{table}"

# COMMAND ----------

from pyspark.sql import functions as F, Window

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load inputs

# COMMAND ----------

df_360 = spark.table(fqn("applicant_360"))
df_rules_summary = spark.table(fqn("rules_summary"))
df_rules_results = spark.table(fqn("rules_results"))
df_agent = spark.table(fqn("agent_recommendations"))
df_evidence = spark.table(fqn("evidence_documents"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build caseworker queue
# MAGIC
# MAGIC Priority scoring:
# MAGIC - Urgent flag: +30
# MAGIC - Borderline with agent recommendation: +20
# MAGIC - Has failing criteria: +10
# MAGIC - Number of criteria needing review: +5 each
# MAGIC - Days since lodged: +1 per day

# COMMAND ----------

# Evidence count per application
df_evidence_count = (
    df_evidence
    .groupBy("application_id")
    .agg(
        F.count("*").alias("evidence_count"),
        F.sum(F.when(F.col("verification_status") == "verified", 1).otherwise(0)).alias("evidence_verified"),
        F.sum(F.when(F.col("verification_status") == "needs_context", 1).otherwise(0)).alias("evidence_needs_context"),
    )
)

# Criteria detail aggregation
df_criteria_detail = (
    df_rules_results
    .groupBy("application_id")
    .agg(
        F.collect_list(
            F.struct(
                F.col("criterion_name"),
                F.col("result"),
                F.col("policy_section"),
                F.col("rule_id"),
            )
        ).alias("criteria_detail")
    )
)

# Build the queue
df_queue = (
    df_360
    .join(df_rules_summary, on="application_id", how="inner")
    .join(df_agent.select(
        "application_id",
        F.col("verdict").alias("agent_verdict"),
        F.col("agent_recommendation"),
        F.col("generated_at").alias("agent_generated_at"),
    ), on="application_id", how="left")
    .join(df_evidence_count, on="application_id", how="left")
    .join(df_criteria_detail, on="application_id", how="left")
    .withColumn("days_since_lodged",
        F.datediff(F.current_date(), F.col("lodged_date").cast("date")))
    .withColumn("priority_score",
        F.when(F.col("urgency") == "urgent", F.lit(30)).otherwise(F.lit(0))
        + F.when(F.col("rules_outcome") == "borderline", F.lit(20)).otherwise(F.lit(0))
        + F.when(F.col("criteria_failed") > 0, F.lit(10)).otherwise(F.lit(0))
        + (F.col("criteria_needs_review") * 5)
        + F.col("days_since_lodged")
    )
    .withColumn("queue_status",
        F.when(F.col("rules_outcome") == "ineligible", F.lit("auto_declined"))
         .when(F.col("rules_outcome") == "eligible", F.lit("ready_for_approval"))
         .otherwise(F.lit("needs_review"))
    )
    .withColumn("queue_label",
        F.when(F.col("urgency") == "urgent", F.lit("Urgent"))
         .when(F.col("rules_outcome") == "borderline", F.lit("Borderline"))
         .when(F.col("rules_outcome") == "eligible", F.lit("Ready"))
         .otherwise(F.lit("Declined"))
    )
    .select(
        "application_id", "applicant_id", "full_name", "program_id", "program_name",
        "lodged_date", "urgency", "queue_status", "queue_label", "priority_score",
        "days_since_lodged",
        # Applicant summary
        "monthly_income", "num_dependent_children", "household_size",
        "weekly_rent", "monthly_rent", "rent_burden_pct",
        "residency_months", "max_absence_days", "absence_reason",
        "employment_type", "tenure_type", "rent_increase_recent",
        "identity_verified",
        # Rules summary
        "rules_outcome", "criteria_passed", "criteria_failed", "criteria_needs_review",
        "criteria_total", "criteria_detail",
        # Agent recommendation
        "agent_verdict", "agent_recommendation", "agent_generated_at",
        # Evidence
        "evidence_count", "evidence_verified", "evidence_needs_context",
        # Timestamps
        "refreshed_at",
    )
    .orderBy(F.desc("priority_score"))
)

df_queue.write.mode("overwrite").saveAsTable(fqn("caseworker_queue"))

print(f"caseworker_queue: {df_queue.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Seed the audit trail
# MAGIC
# MAGIC Record every system action as an immutable audit event. Human decisions
# MAGIC will be appended by the application interface.

# COMMAND ----------

# Build audit events from the pipeline execution.
from pyspark.sql import Row
from datetime import datetime

audit_events = []
ref_ts = datetime(2026, 10, 20, 9, 40, 0)

for row in df_queue.collect():
    app_id = row["application_id"]
    # 1. Application received
    audit_events.append(Row(
        event_id=f"EVT-{app_id}-001",
        application_id=app_id,
        event_type="application_received",
        description="Form and supporting documents ingested",
        actor="system",
        detail=f"{row['evidence_count'] or 0} documents submitted",
        timestamp=datetime.fromisoformat(f"{row['lodged_date']}T14:16:00"),
    ))
    # 2. Applicant 360 refreshed
    audit_events.append(Row(
        event_id=f"EVT-{app_id}-002",
        application_id=app_id,
        event_type="applicant_360_refreshed",
        description="Source domains reconciled into applicant 360",
        actor="system",
        detail="Four source domains: identity, household, employment, housing",
        timestamp=datetime(2026, 10, 20, 9, 42, 0),
    ))
    # 3. Rules engine completed
    audit_events.append(Row(
        event_id=f"EVT-{app_id}-003",
        application_id=app_id,
        event_type="rules_engine_completed",
        description=f"{row['criteria_passed']} passed, {row['criteria_failed']} failed, {row['criteria_needs_review']} referred for review",
        actor="system",
        detail=f"Ruleset {row['program_id']}",
        timestamp=datetime(2026, 10, 20, 9, 43, 0),
    ))
    # 4. Agent recommendation (if borderline)
    if row["agent_verdict"] is not None:
        audit_events.append(Row(
            event_id=f"EVT-{app_id}-004",
            application_id=app_id,
            event_type="agent_recommendation_generated",
            description=f"{row['agent_verdict']} \u2014 citations captured, model response archived",
            actor="system",
            detail=f"Model endpoint used",
            timestamp=datetime(2026, 10, 20, 9, 44, 0),
        ))

df_audit = spark.createDataFrame(audit_events)
df_audit.write.mode("overwrite").saveAsTable(fqn("audit_trail"))

print(f"audit_trail: {df_audit.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create decisions table (empty — populated by caseworkers)

# COMMAND ----------

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {fqn('decisions')} (
        decision_id STRING,
        application_id STRING,
        caseworker_id STRING,
        caseworker_name STRING,
        outcome STRING COMMENT 'Eligible, Not eligible, or Request more information',
        rationale STRING,
        decided_at TIMESTAMP,
        agent_verdict STRING COMMENT 'What the system recommended at the time of decision',
        rules_outcome STRING COMMENT 'What the rules engine concluded'
    )
""")

print(f"decisions table ready: {fqn('decisions')}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Queue summary

# COMMAND ----------

df_queue.groupBy("queue_status", "queue_label").count().orderBy("queue_status").display()

# COMMAND ----------

df_queue.select(
    "application_id", "full_name", "program_name", "queue_label",
    "priority_score", "agent_verdict", "rules_outcome"
).orderBy(F.desc("priority_score")).display()
