import datetime as dt
import random

import pytest

import rules
from common import BUYER_ABN, BUYER_NAME
from rules import InvoiceContext

ACT_2026 = {dt.date(2026, 12, 25), dt.date(2026, 12, 28), dt.date(2027, 1, 1), dt.date(2027, 1, 26)}


def test_abn_checksum_known_valid_and_invalid():
    assert rules.abn_valid("51 824 753 556")  # the ATO's published example ABN
    assert not rules.abn_valid("51 824 753 557")
    assert not rules.abn_valid("1234")
    assert rules.abn_valid(BUYER_ABN)


def test_make_and_corrupt_abn():
    rng = random.Random(1)
    for _ in range(50):
        good = rules.make_abn(rng)
        assert rules.abn_valid(good)
        assert not rules.abn_valid(rules.corrupt_abn(good, rng))


@pytest.mark.parametrize("sub,gst,total,ok", [
    (10300, 1030, 11330, True),
    (10300, 1030.04, 11330.04, True),
    (10300, 1545, 11845, False),        # 15%
    (10300, 1030, 11355, False),        # total does not add up
    ("$10,300.00", "$1,030.00", "$11,330.00", True),
])
def test_gst(sub, gst, total, ok):
    assert rules.gst_consistent(sub, gst, total) is ok


def test_gst_not_registered_charges_no_gst():
    assert rules.gst_consistent(5000, 0, 5000, gst_registered=False)
    assert not rules.gst_consistent(5000, 500, 5500, gst_registered=False)


def test_business_days_skip_weekends_and_holidays():
    # Thursday 24 Dec 2026 + 3 business days: skip Fri 25 (Christmas), weekend, Mon 28 (Boxing Day substitute)
    assert rules.add_business_days(dt.date(2026, 12, 24), 1, ACT_2026) == dt.date(2026, 12, 29)
    assert rules.business_days_between(dt.date(2026, 12, 24), dt.date(2026, 12, 31), ACT_2026) == 3
    assert rules.business_days_between(dt.date(2026, 12, 31), dt.date(2026, 12, 24), ACT_2026) == -3


def test_pay_by_regimes():
    current = rules.pay_by(dt.date(2026, 11, 20), ACT_2026)
    assert current.regime == "current" and current.pay_by == dt.date(2026, 12, 10)
    einv = rules.pay_by(dt.date(2026, 11, 20), ACT_2026, einvoice=True)
    assert einv.pay_by == dt.date(2026, 11, 25)
    # Clock starts on 1 Jan 2027 (trigger 31 Dec): the 2027 terms apply, 10 business days.
    new = rules.pay_by(dt.date(2026, 12, 31), ACT_2026)
    assert new.regime == "2027" and new.pay_by == dt.date(2027, 1, 15)
    what_if = rules.pay_by(dt.date(2026, 11, 20), ACT_2026, regime="2027")
    assert what_if.pay_by == dt.date(2026, 12, 4)


def test_interest_threshold():
    assert rules.interest_accrued(100000, 10, 0.1151) == pytest.approx(315.34, abs=0.01)
    assert rules.interest_payable(5000, 10, 0.1151) == 0.0  # $15.77 accrued: under the $100 threshold
    assert rules.interest_payable(100000, 10, 0.1151) > 100


def test_grounding_and_routing():
    text = "Invoice date: 18 November 2026\nTotal (incl. GST) $11,330.00\nABN 51 824 753 556"
    assert rules.value_grounded("invoice_date", "2026-11-18", text)
    assert rules.value_grounded("total_inc_gst", 11330, text)
    assert rules.value_grounded("supplier_abn", "51824753556", text)
    assert not rules.value_grounded("total_inc_gst", 11380, text)
    score, grounded, valid = rules.routing_confidence("total_inc_gst", 11380, 0.98, text)
    assert not grounded and score < 0.85
    assert rules.routing_confidence("invoice_number", None, 1.0, text)[0] == 0.0


def clean_invoice(**over):
    v = {"document_title": "Tax invoice", "supplier_name": "Kestrel Ridge Consulting Pty Ltd", "supplier_abn": "51824753556",
         "recipient_name": BUYER_NAME, "recipient_abn": None, "invoice_number": "KRC-1", "invoice_date": "2026-11-18",
         "po_number": "PO-1", "subtotal_ex_gst": "10300.00", "gst_amount": "1030.00", "total_inc_gst": "11330.00"}
    v.update(over)
    return v


