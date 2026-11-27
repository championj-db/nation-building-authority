"""Turn extraction output into reviewable evidence: per-field values with confidence and page
location, three-way matching (invoice, purchase order, goods receipt), the correctly rendered
checks, document status and the RMG 417 payment clock.

Pure Python: src/03_assess.py feeds it rows from the silver tables, and tests/test_assess.py
feeds it hand-built ones.
"""

from __future__ import annotations

import datetime as dt
import json
import re

from common import (
    INVOICE_FIELD_LABELS,
    INVOICE_REQUIRED_FIELDS,
    INVOICE_SCHEMA,
    NUMBER_FIELDS,
    REVIEW_THRESHOLD,
)
from rules import (
    InvoiceContext,
    digits,
    document_status,
    evaluate_invoice,
    money,
    parse_date,
    pay_by,
    routing_confidence,
)


# ---------------------------------------------------------------------------
# Citations -> page regions and cited text
# ---------------------------------------------------------------------------
def _key(bbox: dict) -> tuple:
    return (int(bbox.get("page_id") or 0), tuple(int(round(float(c))) for c in (bbox.get("coord") or [])))


def index_elements(elements_json: str | None) -> list[dict]:
    out = []
    for e in json.loads(elements_json or "[]") or []:
        boxes = e.get("bbox") or []
        out.append({"id": e.get("id"), "type": e.get("type"), "content": e.get("content") or "",
                    "boxes": [_key(b) for b in boxes]})
    return out


def _overlap(a: tuple, b: tuple) -> float:
    if a[0] != b[0] or len(a[1]) != 4 or len(b[1]) != 4:
        return 0.0
    ax0, ay0, ax1, ay1 = a[1]
    bx0, by0, bx1, by1 = b[1]
    iw, ih = max(0, min(ax1, bx1) - max(ax0, bx0)), max(0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    area = max((ax1 - ax0) * (ay1 - ay0), 1)
    return inter / area


def resolve_citation(citation_ids: list, citations: list[dict], elements: list[dict]) -> tuple[list[dict], str]:
    """(regions, cited_text). A region is {page, x0, y0, x1, y1} in page-image pixels."""
    by_id = {c.get("id"): c for c in citations or []}
    regions, texts = [], []
    for cid in citation_ids or []:
        c = by_id.get(cid)
        if not c:
            continue
        for b in c.get("bbox") or []:
            k = _key(b)
            if len(k[1]) == 4:
                regions.append({"page": k[0], "x0": k[1][0], "y0": k[1][1], "x1": k[1][2], "y1": k[1][3]})
            match = [e for e in elements if k in e["boxes"]]
            if not match:  # citation boxes are usually element boxes; fall back to overlap
                match = [e for e in elements if any(_overlap(k, eb) > 0.5 for eb in e["boxes"])]
            texts.extend(e["content"] for e in match)
    return regions, "\n".join(texts)


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------
def canonical(name: str, value) -> str | None:
    """Display and comparison form: numbers to 2dp, dates ISO, identifiers without spaces."""
    if value is None or value == "":
        return None
    if name in NUMBER_FIELDS:
        n = money(value)
        return f"{n:.2f}" if n is not None else str(value)
    if name == "invoice_date":
        d = parse_date(value)
        return d.isoformat() if d else str(value)
    if name in ("supplier_abn", "recipient_abn", "bank_bsb", "bank_account"):
        return digits(value) or str(value)
    return " ".join(str(value).split())


def field_rows(fields_json: str | None, citations_json: str | None, elements_json: str | None, full_text: str = "") -> list[dict]:
    """One row per declared invoice field, in display order, with routing confidence and regions."""
    fields = json.loads(fields_json or "{}") or {}
    citations = json.loads(citations_json or "[]") or []
    elements = index_elements(elements_json)
    rows = []
    for order, name in enumerate(INVOICE_FIELD_LABELS):
        obj = fields.get(name)
        if isinstance(obj, dict):
            raw, conf, cids = obj.get("value"), obj.get("confidence_score"), obj.get("citation_ids") or []
        else:
            raw, conf, cids = obj, None, []
        regions, cited = resolve_citation(cids, citations, elements)
        score, grounded, valid = routing_confidence(name, raw, conf, cited or full_text, full_text)
        in_region = bool(cited) and score == routing_confidence(name, raw, conf, cited)[0]
        required = name in INVOICE_REQUIRED_FIELDS
        rows.append({
            "field": name, "label": INVOICE_FIELD_LABELS[name], "display_order": order, "required": required,
            "value": canonical(name, raw), "model_confidence": None if conf is None else round(float(conf), 3),
            "routing_confidence": score, "grounded": grounded, "type_valid": valid, "in_cited_region": in_region,
            "below_threshold": required and score < REVIEW_THRESHOLD,
            "regions_json": json.dumps(regions), "cited_text": cited[:400] if cited else None,
            "field_type": INVOICE_SCHEMA[name]["type"],
        })
    return rows


def values_of(rows: list[dict]) -> dict:
    return {r["field"]: r["value"] for r in rows}


def lowest_required(rows: list[dict]) -> float:
    req = [r["routing_confidence"] for r in rows if r["required"]]
    return min(req) if req else 0.0


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def normalise_po(value) -> str | None:
    d = digits(value)
    return f"PO-{d}" if d else None


def normalise_invoice_number(value) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper())


