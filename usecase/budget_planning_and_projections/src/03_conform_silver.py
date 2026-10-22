# Databricks notebook source
# MAGIC %md
# MAGIC # 03 Conform silver - the portfolio model
# MAGIC
# MAGIC Turns raw bronze extracts into the typed, validated, conformed portfolio model:
# MAGIC
# MAGIC * **Snapshot extracts** (register, assurance, assumptions, market model) keep the latest delivery per key.
# MAGIC * **Ledger postings** are de-duplicated on `txn_id` and aggregated to project-month-cost element actuals.
# MAGIC * Money is conformed to **AUD millions**; months to the first of the month with the Australian
# MAGIC   Government financial year (`fy`, `financial_year`).
# MAGIC * Data-quality rules run on every table. `error` rules drop the failing rows, `warn` rules keep them;
# MAGIC   both are recorded in `dq_results` with the run id.
# MAGIC * Seeded scenarios are merged into the app-writable `scenario_definitions` / `scenario_levers`
# MAGIC   tables without touching user-created rows.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("run_id", "")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

run_id = dbutils.widgets.get("run_id") or new_run_id("SILVER")
dq_rows = []


def bronze(extract: str) -> DataFrame:
    return spark.table(table_name(f"bronze_{extract}"))


def latest(df: DataFrame, keys: list) -> DataFrame:
    """Latest delivered record per business key (snapshot semantics)."""
    w_ = Window.partitionBy(*keys).orderBy(F.col("_delivery_date").desc(), F.col("_ingested_at").desc())
    return df.withColumn("_rn", F.row_number().over(w_)).filter("_rn = 1").drop("_rn")


def fy_cols(df: DataFrame, month_col: str = "month") -> DataFrame:
    fy = F.when(F.month(month_col) >= 7, F.year(month_col) + 1).otherwise(F.year(month_col))
    return (df.withColumn("fy", fy.cast("int"))
              .withColumn("financial_year", F.concat(F.lit("FY"), F.lpad((F.col("fy") % 100).cast("string"), 2, "0"))))


def check(df: DataFrame, table: str, rules: list) -> DataFrame:
    """rules: (name, valid-row SQL predicate, severity). Error rows are dropped. Results are recorded.

    Predicates run through SQL over a temp view so they may use subqueries (referential checks).
    """
    total = df.count()
    for i, (name, predicate, severity) in enumerate(rules):
        view = f"_dq_{table}_{i}"
        df.createOrReplaceTempView(view)
        failed = spark.sql(f"SELECT count(*) FROM {view} WHERE NOT coalesce({predicate}, false)").first()[0]
        dq_rows.append((run_id, table, name, severity, int(failed), int(total), failed == 0))
        if failed:
            print(f"  DQ {severity:<5} {table}.{name}: {failed} of {total} rows")
        if severity == "error" and failed:
            df = spark.sql(f"SELECT * FROM {view} WHERE coalesce({predicate}, false)")
    return df


LINEAGE = ["_delivery_date", "_source_file"]
SILVER_TAGS = {"nba_layer": "silver"}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Portfolio register

# COMMAND ----------

programs = check(latest(bronze("programs"), ["program_id"]).select(
    "program_id", "program_name", "sector", "subsector", "lead_jurisdiction", "delivery_agency", "program_executive", *LINEAGE),
    "silver_programs", [("program_id_present", "program_id IS NOT NULL", "error"),
                        ("sector_valid", "sector IN ('Transport','Energy','Water','Social')", "error")])
write_table(programs, "silver_programs", "Silver: conformed program register (synthetic).", tags=SILVER_TAGS)

projects = latest(bronze("projects"), ["project_id"]).select(
    "project_id", "program_id", "project_name", "sector", "subsector", "jurisdiction", "region_type", "delivery_agency",
    "delivery_model", "lifecycle_stage", F.col("priority_tier").cast("int").alias("priority_tier"), "schedule_flexibility",
    "funding_source", F.col("commonwealth_share_pct").cast("double").alias("commonwealth_share_pct"),
    (F.col("tec_p50_aud").cast("double") / 1e6).alias("tec_p50_aud_m"), (F.col("tec_p90_aud").cast("double") / 1e6).alias("tec_p90_aud_m"),
    F.col("contingency_pct").cast("double").alias("contingency_pct"),
    F.to_date("baseline_start").alias("baseline_start"), F.to_date("baseline_finish").alias("baseline_finish"),
    F.col("bcr").cast("double").alias("bcr"), (F.col("benefits_pv_aud").cast("double") / 1e6).alias("benefits_pv_aud_m"),
    "benefit_category", *LINEAGE)
