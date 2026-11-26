"""Reporting tables: signal precision, model evaluation, outcome history and the precision table.

Everything here answers one question: how often do flags survive investigation? Precision is
measured two ways and both are labelled as synthetic in the table comments:
  * against ground truth, for every open case (gold_signal_eval), and
  * against recorded triage outcomes, historical and live (gold_precision).
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from common import PATTERNS, stable_case_ids

BENIGN_RULE_LOOKALIKE = {
    "benign_franchise_branch": "shared_bank_account",
    "benign_new_vendor": "new_vendor_early_invoice",
    "benign_family_address": "claimant_contact_reuse",
    "benign_cancelled_inactive": "cancelled_registration_paid",
}
REASON_CODES = {
    "escalated": ["CONFIRMED_LINK", "CONFIRMED_DUPLICATE", "CONFIRMED_SPLIT", "REFERRED_FOR_RECOVERY"],
    "cleared": ["LEGITIMATE_RELATIONSHIP", "DOCUMENTED_EXPLANATION", "NO_EVIDENCE_FOUND"],
}


def signal_eval(case_payments: pd.DataFrame, cases: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Per primary signal: open cases, how many contain at least one improper flagged payment, precision.

    A case counts as true when any of its flagged payments is ground-truth improper.
    """
    flagged = case_payments[case_payments["flagged"]].merge(truth[["payment_id", "is_improper"]], on="payment_id", how="left")
    hit = flagged.groupby("case_id")["is_improper"].max().fillna(False).astype(bool)
    frame = cases[["case_id", "primary_signal", "primary_signal_label"]].copy()
    frame["true_case"] = frame["case_id"].map(hit).fillna(False).astype(bool)
    out = (frame.groupby(["primary_signal", "primary_signal_label"])
           .agg(cases=("case_id", "size"), true_improper=("true_case", "sum"))
           .reset_index())
    out["precision"] = np.where(out["cases"] > 0, out["true_improper"] / out["cases"].clip(lower=1), 0.0)
    out["cases"] = out["cases"].astype(int)
    out["true_improper"] = out["true_improper"].astype(int)
    return out.sort_values(["cases", "primary_signal"], ascending=[False, True]).reset_index(drop=True)


def model_eval_frame(metrics: dict, model_version: str, payments_scored: int) -> pd.DataFrame:
    """Long-format model evaluation rows, held-out split unless stated otherwise."""
    rows = [{"metric": k, "value": float(v), "model_version": model_version} for k, v in metrics.items()]
    rows.append({"metric": "payments_scored", "value": float(payments_scored), "model_version": model_version})
    return pd.DataFrame(rows)


def outcome_history(truth: pd.DataFrame, payments: pd.DataFrame, as_of: dt.date, seed: int,
                    n_improper: int = 320, n_benign: int = 120) -> pd.DataFrame:
    """Synthetic triage history for cases closed in the prior six months, derived from ground truth.

    A historical case is one counterparty, one pattern and one calendar month of payments. Months
    that fall in the six months before `as_of` (and not in its last week) are candidates, so a
    long-running pattern contributes several closed cases rather than one open one. Improper cases
    are escalated with probability 0.85; benign look-alikes are escalated with probability 0.08.
    Risk band and decision time are drawn at random. This is noise-laden synthetic history, not a
    record of real investigations.
    """
    rng = np.random.default_rng(seed + 1)
    t = truth.merge(payments[["payment_id", "payment_date"]], on="payment_id")
    t["payment_date"] = pd.to_datetime(t["payment_date"])
    t["month"] = t["payment_date"].dt.to_period("M").astype(str)
    lo, hi = pd.Timestamp(as_of - dt.timedelta(days=180)), pd.Timestamp(as_of - dt.timedelta(days=7))
    groups = (t.groupby(["entity_id", "pattern_code", "month"])
              .agg(is_improper=("is_improper", "max"), last_seen=("payment_date", "max"))
              .reset_index())
    groups = groups[(groups["last_seen"] >= lo) & (groups["last_seen"] <= hi)]
    improper = groups[groups["is_improper"]]
    benign = groups[(~groups["is_improper"]) & groups["pattern_code"].str.startswith("benign_")]
    sample = pd.concat([
        improper.iloc[rng.permutation(len(improper))[:n_improper]],
        benign.iloc[rng.permutation(len(benign))[:n_benign]],
    ], ignore_index=True)

    keys = [f"{e}|{p}|{m}" for e, p, m in zip(sample["entity_id"], sample["pattern_code"], sample["month"])]
    ids = stable_case_ids(keys, prefix="IH")
    rows = []
    for (_, r), key in zip(sample.iterrows(), keys):
        is_improper = bool(r["is_improper"])
        code = r["pattern_code"] if is_improper else BENIGN_RULE_LOOKALIKE[r["pattern_code"]]
        escalate = rng.random() < (0.85 if is_improper else 0.08)
        outcome = "escalated" if escalate else "cleared"
        reason = REASON_CODES[outcome][int(rng.integers(0, len(REASON_CODES[outcome])))]
        decided = min(r["last_seen"] + pd.Timedelta(days=int(rng.integers(7, 40))), hi)
        decided = decided + pd.Timedelta(seconds=int(rng.integers(0, 86400)))
        rows.append({
            "case_id": ids[key], "primary_signal": code, "primary_signal_label": PATTERNS[code]["label"],
            "risk_band": "high" if rng.random() < 0.35 else "medium", "outcome": outcome,
            "reason_code": reason, "decided_ts": decided.to_pydatetime(),
        })
    return pd.DataFrame(rows).sort_values(["decided_ts", "case_id"]).reset_index(drop=True)


def precision_table(decisions: pd.DataFrame) -> pd.DataFrame:
    """Weekly escalated and cleared counts, and precision, by primary signal and risk band.

    decisions: primary_signal, risk_band, outcome ('escalated' | 'cleared'), decided_ts. History and
    live decisions are unioned by the caller. Rows with any other outcome are ignored.
    """
    d = decisions[decisions["outcome"].isin(["escalated", "cleared"])].copy()
    d["decided_ts"] = pd.to_datetime(d["decided_ts"])
    d["week"] = (d["decided_ts"] - pd.to_timedelta(d["decided_ts"].dt.weekday, unit="D")).dt.normalize()
    out = (d.assign(escalated=d["outcome"].eq("escalated").astype(int), cleared=d["outcome"].eq("cleared").astype(int))
           .groupby(["primary_signal", "risk_band", "week"], as_index=False)[["escalated", "cleared"]].sum())
    out["precision"] = out["escalated"] / (out["escalated"] + out["cleared"]).clip(lower=1)
    out["week"] = out["week"].dt.date
    return out.sort_values(["primary_signal", "risk_band", "week"]).reset_index(drop=True)
