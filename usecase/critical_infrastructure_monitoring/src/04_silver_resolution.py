# Databricks notebook source
# Step 4 of the critical infrastructure monitoring pipeline: silver identity
# resolution.
#
# Raw sighting plates carry realistic read errors. Resolution is a two-stage
# candidate matcher over the asset registry:
#   A. exact match on the raw plate (highest confidence)
#   B. canonical match - collapse each OCR confusion class (0/O/Q/D, 8/B,
#      1/5/I, 2/Z, 6/G) to one representative, join on the canonical key, then
#      keep the registry candidate with the smallest edit distance (ties broken
#      deterministically by asset id)
#   C. fuzzy fallback - block candidates on the first plate character and
#      accept an edit distance of at most max_levenshtein
# Events that survive all three stages are quarantined, not dropped: a
# regulator keeps its unresolved evidence.
#
# The table is rebuilt from bronze each run (bounded window, deduplicated on
# the deterministic sighting id), so re-landed batches and late stragglers
# are absorbed idempotently.

# COMMAND ----------

import sys

from pyspark.sql import functions as F, types as T
from pyspark.sql.window import Window

import os

# The shared model contract (common.py) lives in this use case's src/ folder.
# The job passes src_dir=${workspace.file_path} (a file path, which is
# normalised to its folder); interactive runs probe well-known locations.
dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir")
_candidates = [_src]
if _src.endswith(".py"):
    _candidates.append(os.path.dirname(_src))
if _src.endswith(".yml"):
    _candidates.append(os.path.join(os.path.dirname(_src), "..", "src"))
_candidates += ["src", "."]
_src_dir = next(
    (c for c in _candidates if c and os.path.isfile(os.path.join(c, "common.py"))),
    None,
)
if _src_dir is None:
    raise FileNotFoundError(
        "common.py not found - pass src_dir pointing at the use case's src folder"
    )
sys.path.insert(0, _src_dir)

from common import REST_WINDOW_END_HOUR, canonical_plate_expr, get_params

params = get_params(
    {
        "catalog": "",
        "schema": "",
        "max_levenshtein": 1,
    },
    dbutils,
)
if not params["catalog"] or not params["schema"]:
    raise ValueError("catalog and schema parameters are required")

CATALOG = params["catalog"]
SCHEMA = params["schema"]
MAX_LEVENSHTEIN = int(params["max_levenshtein"])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Inputs

# COMMAND ----------

raw_events = (
    spark.table(f"{CATALOG}.{SCHEMA}.bronze_sightings")
    .dropDuplicates(["sighting_id"])
    .select("sighting_id", "event_ts_epoch_ms", "hour_of_day", "sighted_plate_raw",
            "site_id", "road_name", "locality", "state", "latitude", "longitude",
            "heading", "source_type", "speed_kph", "axle_count_est", "mass_estimate_kg")
)

