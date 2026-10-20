# Databricks notebook source
# MAGIC %md
# MAGIC # Rules Engine — Deterministic Eligibility Assessment
# MAGIC
# MAGIC Evaluates each application against the hard eligibility criteria for its program.
# MAGIC Criteria marked `deterministic` are resolved to pass/fail; criteria marked
# MAGIC `judgement` are flagged for human review. Every evaluation is versioned so
# MAGIC past decisions can be reproduced against the ruleset in force at the time.

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
from datetime import date
import json

ref_date = date(2026, 10, 20)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load applicant 360 and criteria

# COMMAND ----------

df_360 = spark.table(fqn("applicant_360"))
df_criteria = spark.table(fqn("eligibility_criteria"))
df_programs = spark.table(fqn("programs"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evaluate deterministic criteria
# MAGIC
# MAGIC Cross-join each application with its program's criteria, then evaluate
# MAGIC deterministic rules in-engine. Judgement criteria pass through as `needs_review`.

# COMMAND ----------

# Join applications to their program criteria
df_eval = (
    df_360
    .join(df_criteria, on="program_id", how="inner")
    .join(
        df_programs.select("program_id", F.col("version").alias("ruleset_version")),
        on="program_id", how="left"
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Rule evaluation logic
# MAGIC
# MAGIC Each deterministic rule maps to a SQL expression. Judgement rules are sent to
# MAGIC the agentic triage step.

# COMMAND ----------

# Evaluate each criterion row.
df_results = df_eval.withColumn(
    "result",
    F.when(F.col("evaluation_type") == "judgement", F.lit("needs_review"))
    # Income below max threshold (HSP, ISP, CAP)
    .when(
        (F.col("threshold_type") == "income_max"),
        F.when(F.col("monthly_income") <= F.col("threshold_value"), F.lit("pass"))
         .otherwise(F.lit("fail"))
    )
    # Dependent children minimum (HSP)
    .when(
        (F.col("threshold_type") == "dependents_min"),
        F.when(F.col("num_dependent_children") >= F.col("threshold_value"), F.lit("pass"))
         .otherwise(F.lit("fail"))
    )
    # Residency months minimum
    .when(
        (F.col("threshold_type") == "residency_months_min"),
        F.when(F.col("residency_months") >= F.col("threshold_value"), F.lit("pass"))
         .otherwise(F.lit("fail"))
    )
    # Residency years minimum (DSP)
    .when(
        (F.col("threshold_type") == "residency_years_min"),
        F.when((F.col("residency_months") / 12) >= F.col("threshold_value"), F.lit("pass"))
         .otherwise(F.lit("fail"))
    )
    # Age range checks (ISP: 22-66, DSP: 16-67)
    .when(
        (F.col("threshold_type") == "age_range") & (F.col("program_id") == "ISP"),
        F.when((F.col("age") >= 22) & (F.col("age") <= 66), F.lit("pass"))
         .otherwise(F.lit("fail"))
    )
    .when(
        (F.col("threshold_type") == "age_range") & (F.col("program_id") == "DSP"),
        F.when((F.col("age") >= 16) & (F.col("age") <= 67), F.lit("pass"))
         .otherwise(F.lit("fail"))
    )
    # Care recipient relationship (CAP) — deterministic check on household
    .when(
        (F.col("threshold_type") == "relationship_valid"),
        F.when(F.col("household_size") >= 2, F.lit("pass"))
         .otherwise(F.lit("fail"))
    )
    .otherwise(F.lit("needs_review"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build rules_results table

# COMMAND ----------

df_rules_out = df_results.select(
    F.col("application_id"),
    F.col("applicant_id"),
    F.col("program_id"),
    F.col("rule_id"),
    F.col("criterion_name"),
    F.col("evaluation_type"),
    F.col("policy_section"),
    F.col("result"),
    F.col("ruleset_version"),
    F.col("threshold_type"),
    F.col("threshold_value"),
    # Capture the actual value evaluated for audit reproducibility.
    F.when(F.col("threshold_type").isin("income_max"), F.col("monthly_income"))
     .when(F.col("threshold_type") == "dependents_min", F.col("num_dependent_children").cast("double"))
     .when(F.col("threshold_type").isin("residency_months_min"), F.col("residency_months").cast("double"))
     .when(F.col("threshold_type") == "residency_years_min", (F.col("residency_months") / 12).cast("double"))
     .when(F.col("threshold_type") == "age_range", F.col("age").cast("double"))
     .when(F.col("threshold_type") == "relationship_valid", F.col("household_size").cast("double"))
     .alias("actual_value"),
    F.current_timestamp().alias("evaluated_at"),
)

df_rules_out.write.mode("overwrite").saveAsTable(fqn("rules_results"))

print(f"rules_results: {df_rules_out.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary by application

# COMMAND ----------

df_app_summary = (
    df_rules_out
    .groupBy("application_id")
    .agg(
        F.sum(F.when(F.col("result") == "pass", 1).otherwise(0)).alias("criteria_passed"),
        F.sum(F.when(F.col("result") == "fail", 1).otherwise(0)).alias("criteria_failed"),
        F.sum(F.when(F.col("result") == "needs_review", 1).otherwise(0)).alias("criteria_needs_review"),
        F.count("*").alias("criteria_total"),
    )
    .withColumn("rules_outcome",
        F.when(F.col("criteria_failed") > 0, F.lit("ineligible"))
         .when(F.col("criteria_needs_review") > 0, F.lit("borderline"))
         .otherwise(F.lit("eligible"))
    )
)

df_app_summary.write.mode("overwrite").saveAsTable(fqn("rules_summary"))

print(f"rules_summary: {df_app_summary.count()} rows")
df_app_summary.display()
