# Databricks notebook source
# MAGIC %md
# MAGIC # Applicant 360 Assembly
# MAGIC
# MAGIC Silver layer: assembles a unified applicant view from governed source systems.
# MAGIC Joins identity, household, employment, and housing records into a single
# MAGIC `applicant_360` table that the rules engine and triage agent consume.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")

assert catalog, "catalog parameter is required"
assert schema, "schema parameter is required"

fqn = lambda table: f"{catalog}.{schema}.{table}"

# COMMAND ----------

from pyspark.sql import functions as F

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load source system records

# COMMAND ----------

df_applicants = spark.table(fqn("applicants"))
df_applications = spark.table(fqn("applications"))
df_identity = spark.table(fqn("source_identity"))
df_household = spark.table(fqn("source_household"))
df_employment = spark.table(fqn("source_employment"))
df_housing = spark.table(fqn("source_housing"))
df_movements = spark.table(fqn("source_movements"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build Applicant 360
# MAGIC
# MAGIC Join across all four source domains on `applicant_id`, producing one row per
# MAGIC applicant with the key fields the rules engine needs.

# COMMAND ----------

# Identity enrichment
df_id_enriched = df_identity.select(
    F.col("applicant_id"),
    F.col("verified").alias("identity_verified"),
    F.col("full_name"),
    F.col("document_type").alias("id_document_type"),
    F.col("verification_date").alias("identity_verified_date"),
)

# Household enrichment
df_hh_enriched = df_household.select(
    F.col("applicant_id"),
    F.col("num_adults"),
    F.col("num_dependent_children"),
    F.col("household_size"),
    F.col("verification_date").alias("household_verified_date"),
    F.get_json_object(F.col("data_json"), "$.shared_custody").cast("boolean").alias("shared_custody"),
    F.get_json_object(F.col("data_json"), "$.custody_pct").cast("int").alias("custody_pct"),
)

# Employment enrichment
df_emp_enriched = df_employment.select(
    F.col("applicant_id"),
    F.col("employment_type"),
    F.col("monthly_income"),
    F.col("income_variable"),
    F.col("verification_date").alias("employment_verified_date"),
)

# Housing enrichment
df_hsg_enriched = df_housing.select(
    F.col("applicant_id"),
    F.col("tenure_type"),
    F.col("weekly_rent"),
    F.col("monthly_rent"),
    F.col("lease_current"),
    F.col("rent_increase_recent"),
    F.col("previous_weekly_rent"),
    F.col("verification_date").alias("housing_verified_date"),
)

# Movement summary: longest absence per applicant
df_absence = df_movements.groupBy("applicant_id").agg(
    F.max("absence_days").alias("max_absence_days"),
    F.count("*").alias("absence_count"),
    F.first("declared_reason").alias("absence_reason"),
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Join into unified 360 view

# COMMAND ----------

df_360 = (
    df_applicants
    .join(df_applications.select(
        "applicant_id", "application_id", "program_id", "program_name",
        "lodged_date", "status", "urgency"
    ), on="applicant_id", how="inner")
    .join(df_id_enriched, on="applicant_id", how="left")
    .join(df_hh_enriched, on="applicant_id", how="left")
    .join(df_emp_enriched, on="applicant_id", how="left")
    .join(df_hsg_enriched, on="applicant_id", how="left")
    .join(df_absence, on="applicant_id", how="left")
    .withColumn("max_absence_days", F.coalesce(F.col("max_absence_days"), F.lit(0)))
    .withColumn("absence_count", F.coalesce(F.col("absence_count"), F.lit(0)))
    .withColumn("rent_burden_pct", 
        F.when(F.col("monthly_income") > 0,
               F.round(F.col("monthly_rent") / F.col("monthly_income") * 100, 1))
        .otherwise(F.lit(None)))
    .withColumn("refreshed_at", F.current_timestamp())
)

# COMMAND ----------

df_360.write.mode("overwrite").saveAsTable(fqn("applicant_360"))

print(f"applicant_360: {df_360.count()} rows written to {fqn('applicant_360')}")
df_360.select(
    "application_id", "full_name", "program_name", "monthly_income",
    "num_dependent_children", "weekly_rent", "rent_burden_pct",
    "residency_months", "max_absence_days"
).display()
