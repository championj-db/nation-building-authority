# Databricks notebook source
# Step 5: train the payment risk model against ground truth, track it, and register it to Unity Catalog.
#
# Inputs are payment features only (features.MODEL_FEATURES: payment-level continuous features and
# the rule flags). Counterparty-level constants are kept out on purpose; see features.py.
#
# Split: time-based. Payments before the 75th percentile date train the model; later payments are
# held out for evaluation. Improper payments are rare (about 2%), so positives are up-weighted by
# the negative:positive ratio, capped at 10, so that rare patterns are learned at all.
#
# Registration: UC model improper_payment_risk, with alias 'champion'. The alias only moves when
# the new model's held-out PR-AUC is at least the current champion's.

# COMMAND ----------

# MAGIC %pip install lightgbm

# COMMAND ----------

import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import average_precision_score  # noqa: E402

import features  # noqa: E402
from common import FLAG_SCORE, fq, get_params  # noqa: E402

params = get_params({"catalog": "", "schema": "", "seed": "42", "positive_weight_cap": "10"}, dbutils)
CATALOG, SCHEMA = params["catalog"], params["schema"]
SEED = int(params["seed"])
W_CAP = float(params["positive_weight_cap"])
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731
MODEL_NAME = t("improper_payment_risk")

# COMMAND ----------

G = (spark.table(t("gold_payment_features")).toPandas()
     .merge(spark.table(t("bronze_ground_truth")).toPandas()[["payment_id", "is_improper"]], on="payment_id"))
G["y"] = G["is_improper"].astype(int)
G["payment_date"] = pd.to_datetime(G["payment_date"])
cutoff = G["payment_date"].quantile(0.75)
train, test = G[G["payment_date"] < cutoff], G[G["payment_date"] >= cutoff]
X = features.MODEL_FEATURES

neg, pos = int((train["y"] == 0).sum()), int((train["y"] == 1).sum())
w_pos = min(neg / max(pos, 1), W_CAP)
weights = np.where(train["y"].to_numpy() == 1, w_pos, 1.0)
print(f"train {len(train)} (improper {pos}), holdout {len(test)} (improper {int(test['y'].sum())}), cutoff {cutoff.date()}, positive weight {w_pos:.2f}")

# COMMAND ----------

try:
    import lightgbm as lgb

    flavor = "lightgbm"
    booster = lgb.train(
        {"objective": "binary", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 20,
         "feature_fraction": 0.9, "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0,
         "seed": SEED, "verbosity": -1},
        lgb.Dataset(train[X], label=train["y"], weight=weights, feature_name=X),
        num_boost_round=200,
    )
    p_test = booster.predict(test[X])
    model_obj = booster
except ImportError as exc:
    from sklearn.ensemble import HistGradientBoostingClassifier

    print(f"LightGBM unavailable ({exc}); using scikit-learn HistGradientBoosting. Per-payment SHAP is not available in this run.")
    flavor = "sklearn"
    model_obj = HistGradientBoostingClassifier(max_depth=4, min_samples_leaf=20, learning_rate=0.05,
                                               max_iter=200, l2_regularization=1.0, random_state=SEED)
    model_obj.fit(train[X], train["y"], sample_weight=weights)
    p_test = model_obj.predict_proba(test[X])[:, 1]

# Report threshold metrics on the prior-corrected probability, the same score 06 publishes.
p_test = p_test / (p_test + (1.0 - p_test) * w_pos)
y_test = test["y"].to_numpy()
order = np.argsort(-p_test)
flag = p_test >= FLAG_SCORE / 100
metrics = {
    "pr_auc": float(average_precision_score(y_test, p_test)),
    "precision_at_50": float(y_test[order][:50].mean()),
    "precision_at_100": float(y_test[order][:100].mean()),
    "recall_at_threshold": float((flag & (y_test == 1)).sum() / max(y_test.sum(), 1)),
    "precision_at_threshold": float(y_test[flag].mean()) if flag.any() else 0.0,
    "holdout_improper": float(y_test.sum()),
}
print({k: round(v, 3) for k, v in metrics.items()})

# COMMAND ----------

import mlflow
from mlflow.tracking import MlflowClient

mlflow.set_registry_uri("databricks-uc")
with mlflow.start_run(run_name="improper_payment_risk") as run:
    mlflow.log_params({
        "flavor": flavor, "features": ",".join(X), "seed": SEED, "cutoff_date": str(cutoff.date()),
        "positive_weight": round(w_pos, 3), "train_rows": len(train), "holdout_rows": len(test),
    })
    mlflow.log_metrics(metrics)
    # Unity Catalog requires a signature with both inputs and outputs.
    from mlflow.models import infer_signature
    example = test[X].head(20)
    signature = infer_signature(example, np.asarray(p_test[: len(example)]))
    if flavor == "lightgbm":
        info = mlflow.lightgbm.log_model(model_obj, artifact_path="model", signature=signature, input_example=example)
    else:
        info = mlflow.sklearn.log_model(model_obj, artifact_path="model", signature=signature, input_example=example)
    run_id = run.info.run_id

client = MlflowClient()
version = mlflow.register_model(info.model_uri, MODEL_NAME)
try:
    champion = client.get_model_version_by_alias(MODEL_NAME, "champion")
    champion_auc = client.get_run(champion.run_id).data.metrics.get("pr_auc", -1.0)
except Exception:  # no champion yet
    champion_auc = -1.0

if metrics["pr_auc"] >= champion_auc:
    client.set_registered_model_alias(MODEL_NAME, "champion", version.version)
    print(f"champion -> version {version.version} (pr_auc {metrics['pr_auc']:.3f} vs {champion_auc:.3f})")
else:
    print(f"kept existing champion (pr_auc {champion_auc:.3f} beats new {metrics['pr_auc']:.3f}); version {version.version} registered")

dbutils.jobs.taskValues.set(key="model_version", value=str(version.version))
dbutils.jobs.taskValues.set(key="mlflow_run_id", value=run_id)