def normalise_name(value) -> str:
    s = re.sub(r"[^a-z ]", "", str(value or "").lower())
    for suffix in (" pty ltd", " ltd", " partners", " co", " pty"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return " ".join(s.split())


class Ledger:
    """What AP knows when each invoice arrives, in arrival order: orders, vendors, receipts not yet
    matched, invoice numbers already seen, and how much of each order has been billed."""

    def __init__(self, purchase_orders: list[dict], suppliers: list[dict], receipts: list[dict], history_billed: dict | None = None):
        self.po = {p["po_number"]: p for p in purchase_orders}
        self.suppliers = {s["supplier_id"]: s for s in suppliers}
        self.by_abn = {digits(s["abn"]): s for s in suppliers}
        self.by_name = {normalise_name(s["name"]): s for s in suppliers}
        self.receipts = sorted(receipts, key=lambda r: r["receipted_date"])
        self.used_receipts: set[str] = set()
        self.seen: dict[tuple, str] = {}
        self.billed: dict[str, float] = {}

    def supplier_for(self, po: dict | None, values: dict) -> dict | None:
        """Identify the vendor from the document itself first (ABN, then name), and only then from
        the order it quotes, so that an order raised with someone else shows up as a mismatch."""
        abn = digits(values.get("supplier_abn"))
        if abn in self.by_abn:
            return self.by_abn[abn]
        by_name = self.by_name.get(normalise_name(values.get("supplier_name")))
        if by_name:
            return by_name
        return self.suppliers.get(po["supplier_id"]) if po else None

    def match_receipt(self, po_number: str | None, total: float | None, as_at: dt.date) -> dict | None:
        """Three-way match: an unused receipt on the same order for the same amount (within $1)."""
        if not po_number or total is None:
            return None
        for r in self.receipts:
            if r["receipt_id"] in self.used_receipts or r["po_number"] != po_number or r["receipted_date"] > as_at:
                continue
            if r.get("amount_inc_gst") is None or abs(float(r["amount_inc_gst"]) - total) <= 1.0:
                return r
        return None

    def assess(self, doc_id: str, doc_type: str, values: dict, arrival: dt.date, today: dt.date) -> tuple[InvoiceContext, dict]:
        po = self.po.get(normalise_po(values.get("po_number")) or "")
        supplier = self.supplier_for(po, values)
        total = money(values.get("total_inc_gst"))
        key = (supplier["supplier_id"] if supplier else normalise_name(values.get("supplier_name")),
               normalise_invoice_number(values.get("invoice_number")))
        duplicate_of = self.seen.get(key) if key[1] else None
        receipt = None if doc_type != "tax_invoice" or duplicate_of else self.match_receipt(po["po_number"] if po else None, total, today)
        po_ctx = None
        if po:
            po_ctx = {**po, "invoiced_to_date_inc_gst": self.billed.get(po["po_number"], 0.0)}
        ctx = InvoiceContext(po=po_ctx, supplier=supplier, receipt_date=receipt["receipted_date"] if receipt else None,
                             duplicate_of=duplicate_of)
        return ctx, {"po": po, "supplier": supplier, "receipt": receipt, "key": key}

    def commit(self, doc_id: str, doc_type: str, match: dict, values: dict, status: str) -> None:
        """Record the document so later ones see it. Exceptions are going back to the supplier and
        do not consume order value or a receipt."""
        if match["key"][1] and match["key"] not in self.seen:
            self.seen[match["key"]] = doc_id
        if status == "exception" or doc_type != "tax_invoice":
            return
        if match["receipt"]:
            self.used_receipts.add(match["receipt"]["receipt_id"])
        if match["po"]:
            total = money(values.get("total_inc_gst")) or 0.0
            self.billed[match["po"]["po_number"]] = self.billed.get(match["po"]["po_number"], 0.0) + total


# ---------------------------------------------------------------------------
# One invoice, end to end
# ---------------------------------------------------------------------------
def assess_invoice(doc: dict, ledger: Ledger, holidays: set[dt.date], today: dt.date) -> dict:
    """doc: doc_id, doc_type, arrival_date, channel, fields_json, citations_json, elements_json, full_text."""
    rows = field_rows(doc["fields_json"], doc["citations_json"], doc["elements_json"], doc.get("full_text") or "")
    values = values_of(rows)
    ctx, match = ledger.assess(doc["doc_id"], doc["doc_type"], values, doc["arrival_date"], today)
    checks = evaluate_invoice(values, ctx, doc["doc_type"])
    low = lowest_required(rows)
    status = document_status(checks, low, is_invoice=True)
    ledger.commit(doc["doc_id"], doc["doc_type"], match, values, status)

    supplier, po, receipt = match["supplier"], match["po"], match["receipt"]
    einvoice = doc.get("channel") == "peppol" and bool(supplier and supplier.get("einvoicing"))
    trigger = None
    if doc["doc_type"] == "tax_invoice" and status in ("ready", "needs_review") and ctx.receipt_date:
        trigger = max(doc["arrival_date"], ctx.receipt_date)
    clock = pay_by(trigger, holidays, einvoice=einvoice) if trigger else None
    clock_2027 = pay_by(trigger, holidays, einvoice=einvoice, regime="2027") if trigger else None
    failed = [c for c in checks if c.passed is False]
    return {
        "rows": rows,
        "checks": checks,
        "summary": {
            "doc_id": doc["doc_id"], "doc_type": doc["doc_type"], "status": status,
            "lowest_required_confidence": low,
            "fields_below_threshold": [r["field"] for r in rows if r["below_threshold"]],
            "failed_checks": [c.code for c in failed],
            "return_reasons": [c.meta["return_reason"] for c in failed if c.meta["supplier_fault"] and c.meta["return_reason"]],
            "supplier_id": supplier["supplier_id"] if supplier else None,
            "supplier_name": supplier["name"] if supplier else values.get("supplier_name"),
            "invoice_number": values.get("invoice_number"),
            "invoice_date": parse_date(values.get("invoice_date")),
            "po_number_quoted": values.get("po_number"),
            "po_number": po["po_number"] if po else None,
            "contract_id": po["contract_id"] if po else None,
            "po_value_inc_gst": po["po_value_inc_gst"] if po else None,
            "po_billed_before_inc_gst": (ctx.po or {}).get("invoiced_to_date_inc_gst"),
            "subtotal_ex_gst": money(values.get("subtotal_ex_gst")),
            "gst_amount": money(values.get("gst_amount")),
            "total_inc_gst": money(values.get("total_inc_gst")),
            "receipt_id": receipt["receipt_id"] if receipt else None,
            "receipt_date": ctx.receipt_date,
            "duplicate_of": ctx.duplicate_of,
            "einvoice": einvoice,
            "trigger_date": trigger,
            "clock_regime": clock.regime if clock else None,
            "term_label": clock.term_label if clock else None,
            "pay_by_date": clock.pay_by if clock else None,
            "pay_by_2027_date": clock_2027.pay_by if clock_2027 else None,
        },
    }