registry = (
    spark.table(f"{CATALOG}.{SCHEMA}.dim_asset")
    .select("asset_id", "registration_plate", "operator_id",
            "registered_mass_kg", "risk_cohort")
    .withColumn("canon_plate", F.expr(canonical_plate_expr("registration_plate")))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Stage A - exact match

# COMMAND ----------

exact = (
    raw_events
    .join(
        registry.select(
            F.col("asset_id").alias("exact_asset_id"),
            F.col("registration_plate").alias("exact_plate"),
        ),
        F.col("sighted_plate_raw") == F.col("exact_plate"),
        "inner",
    )
    .select("sighting_id", F.col("exact_asset_id").alias("asset_id"),
            F.lit("exact").alias("resolution_method"),
            F.lit("high").alias("resolution_confidence"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Stage B - canonical candidates
# MAGIC The canonical key pulls confusable plates into one candidate set; within
# MAGIC the set the smallest edit distance wins, which keeps sibling plates
# MAGIC (e.g. AA00ND vs AA00NQ) from resolving ambiguously.

# COMMAND ----------

after_exact = raw_events.join(exact.select("sighting_id"), "sighting_id", "left_anti")

canonical_matches = (
    after_exact
    .withColumn("canon_raw", F.expr(canonical_plate_expr("sighted_plate_raw")))
    .join(
        registry.select(
            F.col("asset_id").alias("canon_asset_id"),
            F.col("registration_plate").alias("canon_reg_plate"),
            "canon_plate",
        ),
        F.col("canon_raw") == F.col("canon_plate"),
        "inner",
    )
    .withColumn("edit_distance", F.levenshtein("sighted_plate_raw", "canon_reg_plate"))
)

best_window = Window.partitionBy("sighting_id").orderBy(
    F.col("edit_distance").asc(), F.col("canon_asset_id").asc()
)
canonical = (
    canonical_matches
    .withColumn("rank", F.row_number().over(best_window))
    .filter(F.col("rank") == 1)
    .filter(F.col("edit_distance") <= MAX_LEVENSHTEIN)
    .select("sighting_id", F.col("canon_asset_id").alias("asset_id"),
            F.lit("canonical").alias("resolution_method"),
            F.lit("medium").alias("resolution_confidence"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Stage C - fuzzy fallback
# MAGIC Blocking on the first character keeps the candidate join from becoming a
# MAGIC cross product; it recovers single substitutions in the first position
# MAGIC that canonicalisation cannot.

# COMMAND ----------

after_canonical = after_exact.join(canonical.select("sighting_id"), "sighting_id", "left_anti")

fuzzy_candidates = (
    after_canonical
    .withColumn("first_char", F.expr("substring(sighted_plate_raw, 1, 1)"))
    .join(
        registry
        .withColumn("first_char", F.expr("substring(registration_plate, 1, 1)"))
        .select(F.col("asset_id").alias("fuzzy_asset_id"),
                F.col("registration_plate").alias("fuzzy_plate"), "first_char"),
        "first_char",
        "inner",
    )
    .withColumn("edit_distance", F.levenshtein("sighted_plate_raw", "fuzzy_plate"))
    .filter(F.col("edit_distance") <= MAX_LEVENSHTEIN)
)

fuzzy_window = Window.partitionBy("sighting_id").orderBy(
    F.col("edit_distance").asc(), F.col("fuzzy_asset_id").asc()
)
fuzzy = (
    fuzzy_candidates
    .withColumn("rank", F.row_number().over(fuzzy_window))
    .filter(F.col("rank") == 1)
    .select("sighting_id", F.col("fuzzy_asset_id").alias("asset_id"),
            F.lit("fuzzy").alias("resolution_method"),
            F.lit("medium").alias("resolution_confidence"))
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Conformed silver table

# COMMAND ----------

resolution_map = exact.unionByName(canonical).unionByName(fuzzy)

silver = (
    raw_events
    .join(resolution_map, "sighting_id", "left")
    .join(
        registry.select(F.col("asset_id").alias("reg_asset_id"),
                        "registration_plate", "operator_id",
                        "registered_mass_kg", "risk_cohort"),
        F.col("asset_id") == F.col("reg_asset_id"),
        "left",
    )
    .join(
        spark.table(f"{CATALOG}.{SCHEMA}.dim_operator")
            .select(F.col("operator_id").alias("op_operator_id"), "operator_name"),
        F.col("operator_id") == F.col("op_operator_id"),
        "left",
    )
    .withColumn("event_ts", F.expr("timestamp_millis(event_ts_epoch_ms)"))
    .withColumn("is_night", F.expr("hour_of_day >= 20 OR hour_of_day < 6"))
    .withColumn("is_rest_window", F.expr(f"hour_of_day < {REST_WINDOW_END_HOUR}"))
    .withColumn("day_of_week", F.expr("date_format(event_ts, 'EEEE')"))
    .withColumn("mass_ratio", F.expr(
        "CASE WHEN registered_mass_kg IS NULL OR registered_mass_kg = 0 THEN NULL "
        "ELSE mass_estimate_kg / registered_mass_kg END"
    ))
    .select(
        "sighting_id", "event_ts", "event_ts_epoch_ms", "hour_of_day", "is_night",
        "is_rest_window", "day_of_week", "sighted_plate_raw",
        "resolution_method", "resolution_confidence",
        "asset_id", "registration_plate", "operator_id", "operator_name",
        "site_id", "road_name", "locality", "state", "latitude", "longitude",
        "heading", "source_type", "speed_kph", "axle_count_est",
        "mass_estimate_kg", "mass_ratio", "risk_cohort",
    )
)

silver.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.silver_sighting"
)

unresolved = (
    raw_events.join(resolution_map.select("sighting_id"), "sighting_id", "left_anti")
    .withColumn("quarantine_reason", F.lit("no_registry_match"))
)
unresolved.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    f"{CATALOG}.{SCHEMA}.silver_sighting_quarantine"
)

# COMMAND ----------

total = raw_events.count()
resolved = resolution_map.count()
print(f"silver_sighting: {resolved}/{total} events resolved "
      f"({resolved / total:.1%}) - the identity-resolution KPI on the operations dashboard")
resolution_map.groupBy("resolution_method").count().orderBy(F.desc("count")).show()
print(f"quarantined: {unresolved.count()} events (kept, not dropped)")
