# Databricks notebook source
# MAGIC %md
# MAGIC # Synthetic Data Generator — AI-Enabled Eligibility Determination
# MAGIC
# MAGIC Generates wholly synthetic, deterministically seeded data for:
# MAGIC - Applicants and their applications
# MAGIC - Source system records (identity, household, employment, housing)
# MAGIC - Evidence documents
# MAGIC - Eligibility programs with criteria
# MAGIC - Policy documents for agent citation
# MAGIC - Audit trail seed events
# MAGIC
# MAGIC No real data. Everything is reproducible from the seed.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("seed", "42")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
seed = int(dbutils.widgets.get("seed"))

assert catalog, "catalog parameter is required"
assert schema, "schema parameter is required"

fqn = lambda table: f"{catalog}.{schema}.{table}"

print(f"Writing to {catalog}.{schema} with seed {seed}")

# COMMAND ----------

import random
import json
from datetime import datetime, date, timedelta
from pyspark.sql import functions as F
from pyspark.sql.types import (
    StructType, StructField, StringType, IntegerType, DoubleType,
    DateType, TimestampType, BooleanType, ArrayType
)

rng = random.Random(seed)

# Reference date anchoring all generated timestamps.
ref_date = date(2026, 10, 20)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Eligibility Programs & Criteria

# COMMAND ----------

programs = [
    {"program_id": "HSP", "program_name": "Housing Support Program",
     "description": "Assists low-income households with housing costs when rental burden exceeds policy thresholds.",
     "version": "HS-2026.4", "effective_date": "2026-01-01"},
    {"program_id": "ISP", "program_name": "Income Support Program",
     "description": "Provides supplementary income to individuals below the income threshold who meet activity requirements.",
     "version": "IS-2026.3", "effective_date": "2026-01-01"},
    {"program_id": "CAP", "program_name": "Carer Allowance Program",
     "description": "Supports carers providing daily care to a person with a disability or medical condition.",
     "version": "CA-2026.2", "effective_date": "2026-01-01"},
    {"program_id": "DSP", "program_name": "Disability Support Program",
     "description": "Financial support for people with a permanent disability that limits work capacity.",
     "version": "DS-2026.2", "effective_date": "2026-01-01"},
]

df_programs = spark.createDataFrame(programs)
df_programs.write.mode("overwrite").saveAsTable(fqn("programs"))
print(f"programs: {df_programs.count()} rows")

# COMMAND ----------

