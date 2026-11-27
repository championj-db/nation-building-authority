# Databricks notebook source
# MAGIC %md
# MAGIC # 00 Setup
# MAGIC
# MAGIC Creates the schema and the document volume, and (with `reset=true`) clears the synthetic
# MAGIC inbox so the corpus can be regenerated from its seed. Safe to re-run: without `reset`, nothing
# MAGIC here drops or overwrites data.
# MAGIC
# MAGIC The volume holds supplier documents. Treat it, and everything parsed from it, at the highest
# MAGIC classification of anything in the corpus (PSPF), not the average.

# COMMAND ----------

import sys, os  # noqa: E401

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_found = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _found is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _found)

from common import fq, get_params, volume_dir  # noqa: E402

p = get_params({"catalog": "", "schema": "", "volume": "documents", "reset": "false"}, dbutils)
CATALOG, SCHEMA, VOLUME = p["catalog"], p["schema"], p["volume"]
RESET = str(p["reset"]).lower() == "true"
if not CATALOG or not SCHEMA or not VOLUME:
    raise ValueError("catalog, schema and volume parameters are required")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{CATALOG}`.`{SCHEMA}` COMMENT 'Intelligent document processing: supplier inbox, parsed documents, extracted fields, correctly-rendered checks and the AP review queue. Contracts from public AusTender data (pseudonymised); every document is synthetic.'")
spark.sql(f"CREATE VOLUME IF NOT EXISTS `{CATALOG}`.`{SCHEMA}`.`{VOLUME}` COMMENT 'Supplier documents as received (inbox/), and page images rendered by ai_parse_document (pages/). Synthetic.'")

if RESET:
    import shutil

    for sub in ("inbox", "pages"):
        path = volume_dir(CATALOG, SCHEMA, VOLUME, sub)
        if os.path.isdir(path):
            shutil.rmtree(path)
            print(f"cleared {path}")
    for table in ("bronze_inbox_manifest", "bronze_ground_truth", "bronze_processing_history", "ref_contracts",
                  "ref_suppliers", "ref_purchase_orders", "ref_goods_receipts", "corpus_control"):
        spark.sql(f"DROP TABLE IF EXISTS {fq(CATALOG, SCHEMA, table)}")
    print("reset: corpus tables dropped. Run the processing pipeline with a full refresh next.")

for sub in ("inbox", "pages"):
    os.makedirs(volume_dir(CATALOG, SCHEMA, VOLUME, sub), exist_ok=True)

print(f"Schema ready: {CATALOG}.{SCHEMA}")
print(f"Volume ready: {volume_dir(CATALOG, SCHEMA, VOLUME)}")
