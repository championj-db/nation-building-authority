"""Shared contract for the improper payments detection use case.

Every pipeline step imports this module so the pattern vocabulary, score bands, table names and
helpers agree. Copied in from the geospatial use case, not imported from it: use cases never
import each other (see ../../CONTRIBUTING.md). If a definition changes, it changes here.

No environment-specific value lives in this file: catalog, schema and volume arrive as job
parameters, never as literals.

Data provenance
  synthetic  every source table (suppliers, registry, claimants, claims, officers, payments,
             ground truth). Seeded and deterministic. No record describes a real person or
             business; names are generated from word lists and ABNs are random 11-digit strings.
"""

import datetime as dt
import hashlib
import os

# ---------------------------------------------------------------------------
# Scores and bands
# ---------------------------------------------------------------------------
FLAG_SCORE = 50          # a payment scoring at or above this is flagged for case building
HIGH_BAND_SCORE = 80     # case risk_band 'high' at or above this; 'medium' from case_threshold
# Any payment that fires a rule is scored at least this high. The model ranks within rule hits; it
# does not get to suppress a known pattern because it has seen few examples of it. Set at the
# default case_threshold so every rule hit reaches the queue.
RULE_FLOOR_SCORE = 60

# Ties on the primary signal are broken by this order (most investigable first).
SIGNAL_PRECEDENCE = [
    "cancelled_registration_paid",
    "officer_supplier_link",
    "claimant_assessor_address",
    "shared_bank_account",
    "claimant_contact_reuse",
    "duplicate_invoice",
    "split_below_threshold",
    "new_vendor_early_invoice",
]

# ---------------------------------------------------------------------------
# Patterns: one row per rule code the app can display.
#   label   short badge text (primary_signal_label)
#   title   factor heading, in the plain voice of the investigator notes
#   detail  templated sentence; {n} is a count written out in words, {days} is a number
# Ground-truth codes that are not rule signals (benign look-alikes) are not listed here.
# ---------------------------------------------------------------------------
PATTERNS = {
    "shared_bank_account": {
        "label": "Shared bank account",
        "title": "Bank account shared across suppliers",
        "detail": "The nominated account also appears on {n} separately registered supplier records.",
    },
    "new_vendor_early_invoice": {
        "label": "New vendor, early invoice",
        "title": "Supplier created shortly before first invoice",
        "detail": "The supplier record was created {days} days before its first invoice, and the payments fall in its first 60 days.",
    },
    "duplicate_invoice": {
        "label": "Duplicate invoice pattern",
        "title": "Near-duplicate invoice paid",
        "detail": "{n} near-identical invoices were paid to this supplier within a week of each other.",
    },
    "split_below_threshold": {
        "label": "Split below approval limit",
        "title": "Invoices clustered just under the approval limit",
        "detail": "{n} invoices between $9,000 and $10,000 were paid to this supplier within 14 days.",
    },
    "officer_supplier_link": {
        "label": "Approver linked to supplier",
        "title": "Approver lives at the supplier's director address",
        "detail": "The approving officer's home address matches the director address on the supplier record.",
    },
    "claimant_contact_reuse": {
        "label": "Reused contact details",
        "title": "Claimants share contact details or bank account",
        "detail": "{n} other claimant records share a phone number, email or bank account with this claimant.",
    },
    "claimant_assessor_address": {
        "label": "Address linked to assessor",
        "title": "Claimant address matches the assessor",
        "detail": "The claimant's address matches the home address of the officer who assessed the claim.",
    },
    "cancelled_registration_paid": {
        "label": "Cancelled registration paid",
        "title": "Payment made after registration was cancelled",
        "detail": "The business registry shows this supplier as cancelled, and {n} payments were made after the cancellation date.",
    },
    "model_only": {
        "label": "Unusual payment pattern",
        "title": "Unusual payment profile",
        "detail": "No specific rule fired. The combination of amount, timing and counterparty history scores highly against the training population.",
    },
}

# Continuous model features that carry a factor heading when they drive a score.
# feature name -> (factor_code, title, detail)
MODEL_FACTORS = {
    "amount_log": ("amount_profile", "Amount unusual for this counterparty",
                   "The payment is large compared with this counterparty's usual payments."),
    "amount_vs_entity_median": ("amount_profile", "Amount unusual for this counterparty",
                                "The payment is large compared with this counterparty's usual payments."),
    "vendor_age_days": ("vendor_tenure", "Counterparty record is recent",
                        "The counterparty record is young relative to the payment."),
    "days_created_to_first_invoice": ("vendor_tenure", "Counterparty record is recent",
                                      "The counterparty record was created shortly before its first invoice."),
    "payments_30d": ("payment_velocity", "Payments clustered in a short window",
                     "Several payments to this counterparty fall within 30 days."),
    "approver_share": ("approver_concentration", "One officer approves most payments",
                       "A single officer approved most payments to this counterparty."),
    "bank_entity_count": ("account_reuse", "Account used across several counterparties",
                          "The nominated account receives payments from more than one counterparty."),
    "is_round_amount": ("round_amount", "Round-sum payment",
                        "The amount is an exact multiple of $100."),
    "cluster_size": ("linked_group", "Part of a linked group of records",
                     "This record shares contact details with other records in its group."),
    "weekday": ("payment_timing", "Paid outside the usual pattern",
                "Payment timing is unusual for this counterparty."),
}
MODEL_FACTOR_FALLBACK = ("model_pattern", "Unusual payment profile", PATTERNS["model_only"]["detail"])