# Eligibility criteria per program. Each criterion has a rule_id, description,
# evaluation_type (deterministic or judgement), and the policy section it cites.
criteria_rows = [
    # Housing Support Program
    {"program_id": "HSP", "rule_id": "HSP-2.1", "criterion_name": "Income below program threshold",
     "description": "Household income must fall below the program threshold for the household size.",
     "evaluation_type": "deterministic", "policy_section": "\u00a72.1",
     "threshold_type": "income_max", "threshold_value": 3200.0},
    {"program_id": "HSP", "rule_id": "HSP-3.4", "criterion_name": "Dependent children in household",
     "description": "At least one dependent child must reside in the household.",
     "evaluation_type": "deterministic", "policy_section": "\u00a73.4",
     "threshold_type": "dependents_min", "threshold_value": 1.0},
    {"program_id": "HSP", "rule_id": "HSP-4.3", "criterion_name": "Housing cost burden",
     "description": "Rental costs must exceed 30% of gross household income, with evidence of current lease terms.",
     "evaluation_type": "judgement", "policy_section": "\u00a74.3",
     "threshold_type": "rent_burden_pct", "threshold_value": 30.0},
    {"program_id": "HSP", "rule_id": "HSP-6.2", "criterion_name": "Continuous residency",
     "description": "Applicant must have maintained continuous residency for 12+ months, with permitted exceptions for absences.",
     "evaluation_type": "judgement", "policy_section": "\u00a76.2(b)",
     "threshold_type": "residency_months_min", "threshold_value": 12.0},
    # Income Support Program
    {"program_id": "ISP", "rule_id": "ISP-1.1", "criterion_name": "Age eligibility",
     "description": "Applicant must be between 22 and 66 years of age.",
     "evaluation_type": "deterministic", "policy_section": "\u00a71.1",
     "threshold_type": "age_range", "threshold_value": 0.0},
    {"program_id": "ISP", "rule_id": "ISP-2.1", "criterion_name": "Income below threshold",
     "description": "Personal fortnightly income must be below $1,350.",
     "evaluation_type": "deterministic", "policy_section": "\u00a72.1",
     "threshold_type": "income_max", "threshold_value": 2700.0},
    {"program_id": "ISP", "rule_id": "ISP-3.1", "criterion_name": "Activity test",
     "description": "Applicant must demonstrate active job-seeking or approved activity.",
     "evaluation_type": "judgement", "policy_section": "\u00a73.1",
     "threshold_type": "activity_required", "threshold_value": 1.0},
    {"program_id": "ISP", "rule_id": "ISP-5.1", "criterion_name": "Residency requirement",
     "description": "Must be a resident for a qualifying period of at least 24 months.",
     "evaluation_type": "deterministic", "policy_section": "\u00a75.1",
     "threshold_type": "residency_months_min", "threshold_value": 24.0},
    # Carer Allowance Program
    {"program_id": "CAP", "rule_id": "CAP-1.1", "criterion_name": "Care recipient relationship",
     "description": "Applicant provides daily care to an immediate family member or household member.",
     "evaluation_type": "deterministic", "policy_section": "\u00a71.1",
     "threshold_type": "relationship_valid", "threshold_value": 1.0},
    {"program_id": "CAP", "rule_id": "CAP-2.1", "criterion_name": "Care recipient medical assessment",
     "description": "Care recipient must have a verified disability or medical condition score above threshold.",
     "evaluation_type": "judgement", "policy_section": "\u00a72.1",
     "threshold_type": "medical_score_min", "threshold_value": 20.0},
    {"program_id": "CAP", "rule_id": "CAP-3.1", "criterion_name": "Income test",
     "description": "Combined household income must not exceed the carer income threshold.",
     "evaluation_type": "deterministic", "policy_section": "\u00a73.1",
     "threshold_type": "income_max", "threshold_value": 4500.0},
    {"program_id": "CAP", "rule_id": "CAP-4.1", "criterion_name": "Daily care hours",
     "description": "Applicant must provide at least 20 hours per week of personal care.",
     "evaluation_type": "judgement", "policy_section": "\u00a74.1",
     "threshold_type": "care_hours_min", "threshold_value": 20.0},
    # Disability Support Program
    {"program_id": "DSP", "rule_id": "DSP-1.1", "criterion_name": "Disability verification",
     "description": "Applicant has a permanent physical, intellectual or psychiatric condition verified by a medical panel.",
     "evaluation_type": "judgement", "policy_section": "\u00a71.1",
     "threshold_type": "disability_verified", "threshold_value": 1.0},
    {"program_id": "DSP", "rule_id": "DSP-2.1", "criterion_name": "Work capacity assessment",
     "description": "Assessed work capacity must be below 15 hours per week within the next two years.",
     "evaluation_type": "judgement", "policy_section": "\u00a72.1",
     "threshold_type": "work_capacity_max", "threshold_value": 15.0},
    {"program_id": "DSP", "rule_id": "DSP-3.1", "criterion_name": "Residency requirement",
     "description": "Must be a resident with at least 10 years cumulative residency.",
     "evaluation_type": "deterministic", "policy_section": "\u00a73.1",
     "threshold_type": "residency_years_min", "threshold_value": 10.0},
    {"program_id": "DSP", "rule_id": "DSP-4.1", "criterion_name": "Age eligibility",
     "description": "Applicant must be at least 16 and below Age Pension age.",
     "evaluation_type": "deterministic", "policy_section": "\u00a74.1",
     "threshold_type": "age_range", "threshold_value": 0.0},
]

