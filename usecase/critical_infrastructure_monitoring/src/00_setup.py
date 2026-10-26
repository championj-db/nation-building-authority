# Databricks notebook source
# Step 0 of the critical infrastructure monitoring pipeline: idempotent
# environment setup. Creates the use case's schema and landing volume so the
# rest of the pipeline can run without any prior manual provisioning.

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
VOLUME = dbutils.widgets.get("volume").strip()

if not CATALOG or not SCHEMA or not VOLUME:
    raise ValueError(
        "catalog, schema and volume parameters are required - "
        "pass the Unity Catalog location for this use case (the bundle does this "
        "via its variables)"
    )

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME}")

print(f"Schema ready: {CATALOG}.{SCHEMA}")
print(f"Landing volume ready: /Volumes/{CATALOG}/{SCHEMA}/{VOLUME}")
print("Notebook tasks receive src_dir=${workspace.file_path} so they can import "
      "the shared model contract in src/common.py.")
