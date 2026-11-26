# Databricks notebook source
# Step 2: entity resolution across the disconnected sources.
#
# Party records from the supplier master, the business registry and the claimant system are
# normalised (er_rules.party_records), scored for match probability, and clustered with union-find
# into entities. Scoring uses Splink 4 (Fellegi-Sunter) when it can be imported and falls back to
# the rule-based scorer in er_rules otherwise. Clustering, stable ids and the xref are identical
# either way, so downstream steps do not know which scorer ran.
#
# Phone, email and bank account are not used to link records. They are the signals the
# investigation looks at (shared contacts, shared accounts), so they are kept for the graph (03)
# and claimant clusters are formed from them there, not here.

# COMMAND ----------

# MAGIC %pip install "splink>=4,<5"

# COMMAND ----------

import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

import pandas as pd  # noqa: E402

import er_rules  # noqa: E402
from common import fq, get_params, write_table  # noqa: E402

params = get_params({"catalog": "", "schema": "", "match_threshold": "0.85", "splink_threshold": "0.5"}, dbutils)
CATALOG, SCHEMA = params["catalog"], params["schema"]
MATCH_T = float(params["match_threshold"])
SPLINK_T = float(params["splink_threshold"])
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731

# COMMAND ----------

def read(name: str) -> list[dict]:
    return spark.table(t(name)).toPandas().to_dict("records")


parties = er_rules.party_records(
    read("bronze_supplier_master"), read("bronze_business_registry"), read("bronze_claimant"),
)
print(f"party records: {len(parties)}")

# COMMAND ----------

try:
    from er_splink import score_with_splink

    links, diagnostics = score_with_splink(parties, threshold=SPLINK_T)
    method = "splink"
    print(f"Splink scored the candidate pairs: {diagnostics}")
except ImportError as exc:
    print(f"Splink unavailable ({exc}); falling back to rule-based scoring")
    links = er_rules.score_pairs(parties, er_rules.candidate_pairs(parties))
    method = "er_rules"

xref = er_rules.assign_entities([p["key"] for p in parties], links, threshold=MATCH_T)
entities, xref_rows = er_rules.build_entities(parties, xref)
E = pd.DataFrame(entities)
X = pd.DataFrame(xref_rows)
print(f"scorer: {method}; entities: {len(E)}; claimant clusters: {E.loc[E.entity_kind == 'claimant', 'cluster_id'].nunique()}")

# COMMAND ----------

P = pd.DataFrame(parties)
write_table(spark, P, t("silver_party_record"),
            "Normalised party records from the three source systems, one row per source record. Keys are normalised ABN, name, address, phone, email and bank.")
write_table(spark, X, t("silver_entity_xref"),
            f"Source record to resolved entity. match_probability is the strongest accepted link touching the record (1.0 when unlinked). Scorer: {method}.")
write_table(spark, E, t("silver_entity"),
            "One row per resolved entity (supplier or claimant). Claimant clusters are the groups sharing a phone, email or account; suppliers are their own cluster.")
print("silver_party_record, silver_entity_xref and silver_entity written")
