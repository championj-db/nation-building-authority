# Databricks notebook source
# Step 3: relationship graph.
#
# Entities are joined to the attributes they share: bank accounts they are paid into, addresses
# (business, director and officer home), phone numbers, email addresses and directors. Approvals
# and assessments are edges too, so an approving officer is one hop from every supplier they paid.
# Two parties that reach the same attribute node are related; the case view (06) draws those
# two-hop links.

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
import graph  # noqa: E402
from common import fq, get_params, write_table  # noqa: E402

params = get_params({"catalog": "", "schema": ""}, dbutils)
CATALOG, SCHEMA = params["catalog"], params["schema"]
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731

# COMMAND ----------

parties = spark.table(t("silver_party_record")).toPandas().to_dict("records")
xref = spark.table(t("silver_entity_xref")).toPandas()
xref = [{"key": f"{r.source_system}:{r.source_id}", "entity_id": r.entity_id} for r in xref.itertuples()]
entities = spark.table(t("silver_entity")).toPandas().to_dict("records")

payments_pd = spark.table(t("bronze_payment")).toPandas()
claims_pd = spark.table(t("bronze_claim")).toPandas()
officers_pd = spark.table(t("bronze_officer")).toPandas()

entity_of = {x["key"].split(":", 1)[1]: x["entity_id"] for x in xref}
assessor_of_claim = dict(zip(claims_pd["claim_id"], claims_pd["assessor_officer_id"]))
payments = [
    {
        "entity_id": entity_of[r.payee_src_id],
        "bank_key": er_rules.normalise_bank(r.bank_bsb, r.bank_account_no),
        "approver_officer_id": r.approver_officer_id,
        "assessor_officer_id": assessor_of_claim.get(r.invoice_ref) if r.program == "claims" else None,
    }
    for r in payments_pd.itertuples()
]
officers = [
    {"officer_id": r.officer_id, "role": r.role,
     "home_key": er_rules.normalise_address(r.home_street, r.home_suburb, r.home_postcode)}
    for r in officers_pd.itertuples()
]

nodes, edges = graph.graph_rows(parties, xref, entities, payments, officers)
print(f"graph: {len(nodes)} nodes, {len(edges)} edges")

# COMMAND ----------

N = pd.DataFrame(nodes)[["id", "kind", "label", "sub_label"]].rename(columns={"id": "node_id"})
E = pd.DataFrame(edges, columns=["src", "dst", "relation", "weight"])

write_table(spark, N, t("silver_graph_node"),
            "Graph nodes: resolved entities and the attributes they share (bank account, address, phone, email, director, officer, assessor). Labels are short by design.")
write_table(spark, E, t("silver_graph_edge"),
            "Graph edges: entity pays into account, registered at address, shares contact or director, approved by or assessed by officer. weight counts payments.")
print("silver_graph_node and silver_graph_edge written")
