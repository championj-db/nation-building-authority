# Databricks notebook source
# Step 0 of the improper payments detection pipeline: idempotent environment setup.
#
# Creates the schema, the landing volume and the provenance table. Everything else is created by
# the steps that own it. Safe to re-run: nothing here drops or overwrites data.

# COMMAND ----------

import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import PROVENANCE_SCHEMA, fq, get_params, volume_dir  # noqa: E402

params = get_params({"catalog": "", "schema": "", "volume": "landing"}, dbutils)
CATALOG, SCHEMA, VOLUME = params["catalog"], params["schema"], params["volume"]
if not CATALOG or not SCHEMA or not VOLUME:
    raise ValueError("catalog, schema and volume parameters are required")

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} COMMENT 'Improper payments detection: synthetic sources, entity resolution, relationship graph, risk scores and investigator cases'")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME} COMMENT 'Landing area for the synthetic source extracts'")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {fq(CATALOG, SCHEMA, 'pipeline_provenance')} ({PROVENANCE_SCHEMA})
COMMENT 'Where every input came from. Everything here is synthetic and seeded.'
""")

print(f"Schema ready: {CATALOG}.{SCHEMA}")
print(f"Volume ready: {volume_dir(CATALOG, SCHEMA, VOLUME)}")
