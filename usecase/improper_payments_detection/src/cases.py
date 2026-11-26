"""Case assembly: flagged payments grouped into investigator cases (pandas + graph, no Spark).

A case is one resolved supplier entity, or one claimant cluster, with at least one flagged payment
whose case score reaches case_threshold. The case carries:
  * a primary signal - the rule that fires on the most flagged payments (precedence breaks ties),
    or model_only when no rule fires
  * factors          - up to five contributing factors, ranked by SHAP contribution summed per
                       factor, with rule factors taking their wording from common.PATTERNS
  * a case graph     - a bounded neighbourhood (<= 8 nodes, one subject) from silver_graph_*
  * the payments     - the most recent flagged payments and a few unflagged ones for context

Scores are indicators that a payment is worth an investigator's time. They are never findings.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

import graph as gr
from common import (
    FLAG_SCORE, MODEL_FACTOR_FALLBACK, MODEL_FACTORS, PATTERNS, SIGNAL_PRECEDENCE,
    opened_offset_days, pattern_detail, risk_band, stable_case_ids,
)
from features import RULE_CODES, RULE_COLUMNS

MAX_FACTORS = 5
MAX_GRAPH_NODES = 8
MAX_FLAGGED_ROWS = 25
MAX_UNFLAGGED_ROWS = 5


def short_label(text: str, limit: int = 16) -> str:
    """Whole words up to `limit` characters: 'North Harbour Supplies' -> 'North Harbour'."""
    words, out = str(text or "").split(), ""
    for w in words:
        candidate = f"{out} {w}".strip()
        if len(candidate) > limit:
            break
        out = candidate
    return out or str(text or "")[:limit]


def officer_label(officer_id: str) -> str:
    """'OFF-0029' -> 'Officer 029' (the label the investigator sees)."""
    return f"Officer {str(officer_id)[-3:]}"


def _primary_signal(rule_counts: pd.Series) -> str:
    best = int(rule_counts.max())
    if best == 0:
        return "model_only"
    tied = [c for c in RULE_CODES if int(rule_counts[f"rule_{c}"]) == best]
    return min(tied, key=SIGNAL_PRECEDENCE.index)


def _rule_detail(code: str, rows: pd.DataFrame) -> str:
    fired = int(rows[f"rule_{code}"].sum())
    if code == "shared_bank_account":
        return pattern_detail(code, n=max(int(rows["bank_entity_count"].max()) - 1, 1))
    if code == "new_vendor_early_invoice":
        return pattern_detail(code, days=int(rows["days_created_to_first_invoice"].max()))
    if code == "claimant_contact_reuse":
        return pattern_detail(code, n=max(int(rows["cluster_size"].max()) - 1, 1))
    if code in ("duplicate_invoice", "split_below_threshold", "cancelled_registration_paid"):
        return pattern_detail(code, n=max(fired, 1))
    return pattern_detail(code)


def _factors(case_id: str, rows: pd.DataFrame, shap: pd.DataFrame | None) -> list[dict]:
    """Ranked factor rows for one case. Rule factors need a fired rule; model factors need positive SHAP."""
    flagged = rows[rows["flagged"]]
    out: dict[tuple, dict] = {}

    for code in RULE_CODES:
        if int(flagged[f"rule_{code}"].sum()) == 0:
            continue
        if shap is not None:
            contribution = float(shap.loc[flagged.index, f"rule_{code}"].mean())
        else:
            contribution = float(flagged[f"rule_{code}"].mean())
        out[("rule", code)] = {"factor_code": code, "title": PATTERNS[code]["title"],
                               "detail": _rule_detail(code, flagged), "contribution": contribution, "source": "rule"}

    if shap is not None:
        for feature in shap.columns:
            if feature.startswith("rule_"):
                continue
            mean_contrib = float(shap.loc[flagged.index, feature].mean())
            if mean_contrib <= 0:
                continue
            code, title, detail = MODEL_FACTORS.get(feature, MODEL_FACTOR_FALLBACK)
            key = ("model", code)
            if key in out:
                out[key]["contribution"] += mean_contrib
            else:
                out[key] = {"factor_code": code, "title": title, "detail": detail,
                            "contribution": mean_contrib, "source": "model"}

    ranked = sorted(out.values(), key=lambda f: (-f["contribution"], f["factor_code"]))[:MAX_FACTORS]
    if not ranked:
        code, title, detail = MODEL_FACTOR_FALLBACK
        ranked = [{"factor_code": code, "title": title, "detail": detail, "contribution": 0.0, "source": "model"}]
    return [{"case_id": case_id, "rank": i + 1, **f} for i, f in enumerate(ranked)]


def build_cases(scored: pd.DataFrame, entities: pd.DataFrame, nodes: pd.DataFrame, edges: pd.DataFrame,
                as_of: dt.date, case_threshold: int, model_version: str, scored_ts: dt.datetime,
                shap: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Assemble every gold case table.

    scored    one row per payment: payment_id, entity_id, cluster_id, entity_kind, program, amount,
              payment_date, invoice_ref, approver_officer_id, score (int 0-100), the rule flags and
              the continuous features. Index must match `shap` when shap is given.
    entities  silver_entity rows (entity_id, entity_kind, cluster_id, display_name, abn, vendor_created)
    nodes     silver_graph_node rows (node_id, kind, label, sub_label)
    edges     silver_graph_edge rows (src, dst, relation, weight)
    shap      optional per-payment SHAP contributions over the model features (None = rules only)
    """
    s = scored.copy()
    s["case_key"] = np.where(s["entity_kind"].eq("claimant"), s["cluster_id"], s["entity_id"])
    s["flagged"] = s["score"] >= FLAG_SCORE
    flagged = s[s["flagged"]]

    agg = flagged.groupby("case_key").agg(
        case_score=("score", "max"), payment_count=("payment_id", "size"),
        payment_value=("amount", "sum"), entity_kind=("entity_kind", "first"),
    )
    agg = agg[agg["case_score"] >= case_threshold].sort_index()
    case_ids = stable_case_ids(list(agg.index))

    ent = entities.set_index("entity_id")
    claimant_clusters = sorted(agg.index[agg["entity_kind"].eq("claimant")])
    cluster_number = {cid: i + 1 for i, cid in enumerate(claimant_clusters)}
    anchor = entities[entities["entity_kind"].eq("claimant")].groupby("cluster_id")["entity_id"].min()
    claim_counts = s[s["program"].eq("claims")].groupby("cluster_id")["invoice_ref"].nunique()

    rule_counts = flagged.groupby("case_key")[RULE_COLUMNS].sum()
    g = gr.build_graph(
        [{"id": r.node_id, "kind": r.kind, "label": r.label, "sub_label": r.sub_label} for r in nodes.itertuples()],
        [(r.src, r.dst, r.relation, r.weight) for r in edges.itertuples()],
    )

    case_rows, factor_rows, node_rows, edge_rows, payment_rows = [], [], [], [], []
    for key, meta in agg.iterrows():
        cid = case_ids[key]
        is_claim = meta["entity_kind"] == "claimant"
        rows = s[s["case_key"] == key]
        primary = _primary_signal(rule_counts.loc[key])

        if is_claim:
            label = f"Claimant cluster {cluster_number[key]:03d}"
            sub = f"{int(claim_counts.get(key, 0))} linked claims"
            subject_entity = anchor.get(key, key)
            program, program_label, entity_kind = "claims", "Claims", "claimant_cluster"
        else:
            e = ent.loc[key]
            label = str(e["display_name"] or key)
            if e["abn"]:
                sub = f"Supplier · ABN ending {str(e['abn'])[-3:]}"
            elif pd.notna(e["vendor_created"]):
                age = (as_of - pd.Timestamp(e["vendor_created"]).date()).days
                sub = f"Supplier · created {age} days ago"
            else:
                sub = "Supplier"
            subject_entity = key
            program, program_label, entity_kind = "supplier", "Supplier payments", "supplier"

        opened = as_of - dt.timedelta(days=opened_offset_days(cid))
        case_rows.append({
            "case_id": cid, "entity_id": str(key), "entity_label": label, "entity_sub": sub,
            "entity_kind": entity_kind, "program": program, "program_label": program_label,
            "primary_signal": primary, "primary_signal_label": PATTERNS[primary]["label"],
            "risk_score": int(meta["case_score"]), "risk_band": risk_band(int(meta["case_score"]), case_threshold),
            "payment_value": round(float(meta["payment_value"]), 2), "payment_count": int(meta["payment_count"]),
            "opened_date": opened, "model_version": model_version, "scored_ts": scored_ts,
        })

        factor_rows += _factors(cid, rows, None if shap is None else shap.loc[rows.index])

        subject_node = f"ent:{subject_entity}"
        if subject_node in g.nodes:
            sub_graph = gr.case_subgraph(g, subject_node, max_nodes=MAX_GRAPH_NODES)
            for nid in sub_graph["nodes"]:
                meta_n = g.nodes[nid]
                if nid == subject_node:
                    role = "subject"
                elif sub_graph["hop"].get(nid) == 2:
                    role = "related"
                else:
                    role = "link"
                sub_label = meta_n["sub_label"]
                if role == "related" and meta_n["kind"] in gr.OFFICER_KINDS:
                    sub_label = "Shares address"
                elif role == "related" and not sub_label.lower().startswith("related"):
                    sub_label = f"Related {sub_label.lower()}"
                node_rows.append({"case_id": cid, "node_id": nid, "label": meta_n["label"][:16],
                                  "kind": meta_n["kind"], "sub_label": sub_label, "role": role})
            for src, dst, relation in sub_graph["edges"]:
                edge_rows.append({"case_id": cid, "src": src, "dst": dst, "relation": relation})

        if is_claim:
            member_rows = s[s["cluster_id"] == key]
        else:
            member_rows = s[s["entity_id"] == key]
        flagged_members = member_rows[member_rows["flagged"]].sort_values(["payment_date", "payment_id"], ascending=False)
        unflagged = member_rows[~member_rows["flagged"]].sort_values(["payment_date", "payment_id"], ascending=False)
        for _, r in pd.concat([flagged_members.head(MAX_FLAGGED_ROWS), unflagged.head(MAX_UNFLAGGED_ROWS)]).iterrows():
            payment_rows.append({
                "case_id": cid, "payment_id": r["payment_id"], "payment_date": r["payment_date"].date(),
                "amount": round(float(r["amount"]), 2), "invoice_ref": str(r["invoice_ref"]),
                "approver": officer_label(r["approver_officer_id"]), "flagged": bool(r["flagged"]),
            })

    case_df = pd.DataFrame(case_rows)
    return {
        "gold_case": case_df,
        "gold_case_factor": pd.DataFrame(factor_rows),
        "gold_case_graph_node": pd.DataFrame(node_rows),
        "gold_case_graph_edge": pd.DataFrame(edge_rows).drop_duplicates() if edge_rows else pd.DataFrame(),
        "gold_case_payment": pd.DataFrame(payment_rows),
    }
