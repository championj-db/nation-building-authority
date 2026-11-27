"""Deterministic rules: ABN check digits, GST arithmetic, business days, RMG 417 payment clock,
interest exposure, field confidence routing and the "correctly rendered" checks.

Pure Python with no Spark dependency, so tests/test_rules.py can cover it locally. The pipeline
(src/04_assess.py) calls these functions on each extracted document.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from common import (
    BUYER_ABN,
    BUYER_NAME,
    CHECK_ORDER,
    CHECKS,
    DATE_FIELDS,
    GST_RATE,
    GST_TOLERANCE_AUD,
    INTEREST_PAYABLE_OVER_AUD,
    INVALID_TYPE_PENALTY,
    NUMBER_FIELDS,
    RECIPIENT_REQUIRED_FROM_AUD,
    REVIEW_THRESHOLD,
    TERM_BUSINESS_DAYS_2027,
    TERM_CALENDAR_DAYS,
    TERM_EINVOICE_CALENDAR_DAYS,
    TERMS_CHANGE_DATE,
    UNCITED_PENALTY,
    UNGROUNDED_PENALTY,
    digits,
)

# ---------------------------------------------------------------------------
# ABN
# ---------------------------------------------------------------------------
_ABN_WEIGHTS = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)


def abn_valid(value) -> bool:
    """ATO ABN check-digit test: subtract 1 from the first digit, weight, sum, divisible by 89."""
    d = digits(value)
    if len(d) != 11 or d[0] == "0":
        return False
    nums = [int(c) for c in d]
    nums[0] -= 1
    return sum(w * n for w, n in zip(_ABN_WEIGHTS, nums)) % 89 == 0


def make_abn(rng) -> str:
    """A random 11-digit number that passes the ABN check-digit test, formatted 'NN NNN NNN NNN'."""
    while True:
        body = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(10)]
        if abn_valid("".join(map(str, body))):
            s = "".join(map(str, body))
            return f"{s[:2]} {s[2:5]} {s[5:8]} {s[8:]}"


def corrupt_abn(abn: str, rng) -> str:
    """Change one digit so the check-digit test fails (a transcription error on the invoice)."""
    d = list(digits(abn))
    while True:
        i = rng.randint(2, 10)
        original = d[i]
        d[i] = str((int(original) + rng.randint(1, 9)) % 10)
        if not abn_valid("".join(d)):
            s = "".join(d)
            return f"{s[:2]} {s[2:5]} {s[5:8]} {s[8:]}"
        d[i] = original


def format_abn(value) -> str:
    d = digits(value)
    return f"{d[:2]} {d[2:5]} {d[5:8]} {d[8:]}" if len(d) == 11 else str(value or "")


# ---------------------------------------------------------------------------
# Money and GST
# ---------------------------------------------------------------------------
def money(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    negative = s.startswith("-") or s.startswith("(") or s.upper().endswith("CR")
    s = re.sub(r"[^0-9.]", "", s)
    if not s or s.count(".") > 1:
        return None
    n = float(s)
    return -n if negative else n


def gst_consistent(subtotal, gst, total, gst_registered: bool = True) -> bool:
    sub, g, tot = money(subtotal), money(gst), money(total)
    if sub is None or g is None or tot is None:
        return False
    if abs(sub + g - tot) > GST_TOLERANCE_AUD:
        return False
    if not gst_registered:
        return abs(g) <= GST_TOLERANCE_AUD
    # Every supply in this corpus is taxable, so GST must be 10% of the amount.
    return abs(g - sub * GST_RATE) <= GST_TOLERANCE_AUD


# ---------------------------------------------------------------------------
# Business days and the payment clock
# ---------------------------------------------------------------------------
def is_business_day(day: dt.date, holidays: set[dt.date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def add_business_days(start: dt.date, n: int, holidays: set[dt.date]) -> dt.date:
    """The date n business days after start (start itself is not counted)."""
    day, added = start, 0
    while added < n:
        day += dt.timedelta(days=1)
        if is_business_day(day, holidays):
            added += 1
    return day


def business_days_between(start: dt.date, end: dt.date, holidays: set[dt.date]) -> int:
    """Business days after start up to and including end. Negative when end is before start."""
    if end == start:
        return 0
    sign = 1 if end > start else -1
    a, b = (start, end) if sign == 1 else (end, start)
    count, day = 0, a
    while day < b:
        day += dt.timedelta(days=1)
        if is_business_day(day, holidays):
            count += 1
    return sign * count


@dataclass(frozen=True)
class PayBy:
    trigger_date: dt.date        # day both conditions were met; the clock starts the day after
    regime: str                  # 'current' or '2027'
    term_label: str
    pay_by: dt.date


def pay_by(trigger_date: dt.date, holidays: set[dt.date], einvoice: bool = False, regime: str | None = None) -> PayBy:
    """Pay-by date under RMG 417. The regime defaults to the terms in force on the trigger date."""
    regime = regime or ("2027" if trigger_date + dt.timedelta(days=1) >= TERMS_CHANGE_DATE else "current")
    if regime == "2027":
        return PayBy(trigger_date, regime, f"{TERM_BUSINESS_DAYS_2027} business days",
                     add_business_days(trigger_date, TERM_BUSINESS_DAYS_2027, holidays))
    days = TERM_EINVOICE_CALENDAR_DAYS if einvoice else TERM_CALENDAR_DAYS
    label = f"{days} calendar days" + (" (e-invoice)" if einvoice else "")
    return PayBy(trigger_date, regime, label, trigger_date + dt.timedelta(days=days))


def interest_accrued(amount: float, days_late: int, annual_rate: float) -> float:
    """Simple interest at the GIC annual rate for each calendar day late."""
    if days_late <= 0 or amount <= 0:
        return 0.0
    return round(amount * annual_rate / 365.0 * days_late, 2)


def interest_payable(amount: float, days_late: int, annual_rate: float) -> float:
    accrued = interest_accrued(amount, days_late, annual_rate)
    return accrued if accrued > INTEREST_PAYABLE_OVER_AUD else 0.0


# ---------------------------------------------------------------------------
# Field confidence routing
# ---------------------------------------------------------------------------
def _normalise(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", str(text or "").lower())


def value_grounded(name: str, value, cited_text: str) -> bool:
    """True when the extracted value can be found in the text it cites.

    Numbers are matched on their digits (so 11330 matches '$11,330.00'), dates on day, month and
    year in any common format, everything else on alphanumerics.
    """
    if value is None or value == "":
        return False
    text = str(cited_text or "")
    if name in NUMBER_FIELDS:
        n = money(value)
        if n is None:
            return False
        candidates = {f"{abs(n):,.2f}", f"{abs(n):.2f}", f"{abs(n):,.0f}" if abs(n) == int(abs(n)) else f"{abs(n):,.2f}"}
        flat = text.replace(" ", "")
        return any(c in flat for c in candidates)
    if name in DATE_FIELDS:
        d = parse_date(value)
        if d is None:
            return False
        t = text.lower()
        forms = [d.strftime("%d/%m/%Y"), d.strftime("%-d/%m/%Y"), d.strftime("%d.%m.%Y"), d.isoformat(),
                 f"{d.day} {d.strftime('%B').lower()} {d.year}", f"{d.day} {d.strftime('%b').lower()} {d.year}",
                 d.strftime("%d %b %Y").lower(), d.strftime("%d-%b-%Y").lower(), d.strftime("%d/%m/%y")]
        return any(f in t for f in forms)
    if name in ("supplier_abn", "recipient_abn", "bank_bsb", "bank_account"):
        return len(digits(value)) > 0 and digits(value) in digits(text)
    return _normalise(value) in _normalise(text) if _normalise(value) else False


def parse_date(value) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%d-%b-%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def type_valid(name: str, value) -> bool:
    if value is None or value == "":
        return False
    if name in NUMBER_FIELDS:
        return money(value) is not None
    if name in DATE_FIELDS:
        return parse_date(value) is not None
    if name in ("supplier_abn", "recipient_abn"):
        return len(digits(value)) == 11
    return True


def routing_confidence(name: str, value, model_confidence, cited_text: str, full_text: str = "") -> tuple[float, bool, bool]:
    """(routing score, grounded, type_valid). Missing values score 0.

    Grounding is checked in the cited region first. A value found elsewhere in the document is
    still grounded but scores a little lower, because the highlighted evidence is not where it is.
    """
    if value is None or value == "":
        return 0.0, False, False
    score = float(model_confidence if model_confidence is not None else 0.5)
    grounded = value_grounded(name, value, cited_text)
    if not grounded and full_text and value_grounded(name, value, full_text):
        grounded = True
        score *= UNCITED_PENALTY
    valid = type_valid(name, value)
    if not grounded:
        score *= UNGROUNDED_PENALTY
    if not valid:
        score *= INVALID_TYPE_PENALTY
    return round(min(max(score, 0.0), 1.0), 3), grounded, valid


# ---------------------------------------------------------------------------
# Correctly rendered checks
# ---------------------------------------------------------------------------
@dataclass
class CheckResult:
    code: str
    passed: bool | None          # None: could not be evaluated (a field it needs is missing)
    detail: str

    @property
    def meta(self) -> dict:
        return CHECKS[self.code]


@dataclass
class InvoiceContext:
    """What the AP system already knows, looked up from the quoted references."""
    po: dict | None = None                 # po_number, supplier_id, status, po_value_inc_gst, invoiced_to_date_inc_gst
    supplier: dict | None = None           # supplier_id, abn, gst_registered, einvoicing
    receipt_date: dt.date | None = None    # latest goods receipt on the PO, if any
    duplicate_of: str | None = None        # document id of an earlier document with the same number
    contract_remaining_inc_gst: float | None = None
    extra: dict = field(default_factory=dict)


def _same_entity(name: str) -> bool:
    n = _normalise(name)
    return bool(n) and (_normalise(BUYER_NAME) in n or n in {"nba", _normalise("The Nation Building Authority")})


def evaluate_invoice(fields: dict, ctx: InvoiceContext, doc_type: str = "tax_invoice") -> list[CheckResult]:
    """Run every correctly rendered check over one invoice's extracted values."""
    out: list[CheckResult] = []
    total = money(fields.get("total_inc_gst"))
    sub = money(fields.get("subtotal_ex_gst"))
    gst = money(fields.get("gst_amount"))
    gst_registered = bool((ctx.supplier or {}).get("gst_registered", True))
    credit = doc_type == "adjustment_note"

    recipient = fields.get("recipient_name") or ""
    out.append(CheckResult("addressed_to_buyer", _same_entity(recipient),
                           f"Addressed to {recipient}." if recipient else "No recipient found on the document."))

    title = str(fields.get("document_title") or "")
    if gst_registered:
        ok = ("tax invoice" in title.lower()) or ("adjustment note" in title.lower()) or (credit and "credit" in title.lower())
        out.append(CheckResult("tax_invoice_label", ok, f"Titled '{title}'." if title else "No document title found."))
    else:
        out.append(CheckResult("tax_invoice_label", True, "Supplier is not registered for GST; a tax invoice is not required."))

    abn = fields.get("supplier_abn")
    out.append(CheckResult("supplier_abn_valid", abn_valid(abn),
                           f"ABN {format_abn(abn)} {'passes' if abn_valid(abn) else 'fails'} the check-digit test." if abn else "No supplier ABN found."))
    if ctx.supplier and abn:
        match = digits(abn) == digits(ctx.supplier.get("abn"))
        out.append(CheckResult("supplier_abn_matches_vendor", match,
                               "Matches the vendor master." if match else f"Vendor master holds ABN {format_abn(ctx.supplier.get('abn'))}."))
    else:
        out.append(CheckResult("supplier_abn_matches_vendor", None, "No vendor record could be matched through the purchase order."))

    if total is not None and abs(total) >= RECIPIENT_REQUIRED_FROM_AUD and gst_registered:
        ok = _same_entity(recipient) or digits(fields.get("recipient_abn")) == digits(BUYER_ABN)
        out.append(CheckResult("recipient_identity", ok, "Recipient identity shown." if ok else "Recipient identity or ABN is not shown."))
    else:
        out.append(CheckResult("recipient_identity", True, "Not required below $1,000 or for a supplier not registered for GST."))

    po_number = fields.get("po_number")
    out.append(CheckResult("po_quoted", bool(po_number), f"Quotes {po_number}." if po_number else "No purchase order number found."))
    if po_number:
        po = ctx.po
        if po is None:
            out.append(CheckResult("po_matches", False, f"{po_number} does not match any purchase order."))
        elif po.get("status") != "open":
            out.append(CheckResult("po_matches", False, f"{po['po_number']} is {po.get('status')}."))
        elif ctx.supplier and po.get("supplier_id") != ctx.supplier.get("supplier_id"):
            out.append(CheckResult("po_matches", False, f"{po['po_number']} was raised with a different supplier."))
        else:
            out.append(CheckResult("po_matches", True, f"{po['po_number']} is open with this supplier."))
    else:
        out.append(CheckResult("po_matches", None, "No purchase order to match."))

    if sub is None or gst is None or total is None:
        out.append(CheckResult("gst_calculated", None, "Amount, GST or total could not be read."))
    else:
        # An adjustment note's amounts are credits; suppliers print the sign on some lines and not
        # others, so its arithmetic is checked on magnitudes.
        ok = gst_consistent(abs(sub), abs(gst), abs(total), gst_registered) if credit else gst_consistent(sub, gst, total, gst_registered)
        out.append(CheckResult("gst_calculated", ok,
                               f"${sub:,.2f} + GST ${gst:,.2f} = ${total:,.2f}." if ok
                               else f"${sub:,.2f} + GST ${gst:,.2f} does not reconcile to ${total:,.2f}, or GST is not 10%."))

    if ctx.po and total is not None and not credit:
        remaining = float(ctx.po.get("po_value_inc_gst", 0)) - float(ctx.po.get("invoiced_to_date_inc_gst", 0))
        ok = total <= remaining + GST_TOLERANCE_AUD
        out.append(CheckResult("within_po_value", ok,
                               f"${total:,.2f} against ${remaining:,.2f} remaining on the order." if ok
                               else f"${total:,.2f} exceeds the ${max(remaining, 0):,.2f} remaining on the order."))
    elif credit:
        out.append(CheckResult("within_po_value", True, "Adjustment notes reduce the amount owed."))
    else:
        out.append(CheckResult("within_po_value", None, "No purchase order to compare against."))

    out.append(CheckResult("not_duplicate", ctx.duplicate_of is None,
                           "No earlier invoice with this number." if ctx.duplicate_of is None
                           else f"Same invoice number as document {ctx.duplicate_of}."))

    if credit:
        out.append(CheckResult("delivery_acknowledged", True, "Not applicable to an adjustment note."))
    elif ctx.receipt_date:
        out.append(CheckResult("delivery_acknowledged", True, f"Receipted {ctx.receipt_date:%d %b %Y}."))
    else:
        out.append(CheckResult("delivery_acknowledged", False, "No goods or services receipt recorded on the order yet."))

    order = {c: i for i, c in enumerate(CHECK_ORDER)}
    return sorted(out, key=lambda r: order[r.code])


def document_status(checks: list[CheckResult], lowest_required_confidence: float, is_invoice: bool = True) -> str:
    """One status per document, in precedence order: not_invoice, exception, needs_review,
    awaiting_delivery, ready.

    A failed supplier-fault check is only an exception when the fields behind it are trustworthy;
    otherwise the document needs review first, because the "failure" may be a misread.
    """
    if not is_invoice:
        return "not_invoice"
    low = lowest_required_confidence < REVIEW_THRESHOLD
    supplier_fail = any(c.passed is False and c.meta["supplier_fault"] for c in checks)
    if low:
        return "needs_review"
    if supplier_fail:
        return "exception"
    if any(c.passed is None for c in checks if c.meta["supplier_fault"]):
        return "needs_review"
    if any(c.code == "delivery_acknowledged" and c.passed is False for c in checks):
        return "awaiting_delivery"
    return "ready"
