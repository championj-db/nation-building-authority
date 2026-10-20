# Databricks notebook source
# MAGIC %md
# MAGIC # Agentic Triage — AI-Powered Borderline Case Assessment
# MAGIC
# MAGIC For applications where the rules engine returned `borderline` (at least one criterion
# MAGIC marked `needs_review`), this step asks a foundation model to:
# MAGIC
# MAGIC 1. Assemble the evidence for each unresolved criterion.
# MAGIC 2. Cite the applicable policy section.
# MAGIC 3. Produce a structured recommendation with reasoning.
# MAGIC
# MAGIC The output is a **recommendation**, never a determination. The human decides.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("model_endpoint", "databricks-meta-llama-3-3-70b-instruct")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
model_endpoint = dbutils.widgets.get("model_endpoint")

assert catalog, "catalog parameter is required"
assert schema, "schema parameter is required"

fqn = lambda table: f"{catalog}.{schema}.{table}"

print(f"Using model endpoint: {model_endpoint}")

# COMMAND ----------

from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Identify borderline applications

# COMMAND ----------

df_summary = spark.table(fqn("rules_summary"))
df_borderline_apps = df_summary.filter(F.col("rules_outcome") == "borderline").select("application_id")

print(f"Borderline applications: {df_borderline_apps.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build triage context per application
# MAGIC
# MAGIC For each borderline application, assemble:
# MAGIC - The applicant 360 summary
# MAGIC - The unresolved criteria with policy citations
# MAGIC - Relevant evidence documents

# COMMAND ----------

df_360 = spark.table(fqn("applicant_360"))
df_rules = spark.table(fqn("rules_results"))
df_policies = spark.table(fqn("policy_documents"))
df_evidence = spark.table(fqn("evidence_documents"))
df_movements = spark.table(fqn("source_movements"))

# Unresolved criteria for borderline apps
df_unresolved = (
    df_rules
    .join(df_borderline_apps, on="application_id", how="inner")
    .filter(F.col("result") == "needs_review")
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Construct prompt context per application
# MAGIC
# MAGIC Build a single prompt string per application that includes all the evidence
# MAGIC the agent needs to reason about.

# COMMAND ----------

# Join applicant context to borderline apps
df_context = (
    df_borderline_apps
    .join(df_360, on="application_id", how="inner")
    .select(
        "application_id", "applicant_id", "full_name", "program_id", "program_name",
        "monthly_income", "num_dependent_children", "household_size",
        "weekly_rent", "monthly_rent", "rent_burden_pct",
        "residency_months", "max_absence_days", "absence_reason",
        "employment_type", "tenure_type", "rent_increase_recent",
        "lodged_date", "urgency",
    )
)

# Aggregate unresolved criteria per application as JSON array
df_criteria_agg = (
    df_unresolved
    .groupBy("application_id")
    .agg(
        F.collect_list(
            F.struct(
                F.col("rule_id"),
                F.col("criterion_name"),
                F.col("policy_section"),
                F.col("threshold_type"),
                F.col("threshold_value"),
            )
        ).alias("unresolved_criteria")
    )
)

# Aggregate evidence docs per application
df_evidence_agg = (
    df_evidence
    .join(df_borderline_apps, on="application_id", how="inner")
    .groupBy("application_id")
    .agg(
        F.collect_list(
            F.struct("document_name", "category", "verification_status", "summary")
        ).alias("evidence_list")
    )
)

# Build the full triage context
df_triage_input = (
    df_context
    .join(df_criteria_agg, on="application_id", how="left")
    .join(df_evidence_agg, on="application_id", how="left")
    .withColumn("unresolved_criteria_json", F.to_json(F.col("unresolved_criteria")))
    .withColumn("evidence_list_json", F.to_json(F.col("evidence_list")))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build the prompt and call the model

# COMMAND ----------

# Construct the prompt column
df_prompted = df_triage_input.withColumn(
    "prompt",
    F.concat(
        F.lit("You are an eligibility triage agent for the Nation Building Authority. "),
        F.lit("Your role is to assess borderline benefit applications by examining evidence "),
        F.lit("against policy criteria, and produce a structured recommendation. "),
        F.lit("You must cite the specific policy section for each criterion you assess. "),
        F.lit("Your output is a RECOMMENDATION ONLY \u2014 a human caseworker makes the final decision.\n\n"),
        F.lit("APPLICATION: "), F.col("application_id"), F.lit(" \u2014 "), F.col("full_name"), F.lit("\n"),
        F.lit("PROGRAM: "), F.col("program_name"), F.lit("\n"),
        F.lit("MONTHLY INCOME: $"), F.col("monthly_income").cast("string"), F.lit("\n"),
        F.lit("HOUSEHOLD: "), F.col("household_size").cast("string"), F.lit(" members ("),
        F.col("num_dependent_children").cast("string"), F.lit(" dependent children)\n"),
        F.lit("WEEKLY RENT: $"), F.col("weekly_rent").cast("string"),
        F.when(F.col("rent_increase_recent") == True, F.lit(" (recent increase)")).otherwise(F.lit("")),
        F.lit(" | RENT BURDEN: "),
        F.coalesce(F.col("rent_burden_pct").cast("string"), F.lit("N/A")), F.lit("%\n"),
        F.lit("RESIDENCY: "), F.col("residency_months").cast("string"), F.lit(" months"),
        F.when(F.col("max_absence_days") > 0,
            F.concat(F.lit(" | LONGEST ABSENCE: "), F.col("max_absence_days").cast("string"),
                     F.lit(" days ("), F.coalesce(F.col("absence_reason"), F.lit("unknown")), F.lit(")")))
        .otherwise(F.lit("")),
        F.lit("\n\nUNRESOLVED CRITERIA:\n"), F.coalesce(F.col("unresolved_criteria_json"), F.lit("[]")),
        F.lit("\n\nEVIDENCE DOCUMENTS:\n"), F.coalesce(F.col("evidence_list_json"), F.lit("[]")),
        F.lit("\n\nFor each unresolved criterion, assess the available evidence, cite the policy section, "),
        F.lit("and state whether the criterion is LIKELY MET, LIKELY NOT MET, or INSUFFICIENT EVIDENCE. "),
        F.lit("Then provide an overall recommendation: LIKELY ELIGIBLE, LIKELY NOT ELIGIBLE, or REQUEST MORE INFORMATION. "),
        F.lit("Keep the response concise and structured."),
    )
)

# COMMAND ----------

# Call the foundation model via ai_query for each borderline application.
df_prompted.createOrReplaceTempView("triage_prompts")

model_ep = model_endpoint  # avoid f-string escaping issues

df_recommendations = spark.sql(f"""
    SELECT
        application_id,
        applicant_id,
        full_name,
        program_id,
        program_name,
        urgency,
        prompt,
        ai_query(
            '{model_ep}',
            prompt,
            modelParameters => named_struct('max_tokens', 1024, 'temperature', 0.1)
        ) AS agent_recommendation
    FROM triage_prompts
""")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parse and save recommendations

# COMMAND ----------

df_agent_out = df_recommendations.select(
    F.col("application_id"),
    F.col("applicant_id"),
    F.col("full_name"),
    F.col("program_id"),
    F.col("program_name"),
    F.col("urgency"),
    F.col("agent_recommendation"),
    # Extract the overall verdict from the recommendation text.
    F.when(F.lower(F.col("agent_recommendation")).contains("likely eligible"), F.lit("Likely eligible"))
     .when(F.lower(F.col("agent_recommendation")).contains("likely not eligible"), F.lit("Likely not eligible"))
     .when(F.lower(F.col("agent_recommendation")).contains("request more information"), F.lit("Request more information"))
     .otherwise(F.lit("Review required"))
     .alias("verdict"),
    F.lit(model_endpoint).alias("model_endpoint"),
    F.current_timestamp().alias("generated_at"),
)

df_agent_out.write.mode("overwrite").saveAsTable(fqn("agent_recommendations"))

print(f"agent_recommendations: {df_agent_out.count()} rows")
df_agent_out.select("application_id", "full_name", "verdict", "agent_recommendation").display()
