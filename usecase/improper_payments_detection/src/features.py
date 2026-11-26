"""Payment-level features and rule signals (pandas, no Spark).

Each payment gets two kinds of input to the model:
  * continuous features - amount, timing, the counterparty's history, approver concentration
  * rule flags          - one per pattern code, 1 when the rule fires on that payment

The rule flags are deliberately explicit. They are what an investigator can read ("this account
is paid by two separately registered suppliers"), they name the factor a case is built on, and
they are the signals the precision table is reported against. The model learns how to weight
them alongside the continuous features; it does not replace them.

Thresholds (all in one place so the write-up can quote them):
  split band        $9,000 to under $10,000, two or more such payments within 14 days
  near-duplicate    same counterparty, amount within 1%, dated within 7 days, and invoice digits
                    equal or last four digits equal
  new vendor        supplier record created 0 to 20 days before its first invoice, payment within
                    60 days of that first invoice
  contact reuse     claimant cluster of three or more records sharing a phone, email or account
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RULE_CODES = [
    "shared_bank_account",
    "new_vendor_early_invoice",
    "duplicate_invoice",
    "split_below_threshold",
    "officer_supplier_link",
    "claimant_contact_reuse",
    "claimant_assessor_address",
    "cancelled_registration_paid",
]
RULE_COLUMNS = [f"rule_{c}" for c in RULE_CODES]
# Payment-level continuous features the model may use. Counterparty-level constants (vendor age,
# cluster size, approver share, account reuse) are deliberately NOT model inputs: with a few
# hundred injected counterparties the model would learn each one's identity rather than the
# pattern, and the in-sample scores would look far better than the held-out ones. They still drive
# the case factors and the rule flags, which are computed from them.
# Round-sum amounts, weekday and programme carry no signal in these sources, so they stay out of
# the model; a factor naming them would be noise.
CONTINUOUS_FEATURES = ["amount_log", "payments_30d", "amount_vs_entity_median"]
MODEL_FEATURES = CONTINUOUS_FEATURES + RULE_COLUMNS
ENTITY_CONTEXT_FEATURES = [
    "vendor_age_days", "days_created_to_first_invoice", "days_since_first_invoice", "entity_tenure_days",
    "bank_entity_count", "approver_share", "cluster_size",
]

SPLIT_LOW, SPLIT_HIGH, SPLIT_WINDOW_DAYS = 9000.0, 10000.0, 14
DUPLICATE_WINDOW_DAYS, DUPLICATE_AMOUNT_TOLERANCE = 7, 0.01
NEW_VENDOR_MAX_GAP_DAYS, NEW_VENDOR_EARLY_DAYS = 20, 60
CONTACT_REUSE_MIN_CLUSTER = 3
RECENT_WINDOW_DAYS = 30


def _near_duplicate_flags(amounts: np.ndarray, days: np.ndarray, digits: list[str]) -> np.ndarray:
    """True for each payment that has an earlier near-identical payment to the same counterparty."""
    n = len(amounts)
    flags = np.zeros(n, dtype=bool)
    for i in range(1, n):
        for j in range(i):
            same_amount = abs(amounts[i] - amounts[j]) <= DUPLICATE_AMOUNT_TOLERANCE * max(amounts[j], 1.0)
            near_date = abs(days[i] - days[j]) <= DUPLICATE_WINDOW_DAYS
            same_ref = digits[i] == digits[j] or (len(digits[i]) >= 4 and digits[i][-4:] == digits[j][-4:])
            if same_amount and near_date and same_ref:
                flags[i] = True
                break
    return flags


def _count_prior_within(days: np.ndarray, window: int) -> np.ndarray:
    """For each element, how many other elements of the same array fall in [d - window, d)."""
    ordered = np.sort(days)
    return np.searchsorted(ordered, days, side="left") - np.searchsorted(ordered, days - window, side="left")


def build_payment_features(payments: pd.DataFrame, xref: pd.DataFrame, entities: pd.DataFrame,
                           officers: pd.DataFrame, claims: pd.DataFrame) -> pd.DataFrame:
    """One row per payment with entity context, continuous features and rule flags.

    payments  payment_id, payee_src_id, program, amount, payment_date, invoice_ref,
              approver_officer_id, bank_key
    xref      source_id, entity_id                  (payee source record -> entity)
    entities  entity_id, entity_kind, cluster_id, vendor_created, registry_status, status_date,
              address_key, director_address_key, display_name, abn
    officers  officer_id, home_key                  (home address key)
    claims    claim_id, assessor_officer_id
    """
    p = payments.copy()
    p["payment_date"] = pd.to_datetime(p["payment_date"])
    p["amount"] = p["amount"].astype(float)
    p["entity_id"] = p["payee_src_id"].map(dict(zip(xref["source_id"], xref["entity_id"])))
    if p["entity_id"].isna().any():
        raise ValueError(f"{int(p['entity_id'].isna().sum())} payments have no resolved entity")

    ent = entities.set_index("entity_id")
    p["entity_kind"] = p["entity_id"].map(ent["entity_kind"])
    p["cluster_id"] = p["entity_id"].map(ent["cluster_id"])
    p["vendor_created"] = pd.to_datetime(p["entity_id"].map(ent["vendor_created"]))
    p["registry_status"] = p["entity_id"].map(ent["registry_status"])
    p["status_date"] = pd.to_datetime(p["entity_id"].map(ent["status_date"]))
    p["address_key"] = p["entity_id"].map(ent["address_key"])
    p["director_address_key"] = p["entity_id"].map(ent["director_address_key"])
    p["abn"] = p["entity_id"].map(ent["abn"])
    p["display_name"] = p["entity_id"].map(ent["display_name"])
    p["is_supplier"] = p["entity_kind"].eq("supplier")
    p["is_claims"] = p["program"].eq("claims").astype(int)

    cluster_sizes = entities.groupby("cluster_id").size()
    p["cluster_size"] = p["cluster_id"].map(cluster_sizes).fillna(1).astype(int)

    home = dict(zip(officers["officer_id"], officers["home_key"]))
    claim_assessor = dict(zip(claims["claim_id"], claims["assessor_officer_id"]))
    p["approver_key"] = p["approver_officer_id"].map(home)
    p["assessor_key"] = p["invoice_ref"].map(claim_assessor).map(home)

    # --- timing ----------------------------------------------------------------------------------
    supplier_first = p[p["is_supplier"]].groupby("entity_id")["payment_date"].min()
    p["first_invoice"] = p["entity_id"].map(supplier_first)
    first_seen = p.groupby("entity_id")["payment_date"].transform("min")
    p["entity_tenure_days"] = (p["payment_date"] - first_seen).dt.days
    p["vendor_age_days"] = (p["payment_date"] - p["vendor_created"]).dt.days.fillna(-1).astype(int)
    p["days_created_to_first_invoice"] = (p["first_invoice"] - p["vendor_created"]).dt.days.fillna(-1).astype(int)
    p["days_since_first_invoice"] = (p["payment_date"] - p["first_invoice"]).dt.days.fillna(-1).astype(int)
    p["_day"] = (p["payment_date"] - pd.Timestamp("1970-01-01")).dt.days
    p["payments_30d"] = (p.groupby("entity_id")["_day"]
                         .transform(lambda s: pd.Series(_count_prior_within(s.to_numpy(), RECENT_WINDOW_DAYS), index=s.index)))

    # --- amount and counterparty profile ---------------------------------------------------------
    p["amount_log"] = np.log1p(p["amount"])
    p["is_round_amount"] = (p["amount"] % 100 == 0).astype(int)
    p["weekday"] = p["payment_date"].dt.weekday
    entity_median = p.groupby("entity_id")["amount"].transform("median")
    p["amount_vs_entity_median"] = p["amount"] / entity_median.clip(lower=1.0)
    p["bank_entity_count"] = p["bank_key"].map(p.groupby("bank_key")["entity_id"].nunique()).astype(int)
    pair = p.groupby(["entity_id", "approver_officer_id"]).size().rename("pair_n")
    p = p.join(pair, on=["entity_id", "approver_officer_id"])
    p["approver_share"] = p["pair_n"] / p.groupby("entity_id")["payment_id"].transform("size")
    p = p.drop(columns=["pair_n"])

    # --- rule signals ----------------------------------------------------------------------------
    p["rule_shared_bank_account"] = (p["is_supplier"] & (p["bank_entity_count"] >= 2)).astype(int)
    p["rule_new_vendor_early_invoice"] = (
        p["is_supplier"]
        & p["days_created_to_first_invoice"].between(0, NEW_VENDOR_MAX_GAP_DAYS)
        & p["days_since_first_invoice"].between(0, NEW_VENDOR_EARLY_DAYS)
    ).astype(int)

    dup = np.zeros(len(p), dtype=bool)
    split = np.zeros(len(p), dtype=bool)
    p = p.sort_values(["entity_id", "payment_date", "payment_id"]).copy()
    for _, grp in p.groupby("entity_id", sort=False):
        if not grp["is_supplier"].iloc[0]:
            continue
        idx = p.index.get_indexer(grp.index)
        digits = [("".join(ch for ch in str(r) if ch.isdigit())) for r in grp["invoice_ref"]]
        dup[idx] = _near_duplicate_flags(grp["amount"].to_numpy(), grp["_day"].to_numpy(), digits)
        band = grp["amount"].between(SPLIT_LOW, SPLIT_HIGH, inclusive="left").to_numpy()
        days = grp["_day"].to_numpy()
        for k in np.flatnonzero(band):
            near = band & (np.abs(days - days[k]) <= SPLIT_WINDOW_DAYS)
            if near.sum() >= 2:
                split[idx[k]] = True
    p["rule_duplicate_invoice"] = dup.astype(int)
    p["rule_split_below_threshold"] = split.astype(int)

    p["rule_officer_supplier_link"] = (
        p["is_supplier"] & p["approver_key"].notna() & (p["approver_key"] == p["director_address_key"])
    ).astype(int)
    p["rule_claimant_contact_reuse"] = (
        p["entity_kind"].eq("claimant") & (p["cluster_size"] >= CONTACT_REUSE_MIN_CLUSTER)
    ).astype(int)
    p["rule_claimant_assessor_address"] = (
        p["is_claims"].astype(bool) & p["assessor_key"].notna() & (p["assessor_key"] == p["address_key"])
    ).astype(int)
    p["rule_cancelled_registration_paid"] = (
        p["is_supplier"] & p["registry_status"].fillna("").str.lower().eq("cancelled")
        & (p["payment_date"] > p["status_date"])
    ).astype(int)

    out_cols = ["payment_id", "payee_src_id", "entity_id", "cluster_id", "entity_kind", "display_name", "abn",
                "program", "amount", "payment_date", "invoice_ref", "approver_officer_id", "bank_key",
                "address_key", "registry_status", "status_date"] + MODEL_FEATURES + ENTITY_CONTEXT_FEATURES
    return p[out_cols].sort_values(["payment_date", "payment_id"]).reset_index(drop=True)