def ctx(**over):
    base = dict(po={"po_number": "PO-1", "supplier_id": "V1", "status": "open", "po_value_inc_gst": 50000, "invoiced_to_date_inc_gst": 0},
                supplier={"supplier_id": "V1", "abn": "51824753556", "gst_registered": True}, receipt_date=dt.date(2026, 11, 17))
    base.update(over)
    return InvoiceContext(**base)


def failed(checks):
    return {c.code for c in checks if c.passed is False}


def test_clean_invoice_is_ready():
    checks = rules.evaluate_invoice(clean_invoice(), ctx())
    assert failed(checks) == set()
    assert rules.document_status(checks, 0.95) == "ready"


@pytest.mark.parametrize("values,context,code", [
    (dict(po_number=None), {}, "po_quoted"),
    (dict(supplier_abn="51824753557"), {}, "supplier_abn_valid"),
    (dict(gst_amount="1500.00", total_inc_gst="11800.00"), {}, "gst_calculated"),
    (dict(recipient_name="Department of Regional Development"), {}, "addressed_to_buyer"),
    (dict(document_title="Invoice"), {}, "tax_invoice_label"),
    ({}, dict(duplicate_of="DOC-000001"), "not_duplicate"),
    ({}, dict(po={"po_number": "PO-1", "supplier_id": "V1", "status": "open", "po_value_inc_gst": 12000, "invoiced_to_date_inc_gst": 5000}), "within_po_value"),
    ({}, dict(po={"po_number": "PO-1", "supplier_id": "V1", "status": "closed", "po_value_inc_gst": 50000, "invoiced_to_date_inc_gst": 0}), "po_matches"),
    ({}, dict(supplier={"supplier_id": "V1", "abn": "83792749072", "gst_registered": True}), "supplier_abn_matches_vendor"),
])
def test_each_defect_fails_its_check(values, context, code):
    checks = rules.evaluate_invoice(clean_invoice(**values), ctx(**context))
    assert code in failed(checks)
    assert rules.document_status(checks, 0.95) == "exception"


def test_missing_receipt_is_awaiting_delivery_not_exception():
    checks = rules.evaluate_invoice(clean_invoice(), ctx(receipt_date=None))
    assert failed(checks) == {"delivery_acknowledged"}
    assert rules.document_status(checks, 0.95) == "awaiting_delivery"


def test_low_confidence_beats_exception():
    # A "failure" on a field we could not read reliably goes to a person before it goes to the supplier.
    checks = rules.evaluate_invoice(clean_invoice(po_number=None), ctx())
    assert rules.document_status(checks, 0.4) == "needs_review"


def test_recipient_identity_only_from_1000():
    small = clean_invoice(recipient_name=None, subtotal_ex_gst="500.00", gst_amount="50.00", total_inc_gst="550.00")
    checks = rules.evaluate_invoice(small, ctx())
    assert "recipient_identity" not in failed(checks)
    big = clean_invoice(recipient_name=None)
    assert "recipient_identity" in failed(rules.evaluate_invoice(big, ctx()))


def test_value_found_elsewhere_is_grounded_at_a_discount():
    cited = "Kestrel Ridge Consulting Pty Ltd"
    full = "Kestrel Ridge Consulting Pty Ltd\nABN 51 824 753 556 | Level 4"
    in_region, g1, _ = rules.routing_confidence("supplier_abn", "51824753556", 1.0, full, full)
    elsewhere, g2, _ = rules.routing_confidence("supplier_abn", "51824753556", 1.0, cited, full)
    nowhere, g3, _ = rules.routing_confidence("supplier_abn", "51824753557", 1.0, cited, full)
    assert g1 and g2 and not g3
    assert in_region == 1.0 and 0.85 <= elsewhere < 1.0 and nowhere < 0.85


def test_credit_note_gst_is_checked_on_magnitudes():
    v = clean_invoice(document_title="Adjustment note", subtotal_ex_gst="1726.53", gst_amount="172.65", total_inc_gst="-1899.18")
    assert "gst_calculated" not in failed(rules.evaluate_invoice(v, ctx(), doc_type="adjustment_note"))