projects = check(projects, "silver_projects", [
    ("project_id_present", "project_id IS NOT NULL", "error"),
    ("program_exists", f"program_id IN (SELECT program_id FROM {fqn('silver_programs')})", "error"),
    ("tec_positive", "tec_p50_aud_m > 0", "error"),
    ("p90_ge_p50", "tec_p90_aud_m >= tec_p50_aud_m", "warn"),
    ("dates_ordered", "baseline_finish > baseline_start", "error"),
    ("bcr_plausible", "bcr BETWEEN 0.3 AND 6", "warn"),
])
write_table(projects, "silver_projects", "Silver: conformed project register with cost (P50/P90, AUD m), schedule and benefit profile (synthetic).",
            {"tec_p50_aud_m": "Total estimated cost, P50, AUD millions nominal (endorsed).",
             "tec_p90_aud_m": "Total estimated cost, P90, AUD millions nominal.",
             "schedule_flexibility": "Deferrable projects may be resequenced by capacity-balancing scenarios; Fixed may not.",
             "priority_tier": "1 = highest government priority.", "bcr": "Benefit-cost ratio from the endorsed business case."},
            tags=SILVER_TAGS)
project_ids = spark.table(table_name("silver_projects")).select("project_id")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Plan, ledger and suppliers

# COMMAND ----------

plan_versions = latest(bronze("plan_versions"), ["plan_version"]).select(
    "plan_version", "plan_name", F.col("version").cast("int").alias("version"), F.to_date("approved_date").alias("approved_date"),
    "approved_by", "status", "price_basis", *LINEAGE)
write_table(plan_versions, "silver_plan_versions", "Silver: budget plan versions.", tags=SILVER_TAGS)

phasing = fy_cols(latest(bronze("plan_phasing"), ["plan_version", "project_id", "month"]).select(
    "plan_version", "project_id", F.to_date("month").alias("month"), (F.col("amount_aud").cast("double") / 1e6).alias("plan_aud_m"), *LINEAGE))
phasing = check(phasing, "silver_plan_phasing", [
    ("project_exists", f"project_id IN (SELECT project_id FROM {fqn('silver_projects')})", "error"),
    ("month_first_day", "day(month) = 1", "error"),
    ("amount_non_negative", "plan_aud_m >= 0", "error"),
])
write_table(phasing, "silver_plan_phasing", "Silver: endorsed plan monthly phasing by project, AUD millions nominal.", tags=SILVER_TAGS)

w_txn = Window.partitionBy("txn_id").orderBy(F.col("_ingested_at").desc())
gl = (bronze("gl_transactions").withColumn("_rn", F.row_number().over(w_txn)).filter("_rn = 1")
      .select("txn_id", "period", F.to_date("posting_date").alias("posting_date"), "project_id", "wbs_code", "cost_element",
              "supplier_id", "document_type", "document_number", F.col("amount_aud").cast("decimal(18,2)").alias("amount_aud"),
              "currency", "ledger", "_source_file", "_ingested_at"))
gl = check(gl, "silver_gl_transactions", [
    ("project_exists", f"project_id IN (SELECT project_id FROM {fqn('silver_projects')})", "error"),
    ("amount_present", "amount_aud IS NOT NULL", "error"),
    ("currency_aud", "currency = 'AUD'", "error"),
    ("posting_in_period", "date_format(posting_date, 'yyyy-MM') = period", "error"),
    ("supplier_present", "supplier_id IS NOT NULL", "warn"),
])
write_table(gl, "silver_gl_transactions", "Silver: general-ledger capital postings, de-duplicated on txn_id (synthetic).",
            {"amount_aud": "Posting amount, AUD (not millions)."}, tags=SILVER_TAGS)

actuals = fy_cols(spark.table(table_name("silver_gl_transactions"))
                  .withColumn("month", F.trunc("posting_date", "month"))
                  .groupBy("project_id", "month", "cost_element")
                  .agg((F.sum("amount_aud").cast("double") / 1e6).alias("actual_aud_m"), F.count("*").alias("postings")))
write_table(actuals, "silver_actuals_monthly", "Silver: actual expenditure by project, month and cost element (AUD millions), aggregated from the ledger.",
            tags=SILVER_TAGS)

suppliers = latest(bronze("suppliers"), ["supplier_id"]).select(
    "supplier_id", "supplier_name", "supplier_category", "abn", "state", "supplier_tier",
    (F.lower("indigenous_business") == "true").alias("indigenous_business"), F.to_date("onboarded_date").alias("onboarded_date"), *LINEAGE)
