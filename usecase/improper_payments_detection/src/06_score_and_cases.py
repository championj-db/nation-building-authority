# Databricks notebook source
# Step 6: batch score with the champion model and build the investigator cases.
#
# Scores are 0-100 from the model's probability. A payment that fires any rule is never scored below
# common.RULE_FLOOR_SCORE, so the model ranks within rule hits and cannot hide a known pattern.
# Payments at or above FLAG_SCORE are flagged; flagged payments are grouped per supplier entity or
# claimant cluster, and a case is opened where the case score (its highest flagged payment) reaches
# case_threshold.
#
# SHAP contributions (LightGBM pred_contrib) become the case factors; rule factors take their wording
# from common.PATTERNS. Scores are indicators that a payment is worth an investigator's time. They
# are not findings and no action is taken on them automatically.

# COMMAND ----------

# MAGIC %pip install lightgbm

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
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from mlflow.tracking import MlflowClient  # noqa: E402

import cases  # noqa: E402
import features  # noqa: E402
import reporting  # noqa: E402
from common import FLAG_SCORE, RULE_FLOOR_SCORE, as_of_date, fq, get_params, write_table  # noqa: E402

params = get_params({"catalog": "", "schema": "", "case_threshold": "55", "as_of": ""}, dbutils)
CATALOG, SCHEMA = params["catalog"], params["schema"]
CASE_THRESHOLD = int(params["case_threshold"])
AS_OF = as_of_date(params["as_of"])
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731
MODEL_NAME = t("improper_payment_risk")

# COMMAND ----------

mlflow.set_registry_uri("databricks-uc")
client = MlflowClient()
champion = client.get_model_version_by_alias(MODEL_NAME, "champion")
run = client.get_run(champion.run_id)
flavor = run.data.params["flavor"]
model_version = f"v{champion.version}"
model_uri = f"models:/{MODEL_NAME}@champion"
X = features.MODEL_FEATURES

F = spark.table(t("gold_payment_features")).toPandas().reset_index(drop=True)
if flavor == "lightgbm":
    booster = mlflow.lightgbm.load_model(model_uri)
    prob = booster.predict(F[X])
    shap = pd.DataFrame(booster.predict(F[X], pred_contrib=True)[:, :-1], columns=X, index=F.index)
else:
    model = mlflow.sklearn.load_model(model_uri)
    prob = model.predict_proba(F[X])[:, 1]
    shap = None

# Training up-weighted improper payments by positive_weight (see 05_train_model.py), which inflates
# predicted probabilities. Undo that prior shift so a score reads as a calibrated probability:
# p / (p + (1 - p) * w). Without it nearly every case saturates near 100 and the bands mean nothing.
w_pos = float(run.data.params.get("positive_weight", 1.0))
prob = prob / (prob + (1.0 - prob) * w_pos)
score = np.round(100 * prob).astype(int)
any_rule = F[features.RULE_COLUMNS].sum(axis=1).to_numpy() > 0
F["score"] = np.where(any_rule, np.maximum(score, RULE_FLOOR_SCORE), score).astype(int)
F["flagged"] = F["score"] >= FLAG_SCORE
print(f"model {model_version} ({flavor}); payments {len(F)}; flagged {int(F['flagged'].sum())}; rule floor applied to {int(any_rule.sum())}")

# COMMAND ----------

scored_ts = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
entities = spark.table(t("silver_entity")).toPandas()
nodes = spark.table(t("silver_graph_node")).toPandas()
edges = spark.table(t("silver_graph_edge")).toPandas()

tables = cases.build_cases(F, entities, nodes, edges, AS_OF, CASE_THRESHOLD, model_version, scored_ts, shap=shap)
for name, comment in {
    "gold_case": "Open investigator cases: one per supplier entity or claimant cluster with a flagged payment at or above case_threshold. Synthetic indicators for triage, not findings.",
    "gold_case_factor": "Ranked factors behind each case (top five). source=rule when a named pattern rule fired; source=model for SHAP-ranked profile features.",
    "gold_case_graph_node": "Bounded relationship neighbourhood per case (at most eight nodes, one subject).",
    "gold_case_graph_edge": "Edges among the nodes of each case graph.",
    "gold_case_payment": "Flagged payments and a few unflagged comparators per case. approver is a pseudonymous officer label.",
}.items():
    print(f"{name}: {write_table(spark, tables[name], t(name), comment)} rows")

write_table(spark, F[["payment_id", "score", "flagged"]].assign(model_version=model_version),
            t("silver_payment_score"), "Score per payment from the champion model, with the rule floor applied. Scores are triage indicators only.")

metrics = {k: v for k, v in run.data.metrics.items()}
write_table(spark, reporting.model_eval_frame(metrics, model_version, len(F)), t("gold_model_eval"),
            "Model evaluation on a time-based holdout (synthetic ground truth). Precision is among the model's own flags, before the rule floor.")
dbutils.jobs.taskValues.set(key="cases_open", value=str(len(tables["gold_case"])))
dbutils.jobs.taskValues.set(key="scored_ts", value=scored_ts.isoformat())