df_criteria = spark.createDataFrame(criteria_rows)
df_criteria.write.mode("overwrite").saveAsTable(fqn("eligibility_criteria"))
print(f"eligibility_criteria: {df_criteria.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Policy Documents

# COMMAND ----------

policy_documents = [
    {"policy_id": "POL-HSP-2026.4", "program_id": "HSP", "version": "2026.4",
     "section": "\u00a72.1", "title": "Income threshold for housing support",
     "text": "A household is eligible under the income criterion where the combined gross income of all household members, calculated on a monthly basis using the most recent four weeks of verified income data, does not exceed $3,200 per month for a single-adult household, with an additional $400 allowance for each dependent child. Income from irregular sources must be averaged over 12 weeks.",
     "effective_date": "2026-01-01"},
    {"policy_id": "POL-HSP-2026.4-3.4", "program_id": "HSP", "version": "2026.4",
     "section": "\u00a73.4", "title": "Dependent children requirement",
     "text": "At least one dependent child must ordinarily reside in the household. A dependent child is a person under 16 years of age, or under 22 if in full-time education, who is substantially in the care of the applicant. Shared custody arrangements satisfy this criterion where the child resides with the applicant for at least 35% of nights in a standard care period.",
     "effective_date": "2026-01-01"},
    {"policy_id": "POL-HSP-2026.4-4.3", "program_id": "HSP", "version": "2026.4",
     "section": "\u00a74.3", "title": "Housing cost burden assessment",
     "text": "Eligibility under the housing cost burden criterion requires that verified rental or mortgage costs exceed 30 percent of the household gross income. Where the most recent lease or mortgage statement shows a change in housing costs not yet reflected in automated feeds, the caseworker must verify the change against the signed agreement and apply the updated figure. A rent increase within the past 90 days supported by a signed lease variation is accepted as current.",
     "effective_date": "2026-01-01"},
    {"policy_id": "POL-HSP-2026.4-6.2", "program_id": "HSP", "version": "2026.4",
     "section": "\u00a76.2(b)", "title": "Temporary absence and continuous residency",
     "text": "Continuous residency requires the applicant to have maintained their principal place of residence in the jurisdiction for at least 12 consecutive months prior to the date of application. A temporary absence of up to 56 days may be disregarded where the applicant travelled to provide essential care to an immediate family member and maintained their principal residence throughout the absence. The applicant must provide a statutory declaration or equivalent evidence of the care purpose. Absences exceeding 56 days require a permitted-exception assessment by a delegate.",
     "effective_date": "2026-01-01"},
    {"policy_id": "POL-ISP-2026.3-2.1", "program_id": "ISP", "version": "2026.3",
     "section": "\u00a72.1", "title": "Income test for income support",
     "text": "A person\u2019s fortnightly ordinary income must not exceed $2,700. Ordinary income includes wages, salary, business income and deemed income from financial assets. Where income varies, the average of the 6 most recent fortnightly periods is used.",
     "effective_date": "2026-01-01"},
    {"policy_id": "POL-ISP-2026.3-3.1", "program_id": "ISP", "version": "2026.3",
     "section": "\u00a73.1", "title": "Activity test",
     "text": "The applicant must demonstrate that they are actively seeking suitable paid work or participating in an approved activity for at least 20 hours per fortnight. Evidence includes job-search records, training provider reports, or approved volunteer service records. A caseworker may grant a temporary exemption for up to 13 weeks on medical or family grounds supported by documentary evidence.",
     "effective_date": "2026-01-01"},
    {"policy_id": "POL-CAP-2026.2-2.1", "program_id": "CAP", "version": "2026.2",
     "section": "\u00a72.1", "title": "Medical assessment for care recipient",
     "text": "The care recipient must have a disability or medical condition assessed at 20 or more points on the Adult Disability Assessment Tool (ADAT) or the equivalent Child Disability Assessment Tool (CDAT). The assessment must have been completed within the last 24 months by a qualified medical practitioner. Where the condition is degenerative, a prior assessment remains valid for 36 months.",
     "effective_date": "2026-01-01"},
    {"policy_id": "POL-CAP-2026.2-4.1", "program_id": "CAP", "version": "2026.2",
     "section": "\u00a74.1", "title": "Daily care hours requirement",
     "text": "The applicant must provide at least 20 hours per week of personal care and attention to the care recipient. Personal care includes assistance with daily living activities, mobility, communication, and health management. Supervision hours count only where the care recipient requires constant supervision due to behavioural or cognitive impairment as documented in the medical assessment.",
     "effective_date": "2026-01-01"},
    {"policy_id": "POL-DSP-2026.2-1.1", "program_id": "DSP", "version": "2026.2",
     "section": "\u00a71.1", "title": "Disability verification",
     "text": "The applicant must have a permanent physical, intellectual or psychiatric condition that has been diagnosed and verified by a medical panel comprising at least two qualified practitioners. The condition must be fully treated and stabilised, and must result in a functional impairment rating of 20 or more points on the Impairment Tables. Conditions that are likely to persist for less than two years do not meet the permanence requirement.",
     "effective_date": "2026-01-01"},
    {"policy_id": "POL-DSP-2026.2-2.1", "program_id": "DSP", "version": "2026.2",
     "section": "\u00a72.1", "title": "Work capacity assessment",
     "text": "The applicant\u2019s assessed work capacity must be below 15 hours per week of work at or above the relevant minimum wage, within the next two years, with or without the assistance of a Disability Employment Services program. The assessment considers functional limitations, transferable skills, labour market conditions in the applicant\u2019s region, and any program of support already undertaken.",
     "effective_date": "2026-01-01"},
]

df_policies = spark.createDataFrame(policy_documents)
df_policies.write.mode("overwrite").saveAsTable(fqn("policy_documents"))
print(f"policy_documents: {df_policies.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Applicants & Applications

# COMMAND ----------

# Synthetic applicant pool — seeded names, demographics, and circumstances.
first_names = ["Maya", "Elias", "Amina", "Noah", "Priya", "Liam", "Fatima", "James",
               "Sofia", "Oliver", "Aisha", "William", "Zara", "Thomas", "Mei", "Daniel",
               "Nadia", "Benjamin", "Leila", "Samuel", "Rosa", "Patrick", "Hana", "David"]
last_names = ["Chen", "Turner", "Diallo", "Wilson", "Sharma", "O'Brien", "Hassan", "Mitchell",
              "Petrov", "Nguyen", "Ibrahim", "Campbell", "Rahman", "Foster", "Li", "Kelly",
              "Yilmaz", "Harris", "Tanaka", "Moore", "Garcia", "Sullivan", "Kim", "Bennett"]

rng.shuffle(first_names)
rng.shuffle(last_names)

applicants = []
applications = []

program_ids = ["HSP", "ISP", "CAP", "DSP"]
program_map = {p["program_id"]: p["program_name"] for p in programs}

for i in range(24):
    applicant_id = f"APL-{1000 + i}"
    fn = first_names[i]
    ln = last_names[i]
    age = rng.randint(19, 68)
    dob = date(ref_date.year - age, rng.randint(1, 12), rng.randint(1, 28))
    gender = rng.choice(["Female", "Male", "Non-binary"])
    residency_months = rng.randint(6, 180)
    lodged_offset = rng.randint(0, 14)
    lodged_date = ref_date - timedelta(days=lodged_offset)

    applicants.append({
        "applicant_id": applicant_id,
        "first_name": fn,
        "last_name": ln,
        "date_of_birth": str(dob),
        "age": age,
        "gender": gender,
        "email": f"{fn.lower()}.{ln.lower().replace("'", '')}@example.gov.au",
        "phone": f"+61 4{rng.randint(10,99)} {rng.randint(100,999)} {rng.randint(100,999)}",
        "residency_months": residency_months,
    })

    # Each applicant gets one application for a randomly assigned program.
    pid = program_ids[i % len(program_ids)]
    app_id = f"APP-{2024 + i}"
    urgency = rng.choice(["standard", "standard", "urgent", "standard"])

    applications.append({
        "application_id": app_id,
        "applicant_id": applicant_id,
        "program_id": pid,
        "program_name": program_map[pid],
        "lodged_date": str(lodged_date),
        "status": "pending_review",
        "urgency": urgency,
    })

df_applicants = spark.createDataFrame(applicants)
df_applicants.write.mode("overwrite").saveAsTable(fqn("applicants"))
print(f"applicants: {df_applicants.count()} rows")

df_applications = spark.createDataFrame(applications)
df_applications.write.mode("overwrite").saveAsTable(fqn("applications"))
print(f"applications: {df_applications.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Source System Records
# MAGIC
# MAGIC Simulates data from four governed source systems that feed the Applicant 360.

# COMMAND ----------

# Identity registry records
identity_records = []
for a in applicants:
    identity_records.append({
        "applicant_id": a["applicant_id"],
        "source_system": "identity_registry",
        "domain": "identity",
        "record_type": "identity_verification",
        "verified": True,
        "full_name": f"{a['first_name']} {a['last_name']}",
        "date_of_birth": a["date_of_birth"],
        "document_type": rng.choice(["passport", "drivers_licence", "proof_of_age"]),
        "verification_date": str(ref_date - timedelta(days=rng.randint(0, 5))),
        "data_json": json.dumps({
            "full_name": f"{a['first_name']} {a['last_name']}",
            "dob": a["date_of_birth"],
            "gender": a["gender"],
            "nationality": "Australian" if rng.random() > 0.15 else "Permanent Resident",
        }),
    })

df_identity = spark.createDataFrame(identity_records)
df_identity.write.mode("overwrite").saveAsTable(fqn("source_identity"))
print(f"source_identity: {df_identity.count()} rows")

# COMMAND ----------

# Household records (birth registry, household composition)
household_records = []
for a in applicants:
    num_adults = rng.choice([1, 1, 2, 2, 1])
    num_children = rng.choice([0, 0, 1, 1, 2, 2, 3])
    household_records.append({
        "applicant_id": a["applicant_id"],
        "source_system": "birth_registry",
        "domain": "household",
        "record_type": "household_composition",
        "num_adults": num_adults,
        "num_dependent_children": num_children,
        "household_size": num_adults + num_children,
        "verification_date": str(ref_date - timedelta(days=rng.randint(1, 7))),
        "data_json": json.dumps({
            "adults": num_adults,
            "dependent_children": num_children,
            "shared_custody": rng.random() > 0.8,
            "custody_pct": rng.choice([50, 60, 70, 80, 100]) if num_children > 0 else None,
        }),
    })

df_household = spark.createDataFrame(household_records)
df_household.write.mode("overwrite").saveAsTable(fqn("source_household"))
print(f"source_household: {df_household.count()} rows")

# COMMAND ----------

# Employment / income records
employment_records = []
for a in applicants:
    monthly_income = rng.choice([0, 800, 1200, 1600, 1920, 2400, 2800, 3200, 3600, 4200])
    emp_type = "unemployed" if monthly_income == 0 else rng.choice(
        ["full-time", "part-time", "part-time", "casual", "casual"])
    employment_records.append({
        "applicant_id": a["applicant_id"],
        "source_system": "payroll_reporting",
        "domain": "employment",
        "record_type": "income_verification",
        "employment_type": emp_type,
        "monthly_income": float(monthly_income),
        "income_variable": emp_type in ("casual", "part-time"),
        "employer_name": f"Employer-{rng.randint(100, 999)}" if monthly_income > 0 else None,
        "verification_date": str(ref_date - timedelta(days=rng.randint(2, 10))),
        "data_json": json.dumps({
            "gross_monthly": monthly_income,
            "employment_type": emp_type,
            "variable_hours": emp_type in ("casual", "part-time"),
            "weeks_employed": rng.randint(4, 260) if monthly_income > 0 else 0,
        }),
    })

df_employment = spark.createDataFrame(employment_records)
df_employment.write.mode("overwrite").saveAsTable(fqn("source_employment"))
print(f"source_employment: {df_employment.count()} rows")

# COMMAND ----------

# Housing records (lease + property feed)
housing_records = []
for a in applicants:
    weekly_rent = rng.choice([0, 280, 350, 420, 480, 520, 580, 640, 720, 800])
    has_lease = weekly_rent > 0
    rent_increase_recent = has_lease and rng.random() > 0.7
    housing_records.append({
        "applicant_id": a["applicant_id"],
        "source_system": "property_feed",
        "domain": "housing",
        "record_type": "housing_assessment",
        "tenure_type": "private_rental" if has_lease else rng.choice(["owner_occupier", "public_housing", "homeless"]),
        "weekly_rent": float(weekly_rent),
        "monthly_rent": float(weekly_rent * 52 / 12),
        "lease_current": has_lease,
        "rent_increase_recent": rent_increase_recent,
        "previous_weekly_rent": float(weekly_rent - rng.randint(40, 120)) if rent_increase_recent else None,
        "verification_date": str(ref_date - timedelta(days=rng.randint(0, 5))),
        "data_json": json.dumps({
            "weekly_rent": weekly_rent,
            "tenure_type": "private_rental" if has_lease else "other",
            "lease_start": str(ref_date - timedelta(days=rng.randint(30, 730))),
            "rent_increase_date": str(ref_date - timedelta(days=rng.randint(5, 85))) if rent_increase_recent else None,
        }),
    })

df_housing = spark.createDataFrame(housing_records)
df_housing.write.mode("overwrite").saveAsTable(fqn("source_housing"))
print(f"source_housing: {df_housing.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evidence Documents

# COMMAND ----------

evidence_types = [
    ("lease_agreement", "Lease agreement", "Housing"),
    ("bank_statement", "Bank statement", "Financial"),
    ("payslip", "Payslip", "Employment"),
    ("birth_certificate", "Birth certificate", "Identity"),
    ("medical_report", "Medical assessment report", "Medical"),
    ("statutory_declaration", "Statutory declaration", "Legal"),
    ("movement_record", "Movement record extract", "Travel"),
    ("care_plan", "Care plan document", "Medical"),
    ("employer_letter", "Employer verification letter", "Employment"),
    ("utility_bill", "Utility bill", "Residency"),
]

evidence_docs = []
for app in applications:
    # Each application gets 3-6 evidence documents.
    n_docs = rng.randint(3, 6)
    selected = rng.sample(evidence_types, min(n_docs, len(evidence_types)))
    for j, (etype, ename, ecategory) in enumerate(selected):
        doc_id = f"DOC-{app['application_id']}-{j+1:02d}"
        submitted_date = date.fromisoformat(app["lodged_date"])
        evidence_docs.append({
            "document_id": doc_id,
            "application_id": app["application_id"],
            "applicant_id": app["applicant_id"],
            "document_type": etype,
            "document_name": f"{ename}.pdf",
            "category": ecategory,
            "submitted_date": str(submitted_date),
            "verification_status": rng.choice(["verified", "verified", "verified", "needs_context", "unverified"]),
            "summary": f"Synthetic {ename.lower()} for applicant {app['applicant_id']}.",
        })

df_evidence = spark.createDataFrame(evidence_docs)
df_evidence.write.mode("overwrite").saveAsTable(fqn("evidence_documents"))
print(f"evidence_documents: {df_evidence.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Movement Records (for residency checks)

# COMMAND ----------

movement_records = []
for a in applicants:
    # ~30% of applicants have an absence recorded.
    if rng.random() < 0.3:
        absence_days = rng.randint(7, 65)
        departure = ref_date - timedelta(days=rng.randint(60, 200))
        arrival = departure + timedelta(days=absence_days)
        movement_records.append({
            "applicant_id": a["applicant_id"],
            "source_system": "movement_records",
            "departure_date": str(departure),
            "return_date": str(arrival),
            "absence_days": absence_days,
            "destination": rng.choice(["New Zealand", "United Kingdom", "Indonesia", "India", "Philippines", "Singapore"]),
            "declared_reason": rng.choice(["family_care", "holiday", "family_care", "medical", "family_care"]),
        })

df_movements = spark.createDataFrame(movement_records) if movement_records else spark.createDataFrame([], StructType([
    StructField("applicant_id", StringType()),
    StructField("source_system", StringType()),
    StructField("departure_date", StringType()),
    StructField("return_date", StringType()),
    StructField("absence_days", IntegerType()),
    StructField("destination", StringType()),
    StructField("declared_reason", StringType()),
]))
df_movements.write.mode("overwrite").saveAsTable(fqn("source_movements"))
print(f"source_movements: {df_movements.count()} rows")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Summary

# COMMAND ----------

tables = [
    "programs", "eligibility_criteria", "policy_documents",
    "applicants", "applications", "evidence_documents",
    "source_identity", "source_household", "source_employment",
    "source_housing", "source_movements",
]

for t in tables:
    count = spark.table(fqn(t)).count()
    print(f"  {fqn(t)}: {count} rows")

print("\nSynthetic data generation complete.")