write_table(suppliers, "silver_suppliers", "Silver: supplier master (synthetic names and ABNs).", tags=SILVER_TAGS)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Project controls and assurance

# COMMAND ----------

changes = latest(bronze("change_register"), ["change_id"]).select(
    "change_id", "project_id", "change_type", "description", (F.col("cost_impact_aud").cast("double") / 1e6).alias("cost_impact_aud_m"),
    F.col("schedule_impact_months").cast("int").alias("schedule_impact_months"), "status",
    F.to_date("raised_date").alias("raised_date"), F.to_date("approved_date").alias("approved_date"), "approver", "source_system", *LINEAGE)
changes = check(changes, "silver_change_register", [
    ("project_exists", f"project_id IN (SELECT project_id FROM {fqn('silver_projects')})", "error"),
    ("type_valid", "change_type IN ('Schedule','Scope','Packaging')", "error"),
    ("approved_has_date", "status <> 'Approved' OR approved_date IS NOT NULL", "error"),
    ("approved_after_raised", "approved_date IS NULL OR approved_date >= raised_date", "warn"),
])
write_table(changes, "silver_change_register", "Silver: project change requests. Only Approved changes enter the forecast; Pending are visible but excluded.",
            {"cost_impact_aud_m": "Cost impact of the change, AUD millions nominal (negative = saving).",
             "schedule_impact_months": "Months of schedule slip (positive) the change introduces."}, tags=SILVER_TAGS)

w_last = Window.partitionBy("project_id").orderBy(F.col("report_date").desc(), F.col("gate").desc())
reviews = (latest(bronze("gateway_reviews"), ["review_id"])
           .select("review_id", "project_id", F.col("gate").cast("int").alias("gate"), "gate_name", "review_type",
                   F.to_date("review_start").alias("review_start"), F.to_date("report_date").alias("report_date"), "delivery_confidence",
                   F.col("recommendations_total").cast("int").alias("recommendations_total"),
                   F.col("recommendations_critical").cast("int").alias("recommendations_critical"),
                   "review_team_lead", "senior_responsible_official", "summary", *LINEAGE)
           .withColumn("is_latest", F.row_number().over(w_last) == 1))
reviews = check(reviews, "silver_gateway_reviews", [
    ("project_exists", f"project_id IN (SELECT project_id FROM {fqn('silver_projects')})", "error"),
    ("rating_valid", "delivery_confidence IN ('Green','Amber/Green','Amber','Amber/Red','Red')", "error"),
])
write_table(reviews, "silver_gateway_reviews", "Silver: Gateway review reports with delivery confidence rating (5-point scale). is_latest marks the current rating per project.",
            tags=SILVER_TAGS)

assumptions = latest(bronze("assumptions_register"), ["assumption_id"]).select(
    "assumption_id", "title", "assumption_type", "owner", "confidence", "approval_status", F.col("version").cast("int").alias("version"),
    F.to_date("effective_from").alias("effective_from"), F.to_date("last_reviewed").alias("last_reviewed"),
    F.to_date("next_review_due").alias("next_review_due"), "evidence_reference", "value_summary", *LINEAGE)
assumptions = check(assumptions, "silver_assumptions", [
    ("status_valid", "approval_status IN ('Endorsed','Working','Action required','Awaiting attestation')", "error"),
    ("has_evidence", "evidence_reference IS NOT NULL", "warn"),
])
write_table(assumptions, "silver_assumptions", "Silver: governed assumptions register (economic, market, fiscal, delivery, cost estimate).", tags=SILVER_TAGS)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Economic and market capacity model

# COMMAND ----------

esc = latest(bronze("escalation_rates"), ["sector", "fy"]).select(
    "assumption_id", "sector", F.col("fy").cast("int").alias("fy"), "financial_year",
    F.col("endorsed_rate").cast("double").alias("endorsed_rate"), F.col("current_rate").cast("double").alias("current_rate"), *LINEAGE)
esc = check(esc, "silver_escalation_rates", [("rate_range", "current_rate BETWEEN -0.05 AND 0.2 AND endorsed_rate BETWEEN -0.05 AND 0.2", "error")])
write_table(esc, "silver_escalation_rates", "Silver: construction escalation rates by sector and FY, endorsed (at budget) vs current.",
            {"endorsed_rate": "Escalation rate assumed in the endorsed plan (decimal p.a.).",
             "current_rate": "Current escalation assumption (decimal p.a.)."}, tags=SILVER_TAGS)

defl = latest(bronze("price_deflator"), ["fy"]).select("assumption_id", F.col("fy").cast("int").alias("fy"), "financial_year",
                                                     F.col("cpi_rate").cast("double").alias("cpi_rate"), *LINEAGE)
