# Databricks notebook source
# Step 4: payment features and rule signals.
#
# One row per payment: entity context, payment-level features the model may use, and one rule flag
# per pattern (features.py documents the thresholds). The rule flags are what an investigator reads
# and what the precision table is reported against, so they are written here as first-class columns.

# COMMAND ----------

import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

import features  # noqa: E402
import er_rules  # noqa: E402
from common import fq, get_params, write_table  # noqa: E402

params = get_params({"catalog": "", "schema": ""}, dbutils)
CATALOG, SCHEMA = params["catalog"], params["schema"]
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731

# COMMAND ----------

payments = spark.table(t("bronze_payment")).toPandas()
payments["bank_key"] = [er_rules.normalise_bank(b, a) for b, a in zip(payments["bank_bsb"], payments["bank_account_no"])]
xref = spark.table(t("silver_entity_xref")).toPandas()
entities = spark.table(t("silver_entity")).toPandas()
officers_pd = spark.table(t("bronze_officer")).toPandas()
officers = officers_pd.assign(home_key=[er_rules.normalise_address(s, sb, pc) for s, sb, pc in
                                        zip(officers_pd["home_street"], officers_pd["home_suburb"], officers_pd["home_postcode"])])
claims = spark.table(t("bronze_claim")).toPandas()

F = features.build_payment_features(payments, xref, entities, officers, claims)
write_table(spark, F, t("gold_payment_features"),
            "Per-payment features and rule signals (synthetic). rule_* columns are 1 when a named pattern rule fires on the payment. Indicators for triage, not findings.")

print(f"payments featured: {len(F)}")
print(F[features.RULE_COLUMNS].sum().to_string())
