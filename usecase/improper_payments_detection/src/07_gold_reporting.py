# Databricks notebook source
# Step 7: reporting tables and gold comments.
#
# gold_signal_eval      precision of each primary signal against synthetic ground truth
# gold_outcome_history  synthetic triage history for cases closed in the prior six months
# gold_pipeline_summary one row describing this run
# Comments state that the data is synthetic and that scores are indicators, not findings.

# COMMAND ----------

import datetime as dt
import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

import mlflow  # noqa: E402
from mlflow.tracking import MlflowClient  # noqa: E402

import reporting  # noqa: E402
from common import as_of_date, fq, get_params, sql_literal, write_table  # noqa: E402

params = get_params({"catalog": "", "schema": "", "seed": "42", "as_of": ""}, dbutils)
CATALOG, SCHEMA = params["catalog"], params["schema"]
SEED = int(params["seed"])
AS_OF = as_of_date(params["as_of"])
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731
MODEL_NAME = t("improper_payment_risk")

# COMMAND ----------

cases = spark.table(t("gold_case")).toPandas()
case_payments = spark.table(t("gold_case_payment")).toPandas()
truth = spark.table(t("bronze_ground_truth")).toPandas()
payments = spark.table(t("bronze_payment")).toPandas()

signal = reporting.signal_eval(case_payments, cases, truth)
print(signal.to_string(index=False))
write_table(spark, signal, t("gold_signal_eval"),
            "Precision of each primary signal against SYNTHETIC ground truth. A case is true when any of its flagged payments is injected as improper. Indicates how the rules behave on seeded data; it says nothing about real-world performance.")

history = reporting.outcome_history(truth, payments, AS_OF, SEED)
write_table(spark, history, t("gold_outcome_history"),
            "SYNTHETIC triage history (prior six months), derived from ground truth with deliberate noise. Not a record of real investigations. Used to show how precision is reported.")

# COMMAND ----------

mlflow.set_registry_uri("databricks-uc")
champion = MlflowClient().get_model_version_by_alias(MODEL_NAME, "champion")

counts = {name: spark.table(t(name)).count() for name in
          ("bronze_supplier_master", "bronze_business_registry", "bronze_claimant", "bronze_claim", "bronze_payment")}
summary = {
    "scored_ts": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None),
    "model_name": MODEL_NAME,
    "model_version": f"v{champion.version}",
    "source_records": int(sum(counts.values())),
    "entities_resolved": int(spark.table(t("silver_entity")).count()),
    "payments_scored": int(spark.table(t("gold_payment_features")).count()),
    "cases_open": int(len(cases)),
}
import pandas as pd  # noqa: E402

write_table(spark, pd.DataFrame([summary]), t("gold_pipeline_summary"),
            "One row per pipeline run. Counts of synthetic source records, resolved entities, scored payments and open cases.")

# COMMAND ----------

# Column comments on the gold contract. Kept here so every gold table is documented in one place.
GOLD_COLUMN_COMMENTS = {
    "gold_case": {
        "case_id": "Stable case identifier (IP-nnnn), same for the same seed and entity",
        "risk_score": "0-100 case score: highest model score among flagged payments, rule floor applied. Indicator, not finding.",
        "risk_band": "high (>= 80) or medium (>= case_threshold)",
        "primary_signal": "Pattern code of the rule that fires on the most flagged payments; model_only when none fires",
    },
    "gold_case_factor": {
        "source": "rule = a named pattern rule fired; model = SHAP-ranked profile feature",
        "contribution": "Mean SHAP contribution to the payment score across flagged payments (rule-only fallback: fraction firing)",
    },
    "gold_signal_eval": {
        "precision": "Share of cases with this primary signal that contain an improper flagged payment (synthetic)",
    },
    "gold_outcome_history": {
        "outcome": "SYNTHETIC decision: escalated or cleared",
    },
}
for table, columns in GOLD_COLUMN_COMMENTS.items():
    for column, comment in columns.items():
        spark.sql(f"ALTER TABLE {t(table)} ALTER COLUMN {column} COMMENT {sql_literal(comment)}")
print("gold comments applied")