write_table(defl, "silver_price_deflator", "Silver: CPI deflator used for real (constant price) reporting.", tags=SILVER_TAGS)

env = latest(bronze("funding_envelope"), ["fy"]).select("assumption_id", F.col("fy").cast("int").alias("fy"), "financial_year",
                                                      (F.col("envelope_aud").cast("double") / 1e6).alias("envelope_aud_m"), *LINEAGE)
write_table(env, "silver_funding_envelope", "Silver: five-year funding envelope by FY, AUD millions nominal.", tags=SILVER_TAGS)

cats = latest(bronze("capacity_categories"), ["category_id"]).select(
    "category_id", "category_name", "unit", F.col("growth_rate").cast("double").alias("growth_rate"), "assumption_id",
    F.col("constrained_threshold_pct").cast("double").alias("constrained_threshold_pct"),
    F.col("breach_threshold_pct").cast("double").alias("breach_threshold_pct"), *LINEAGE)
write_table(cats, "silver_capacity_categories", "Silver: market capacity categories (delivery inputs) and utilisation thresholds.", tags=SILVER_TAGS)

cap = latest(bronze("market_capacity"), ["model_version", "category_id", "fy"]).select(
    "model_version", "category_id", F.col("fy").cast("int").alias("fy"), "financial_year",
    F.col("available_units").cast("double").alias("available_units"), F.col("national_units").cast("double").alias("national_units"),
    F.col("portfolio_share_pct").cast("double").alias("portfolio_share_pct"), "assumption_id", *LINEAGE)
cap = check(cap, "silver_market_capacity", [("supply_positive", "available_units > 0", "error"),
                                            ("category_exists", f"category_id IN (SELECT category_id FROM {fqn('silver_capacity_categories')})", "error")])
write_table(cap, "silver_market_capacity", "Silver: modelled annual supply available to the portfolio by capacity category and FY.",
            {"available_units": "Supply available to this portfolio in the category unit."}, tags=SILVER_TAGS)

intensity = latest(bronze("demand_intensity"), ["subsector", "category_id"]).select(
    "subsector", "category_id", F.col("units_per_aud_m").cast("double").alias("units_per_aud_m"), *LINEAGE)
write_table(intensity, "silver_demand_intensity", "Silver: demand intensity - units of each capacity input per AUD 1m of annual spend, by subsector.", tags=SILVER_TAGS)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Scenario seeds -> app-writable scenario tables

# COMMAND ----------

seed_defs = latest(bronze("scenario_definitions"), ["scenario_id", "version"]).select(
    "scenario_id", "scenario_name", F.col("version").cast("int").alias("version"), "base_scenario_id", "method", "status",
    "decision_purpose", "description", "created_by", F.to_timestamp("created_at").alias("created_at"), F.lit("seed").alias("source"))
seed_defs.createOrReplaceTempView("seed_defs")
spark.sql(f"""MERGE INTO {fqn('scenario_definitions')} t USING seed_defs s
              ON t.scenario_id = s.scenario_id AND t.version = s.version
              WHEN NOT MATCHED THEN INSERT *""")
seed_levers = latest(bronze("scenario_levers"), ["lever_id"]).select(
    "lever_id", "scenario_id", F.col("scenario_version").cast("int").alias("scenario_version"), "lever_type", "target_type", "target_id",
    F.col("value").cast("double").alias("value"), "rationale", "assumption_id", "created_by", F.to_timestamp("created_at").alias("created_at"),
    F.lit("seed").alias("source"))
seed_levers.createOrReplaceTempView("seed_levers")
spark.sql(f"""MERGE INTO {fqn('scenario_levers')} t USING seed_levers s ON t.lever_id = s.lever_id
              WHEN NOT MATCHED THEN INSERT *""")

# COMMAND ----------

dq = spark.createDataFrame(dq_rows, "run_id string, table_name string, rule string, severity string, failed_rows long, total_rows long, passed boolean")
(dq.withColumn("checked_at", F.current_timestamp())
   .select("run_id", "checked_at", "table_name", "rule", "severity", "failed_rows", "total_rows", "passed")
   .write.mode("append").saveAsTable(table_name("dq_results")))
failed_errors = [r for r in dq_rows if r[3] == "error" and r[4]]
print(f"Silver complete. DQ rules: {len(dq_rows)}, failing error rules: {len(failed_errors)} (rows dropped), "
      f"failing warn rules: {sum(1 for r in dq_rows if r[3] == 'warn' and r[4])}")