NUMBER_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
                8: "eight", 9: "nine", 10: "ten"}


def count_words(n: int) -> str:
    """Counts as words up to ten, digits beyond: 'two', '14'."""
    return NUMBER_WORDS.get(int(n), str(int(n)))


def pattern_detail(code: str, **values) -> str:
    """Plain-English detail for a pattern code, with n rendered as a word where it is small."""
    template = PATTERNS.get(code, PATTERNS["model_only"])["detail"]
    if "n" in values:
        values["n"] = count_words(values["n"])
    return template.format(**values)


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------
def stable_case_ids(entity_ids, prefix: str = "IP") -> dict:
    """Map each entity id to '<prefix>-' + 4 digits, deterministically (IP for open cases).

    The digits come from a hash of the entity id, so a case keeps its id across reruns with the
    same seed. Collisions are resolved by probing in sorted order, so the mapping depends only on
    the set of entity ids, never on row order.
    """
    taken: set[int] = set()
    out = {}
    for entity_id in sorted(set(entity_ids)):
        n = int(hashlib.sha1(entity_id.encode("utf-8")).hexdigest(), 16) % 10000
        while n in taken:
            n = (n + 1) % 10000
        taken.add(n)
        out[entity_id] = f"{prefix}-{n:04d}"
    return out


def opened_offset_days(case_id: str) -> int:
    """Spread opened dates over the last 30 days, deterministically per case."""
    return int(hashlib.sha1(case_id.encode("utf-8")).hexdigest(), 16) % 30


def risk_band(score: int, case_threshold: int) -> str | None:
    if score >= HIGH_BAND_SCORE:
        return "high"
    if score >= case_threshold:
        return "medium"
    return None


# ---------------------------------------------------------------------------
# Bundle parameters and naming
# ---------------------------------------------------------------------------
def get_params(defaults: dict, dbutils) -> dict:
    """Read notebook widgets, creating each with its default first."""
    out = {}
    for key, default in defaults.items():
        dbutils.widgets.text(key, str(default))
        out[key] = dbutils.widgets.get(key).strip()
    return out


def fq(catalog: str, schema: str, name: str) -> str:
    return f"{catalog}.{schema}.{name}"


def volume_dir(catalog: str, schema: str, volume: str, *parts: str) -> str:
    return os.path.join(f"/Volumes/{catalog}/{schema}/{volume}", *parts)


def as_of_date(raw: str) -> dt.date:
    """Run date for relative data: the 'as_of' parameter (YYYY-MM-DD) or today when blank."""
    raw = (raw or "").strip()
    return dt.date.fromisoformat(raw) if raw else dt.date.today()


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
PROVENANCE_SCHEMA = (
    "dataset string, step string, publisher string, source_url string, attribution string, "
    "licence string, features long, from_cache boolean, fetch_error string, fetched_at timestamp"
)


def record_provenance(spark, table: str, step: str, rows: list[tuple]) -> None:
    """Replace this step's rows in the provenance table.

    Each row is (dataset, publisher, source_url, attribution, licence, features, from_cache,
    fetch_error). fetched_at is stamped here. For this use case every source is synthetic, so the
    licence column says so and source_url is blank.
    """
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    spark.sql(f"CREATE TABLE IF NOT EXISTS {table} ({PROVENANCE_SCHEMA}) "
              "COMMENT 'Where every input came from. Everything here is synthetic and seeded.'")
    spark.sql(f"DELETE FROM {table} WHERE step = '{step}'")
    full = [(r[0], step, *r[1:], now) for r in rows]
    spark.createDataFrame(full, PROVENANCE_SCHEMA).write.mode("append").saveAsTable(table)


# ---------------------------------------------------------------------------
# Writing driver-side frames as Unity Catalog tables
# ---------------------------------------------------------------------------
def sql_literal(text: str) -> str:
    """Single-quoted SQL string literal with quotes doubled."""
    return "'" + str(text).replace("'", "''") + "'"


def write_table(spark, pdf, table: str, comment: str = "") -> int:
    """Replace `table` with a pandas frame. Nulls are passed as None, not NaN.

    Used for the outputs that are built on the driver (small enough to hold in memory); the bronze
    sources and gold tables all go through here so they are typed and commented the same way.
    """
    import pandas as pd

    clean = pdf.astype(object).where(pd.notna(pdf), None)
    sdf = spark.createDataFrame(clean) if len(clean) else None
    if sdf is None:
        raise ValueError(f"refusing to write an empty frame to {table}; the caller must handle this")
    sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table)
    if comment:
        spark.sql(f"COMMENT ON TABLE {table} IS {sql_literal(comment)}")
    return len(clean)


def write_empty(spark, table: str, ddl: str, comment: str = "") -> None:
    """Create `table` with the given column DDL if it does not exist yet, and leave any rows alone."""
    spark.sql(f"CREATE TABLE IF NOT EXISTS {table} ({ddl})")
    if comment:
        spark.sql(f"COMMENT ON TABLE {table} IS {sql_literal(comment)}")
