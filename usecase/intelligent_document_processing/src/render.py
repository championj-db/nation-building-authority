"""Render synthetic documents as PDFs (reportlab) or as scanned images (pypdfium2 + Pillow).

Five invoice layouts, because real suppliers use different accounting packages and nothing
should depend on one layout. Some suppliers send scans: the page is rasterised, slightly
rotated, softened and compressed, which is where extraction confidence starts to vary. A mailroom
"RECEIVED" stamp can land across the totals, as it does in real inboxes.

Every document carries a small "SYNTHETIC DEMONSTRATION DOCUMENT" footer.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import random

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from common import BUYER_AP_EMAIL, BUYER_NAME
from corpus import buyer_block
from rules import format_abn

W, H = A4
PALETTE = ["#143D4A", "#1B5162", "#5A3E8C", "#2F5D3A", "#7A3B2E", "#36454F", "#0F4C81", "#6B4E16"]
FOOTER = "SYNTHETIC DEMONSTRATION DOCUMENT - not a real invoice, supplier or person"


def _money(v) -> str:
    if v is None:
        return ""
    v = float(v)
    return f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"


def _date(iso: str | None, style: int) -> str:
    if not iso:
        return ""
    d = dt.date.fromisoformat(str(iso)[:10])
    return [d.strftime("%-d %B %Y"), d.strftime("%d/%m/%Y"), d.strftime("%d %b %Y"), d.strftime("%d-%b-%Y"), d.strftime("%-d %B %Y")][style % 5]


def _accent(supplier: dict) -> colors.Color:
    i = int(hashlib.sha1(supplier["supplier_id"].encode()).hexdigest(), 16) % len(PALETTE)
    return colors.HexColor(PALETTE[i])


def _footer(c: canvas.Canvas, page: int, pages: int) -> None:
    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#777777"))
    c.drawString(20 * mm, 10 * mm, FOOTER)
    c.drawRightString(W - 20 * mm, 10 * mm, f"Page {page} of {pages}")
    c.setFillColor(colors.black)


def _stamp(c: canvas.Canvas, x: float, y: float, when: dt.datetime) -> None:
    c.saveState()
    c.translate(x, y)
    c.rotate(14)
    c.setStrokeColor(colors.Color(0.75, 0.1, 0.1, alpha=0.75))
    c.setFillColor(colors.Color(0.75, 0.1, 0.1, alpha=0.75))
    c.setLineWidth(2)
    c.roundRect(0, 0, 62 * mm, 18 * mm, 3 * mm, stroke=1, fill=0)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(31 * mm, 10.5 * mm, "RECEIVED")
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(31 * mm, 4.5 * mm, f"{when:%d %b %Y}".upper() + "  NBA MAILROOM")
    c.restoreState()


def _recipient_lines(t: dict) -> list[str]:
    if t.get("recipient_name") is None:
        return []
    if t["recipient_name"] != BUYER_NAME:
        return [t["recipient_name"], "Accounts Payable", "GPO Box 9000", "Canberra ACT 2601"]
    return buyer_block()


def _meta(doc: dict, style: int) -> list[tuple[str, str]]:
    t = doc["truth"]
    rows = [("Invoice number" if doc["doc_type"] == "tax_invoice" else "Adjustment note no.", t["invoice_number"]),
            ("Invoice date" if doc["doc_type"] == "tax_invoice" else "Date", _date(t["invoice_date"], style))]
    if t.get("original_invoice_number"):
        rows.append(("Adjusts invoice", t["original_invoice_number"]))
    if t.get("po_number"):
        rows.append(("Purchase order" if style % 2 == 0 else "Your order no.", t["po_number"]))
    if t.get("contract_reference"):
        rows.append(("Contract reference", t["contract_reference"]))
    due = dt.date.fromisoformat(t["invoice_date"]) + dt.timedelta(days=30)
    rows.append(("Due date", _date(due.isoformat(), style)))
    return rows


def _title(doc: dict) -> str:
    return doc["truth"]["document_title"].upper()


def _table(c, x0, y, widths, header, rows, font=9, shade=None):
    c.setFont("Helvetica-Bold", font)
    if shade is not None:
        c.setFillColor(shade)
        c.rect(x0, y - 2.2 * mm, sum(widths), 6.5 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
    x = x0
    for w, h in zip(widths, header):
        if h in ("Qty", "Unit price", "Amount", "Rate", "Hours"):
            c.drawRightString(x + w - 2 * mm, y, h)
        else:
            c.drawString(x + 1.5 * mm, y, h)
        x += w
    c.setFillColor(colors.black)
    y -= 4 * mm
    c.setLineWidth(0.5)
    c.line(x0, y, x0 + sum(widths), y)
    y -= 5 * mm
    c.setFont("Helvetica", font)
    for r in rows:
        x = x0
        for i, (w, v) in enumerate(zip(widths, r)):
            if i == 0:
                c.drawString(x + 1.5 * mm, y, str(v)[:70])
            else:
                c.drawRightString(x + w - 2 * mm, y, str(v))
            x += w
        y -= 5.6 * mm
    c.line(x0, y + 2.5 * mm, x0 + sum(widths), y + 2.5 * mm)
    return y


def _line_rows(doc):
    return [(ln["description"], f"{ln['quantity']:g}", _money(ln["unit_price"]), _money(ln["amount"])) for ln in doc["lines"]]


def _totals(c, x_label, x_value, y, t, gst_inclusive_note=False):
    c.setFont("Helvetica", 9.5)
    if gst_inclusive_note:
        c.setFont("Helvetica-Bold", 12)
        c.drawString(x_label, y, "Amount due")
        c.drawRightString(x_value, y, _money(t["total_inc_gst"]))
        c.setFont("Helvetica", 8.5)
        c.drawString(x_label, y - 5 * mm, f"Total includes GST of {_money(t['gst_amount'])}")
        c.drawString(x_label, y - 9.5 * mm, f"Amount excluding GST {_money(t['subtotal_ex_gst'])}")
        return y - 14 * mm
    for label, v, bold in (("Subtotal (excl. GST)", t["subtotal_ex_gst"], False), ("GST", t["gst_amount"], False),
                           ("Total (incl. GST)", t["total_inc_gst"], True)):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10.5 if bold else 9.5)
        c.drawString(x_label, y, label)
        c.drawRightString(x_value, y, _money(v))
        y -= 6 * mm
    return y


def _bank(c, x, y, s, doc, size=8.5):
    t = doc["truth"]
    c.setFont("Helvetica-Bold", size)
    c.drawString(x, y, "Payment details")
    c.setFont("Helvetica", size)
    c.drawString(x, y - 4.5 * mm, f"Account name: {s['name']}")
    c.drawString(x, y - 9 * mm, f"BSB {t['bank_bsb'][:3]}-{t['bank_bsb'][3:]}   Account {t['bank_account']}")
    c.drawString(x, y - 13.5 * mm, f"Please quote invoice {t['invoice_number']} with your payment. Remittances: {s['email']}")


# ---------------------------------------------------------------------------
# Invoice layouts
# ---------------------------------------------------------------------------
def _invoice_classic(c, doc, s):
    t = doc["truth"]
    c.setFont("Helvetica-Bold", 17)
    c.drawString(20 * mm, H - 25 * mm, s["name"])
    c.setFont("Helvetica", 8.5)
    abn = f"ABN {format_abn(t['supplier_abn'])}" if t.get("supplier_abn") else ""
    c.drawString(20 * mm, H - 31 * mm, f"{abn}   {s['address_1']}, {s['address_2']}   {s['phone']}")
    c.setFont("Helvetica-Bold", 15)
    c.drawRightString(W - 20 * mm, H - 25 * mm, _title(doc))
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(20 * mm, H - 46 * mm, "Bill to")
    c.setFont("Helvetica", 9.5)
    for i, ln in enumerate(_recipient_lines(t)):
        c.drawString(20 * mm, H - 51 * mm - i * 4.8 * mm, ln)
    y = H - 46 * mm
    for k, v in _meta(doc, 0):
        c.setFont("Helvetica", 9.5)
        c.drawRightString(W - 62 * mm, y, k + ":")
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(W - 60 * mm, y, v)
        y -= 5 * mm
    y = _table(c, 20 * mm, H - 88 * mm, [100 * mm, 18 * mm, 26 * mm, 26 * mm], ["Description", "Qty", "Unit price", "Amount"], _line_rows(doc))
    y = _totals(c, 122 * mm, W - 20 * mm, y - 6 * mm, t)
    _bank(c, 20 * mm, 42 * mm, s, doc)
    return (118 * mm, y + 2 * mm)


def _invoice_banded(c, doc, s):
    t = doc["truth"]
    accent = _accent(s)
    c.setFillColor(accent)
    c.rect(0, H - 34 * mm, W, 34 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(20 * mm, H - 18 * mm, s["name"])
    c.setFont("Helvetica", 8.5)
    c.drawString(20 * mm, H - 25 * mm, f"{s['address_1']}  |  {s['address_2']}  |  {s['email']}")
    if t.get("supplier_abn"):
        c.drawString(20 * mm, H - 30 * mm, f"ABN: {format_abn(t['supplier_abn'])}")
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(20 * mm, H - 50 * mm, t["document_title"])
    box_y = H - 72 * mm
    meta = _meta(doc, 1)
    bw = (W - 40 * mm) / max(len(meta), 1)
    for i, (k, v) in enumerate(meta):
        x = 20 * mm + i * bw
        c.setStrokeColor(colors.HexColor("#BBBBBB"))
        c.rect(x, box_y, bw - 2 * mm, 14 * mm, stroke=1, fill=0)
        c.setFont("Helvetica", 7)
        c.drawString(x + 2 * mm, box_y + 9.5 * mm, k.upper())
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x + 2 * mm, box_y + 3.5 * mm, v)
    c.setStrokeColor(colors.black)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, H - 82 * mm, "INVOICE TO")
    c.setFont("Helvetica", 9)
    for i, ln in enumerate(_recipient_lines(t)):
        c.drawString(20 * mm, H - 87 * mm - i * 4.5 * mm, ln)
    y = _table(c, 20 * mm, H - 120 * mm, [100 * mm, 18 * mm, 26 * mm, 26 * mm], ["Description", "Qty", "Unit price", "Amount"],
               _line_rows(doc), shade=accent)
    y = _totals(c, 122 * mm, W - 20 * mm, y - 6 * mm, t)
    _bank(c, 20 * mm, 40 * mm, s, doc)
    return (120 * mm, y + 3 * mm)


def _invoice_letterhead(c, doc, s):
    t = doc["truth"]
    c.setFont("Times-Bold", 19)
    c.drawCentredString(W / 2, H - 22 * mm, s["name"].upper())
    c.setFont("Times-Roman", 9.5)
    c.drawCentredString(W / 2, H - 28 * mm, f"{s['address_1']}, {s['address_2']}  -  Telephone {s['phone']}")
    if t.get("supplier_abn"):
        c.drawCentredString(W / 2, H - 33 * mm, f"A.B.N. {format_abn(t['supplier_abn'])}")
    c.line(20 * mm, H - 37 * mm, W - 20 * mm, H - 37 * mm)
    c.setFont("Times-Bold", 14)
    c.drawString(20 * mm, H - 48 * mm, _title(doc))
    c.setFont("Times-Roman", 10)
    y = H - 56 * mm
    for k, v in _meta(doc, 2):
        c.drawString(20 * mm, y, f"{k}:")
        c.drawString(60 * mm, y, v)
        y -= 5 * mm
    for i, ln in enumerate(_recipient_lines(t)):
        c.drawString(120 * mm, H - 56 * mm - i * 5 * mm, ln)
    y = _table(c, 20 * mm, y - 10 * mm, [100 * mm, 18 * mm, 26 * mm, 26 * mm], ["Particulars", "Qty", "Rate", "Amount"], _line_rows(doc))
    y = _totals(c, 122 * mm, W - 20 * mm, y - 6 * mm, t)
    c.setDash(3, 3)
    c.line(15 * mm, 62 * mm, W - 15 * mm, 62 * mm)
    c.setDash()
    c.setFont("Times-Bold", 10)
    c.drawString(20 * mm, 56 * mm, "REMITTANCE ADVICE - please detach and return with payment")
    c.setFont("Times-Roman", 9.5)
    c.drawString(20 * mm, 50 * mm, f"Invoice {t['invoice_number']}     Amount {_money(t['total_inc_gst'])}")
    _bank(c, 20 * mm, 42 * mm, s, doc, size=9)
    return (120 * mm, y + 2 * mm)


def _invoice_compact(c, doc, s):
    t = doc["truth"]
    accent = _accent(s)
    c.setFillColor(accent)
    c.circle(26 * mm, H - 24 * mm, 6 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(26 * mm, H - 25.5 * mm, s["invoice_prefix"][:2])
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(35 * mm, H - 22 * mm, s["name"])
    c.setFont("Helvetica", 7.5)
    c.drawString(35 * mm, H - 27 * mm, f"{s['address_1']} {s['address_2']}")
    if t.get("supplier_abn"):
        c.drawString(35 * mm, H - 31 * mm, f"ABN {format_abn(t['supplier_abn'])}")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(W - 20 * mm, H - 22 * mm, t["document_title"])
    c.setFont("Helvetica", 8)
    y = H - 28 * mm
    for k, v in _meta(doc, 3):
        c.drawRightString(W - 20 * mm, y, f"{k}  {v}")
        y -= 4 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(20 * mm, H - 48 * mm, "Billed to")
    c.setFont("Helvetica", 8)
    for i, ln in enumerate(_recipient_lines(t)):
        c.drawString(20 * mm, H - 52 * mm - i * 3.8 * mm, ln)
    y = _table(c, 20 * mm, H - 82 * mm, [100 * mm, 18 * mm, 26 * mm, 26 * mm], ["Item", "Qty", "Unit price", "Amount"], _line_rows(doc), font=8)
    y = _totals(c, 122 * mm, W - 20 * mm, y - 8 * mm, t, gst_inclusive_note=True)
    _bank(c, 20 * mm, 36 * mm, s, doc, size=7.5)
    return (118 * mm, y + 6 * mm)


def _invoice_itemised(c, doc, s, rng):
    """Totals on page one, a timesheet on page two. Returns the stamp position on page one."""
    t = doc["truth"]
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, H - 24 * mm, s["name"])
    c.setFont("Helvetica", 8.5)
    c.drawString(20 * mm, H - 30 * mm, f"{s['address_1']}, {s['address_2']}")
    if t.get("supplier_abn"):
        c.drawString(20 * mm, H - 34.5 * mm, f"Australian Business Number {format_abn(t['supplier_abn'])}")
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(W - 20 * mm, H - 24 * mm, _title(doc))
    y = H - 50 * mm
    c.setFont("Helvetica", 9)
    for k, v in _meta(doc, 4):
        c.drawString(20 * mm, y, k)
        c.drawString(62 * mm, y, v)
        y -= 5 * mm
    for i, ln in enumerate(_recipient_lines(t)):
        c.drawString(125 * mm, H - 50 * mm - i * 4.8 * mm, ln)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y - 8 * mm, "Summary of charges (detail on page 2)")
    y = _table(c, 20 * mm, y - 16 * mm, [100 * mm, 18 * mm, 26 * mm, 26 * mm], ["Description", "Qty", "Unit price", "Amount"], _line_rows(doc))
    y = _totals(c, 122 * mm, W - 20 * mm, y - 6 * mm, t)
    _bank(c, 20 * mm, 40 * mm, s, doc)
    if doc["stamp"]:
        _stamp(c, 118 * mm, y + 2 * mm, doc["arrival_ts"])
    _footer(c, 1, 2)
    c.showPage()
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, H - 25 * mm, f"Timesheet detail - invoice {t['invoice_number']}")
    rows = []
    day = dt.date.fromisoformat(t["invoice_date"]) - dt.timedelta(days=28)
    for i in range(rng.randint(12, 22)):
        day += dt.timedelta(days=rng.choice([1, 1, 2]))
        rows.append((f"{day:%a %d %b}  {rng.choice(['Analysis', 'Stakeholder meeting', 'Drafting', 'Review', 'Site visit', 'Reporting'])}",
                     f"{rng.choice([2, 3.5, 4, 6, 7.5, 8]):g}", "", ""))
    _table(c, 20 * mm, H - 36 * mm, [120 * mm, 20 * mm, 15 * mm, 15 * mm], ["Date and activity", "Hours", "", ""], rows, font=8.5)


def render_invoice(doc: dict, supplier: dict, rng: random.Random) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"{doc['truth']['document_title']} {doc['truth']['invoice_number']}")
    c.setAuthor(supplier["name"])
    template = int(doc.get("template") or supplier["template"]) % 5
    if template == 4:
        _invoice_itemised(c, doc, supplier, rng)  # stamps page one itself
        _footer(c, 2, 2)
    else:
        stamp_at = [_invoice_classic, _invoice_banded, _invoice_letterhead, _invoice_compact][template](c, doc, supplier)
        if doc["stamp"]:
            _stamp(c, stamp_at[0], stamp_at[1], doc["arrival_ts"])
        _footer(c, 1, 1)
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Statements, letters and quotes
# ---------------------------------------------------------------------------
def render_statement(doc: dict, supplier: dict, invoices: list[dict]) -> bytes:
    t = doc["truth"]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Statement {supplier['name']}")
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, H - 24 * mm, supplier["name"])
    c.setFont("Helvetica", 8.5)
    c.drawString(20 * mm, H - 30 * mm, f"ABN {format_abn(supplier['abn'])}  {supplier['address_1']}, {supplier['address_2']}")
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(W - 20 * mm, H - 24 * mm, "STATEMENT OF ACCOUNT")
    c.setFont("Helvetica", 9.5)
    c.drawRightString(W - 20 * mm, H - 31 * mm, f"Statement date: {_date(t['statement_date'], 0)}")
    for i, ln in enumerate(buyer_block()):
        c.drawString(20 * mm, H - 46 * mm - i * 4.8 * mm, ln)
    rows = []
    for d in invoices:
        rows.append((f"{_date(d['truth']['invoice_date'], 1)}  Invoice {d['truth']['invoice_number']}", "", "", _money(abs(d["truth"]["total_inc_gst"]))))
    y = _table(c, 20 * mm, H - 84 * mm, [110 * mm, 15 * mm, 15 * mm, 30 * mm], ["Transaction", "", "", "Amount"], rows or [("No open invoices", "", "", "")])
    c.setFont("Helvetica-Bold", 11)
    c.drawString(110 * mm, y - 8 * mm, "Balance due")
    c.drawRightString(W - 20 * mm, y - 8 * mm, _money(t["balance_due"]))
    c.setFont("Helvetica", 9.5)
    c.drawString(110 * mm, y - 14 * mm, "Overdue")
    c.drawRightString(W - 20 * mm, y - 14 * mm, _money(t["overdue_amount"]))
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, 30 * mm, "This statement is not a tax invoice. Please contact us if your records differ.")
    _footer(c, 1, 1)
    c.save()
    return buf.getvalue()


LETTERS = {
    "payment_query": [
        "We are writing regarding {refs}, which our records show as unpaid. Could you please advise the expected payment date? We understand Commonwealth entities pay within the policy term once an invoice is accepted.",
        "Our accounts team has not yet received payment for {refs}. Please let us know whether anything further is needed from us, or confirm when payment will be made.",
    ],
    "bank_details_change": [
        "Please be advised that our banking details have changed, effective immediately. All future payments, including {refs}, should be made to BSB {bsb} account {acct}. Please update your records.",
        "Due to a change of bank, please direct payment of {refs} and all future invoices to our new account: BSB {bsb}, account number {acct}. Our old account will be closed this week.",
    ],
    "delivery_dispute": [
        "We note your contract manager has not yet signed off delivery for the work invoiced under {refs}. The services were completed as scheduled. Please confirm acceptance so the invoice can be processed.",
        "We were advised that delivery under {refs} is disputed. We would welcome a meeting with the contract manager to resolve the outstanding items.",
    ],
    "remittance_request": [
        "Could you please send remittance advice for {refs}? We are reconciling our accounts for the month and cannot match the payments received.",
    ],
}


def render_letter(doc: dict, supplier: dict, rng: random.Random) -> bytes:
    t = doc["truth"]
    nums = t["referenced_invoice_numbers"]
    refs = (f"invoice {nums[0]}" if len(nums) == 1 else f"invoices {' and '.join(nums)}") if nums else "our recent invoice"
    body = rng.choice(LETTERS[t["intent"]]).format(refs=refs, bsb=f"{(t['new_bank_bsb'] or '')[:3]}-{(t['new_bank_bsb'] or '')[3:]}", acct=t["new_bank_account"] or "")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20 * mm, H - 24 * mm, supplier["name"])
    c.setFont("Helvetica", 8.5)
    c.drawString(20 * mm, H - 30 * mm, f"{supplier['address_1']}, {supplier['address_2']}  {supplier['phone']}")
    c.setFont("Helvetica", 10.5)
    c.drawString(20 * mm, H - 46 * mm, _date(t["letter_date"], 0))
    for i, ln in enumerate([BUYER_NAME, "Accounts Payable", BUYER_AP_EMAIL]):
        c.drawString(20 * mm, H - 56 * mm - i * 5 * mm, ln)
    c.drawString(20 * mm, H - 78 * mm, "Dear Accounts Payable team,")
    text = c.beginText(20 * mm, H - 88 * mm)
    text.setFont("Helvetica", 10.5)
    text.setLeading(15)
    line = ""
    for word in body.split():
        if len(line) + len(word) > 88:
            text.textLine(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    text.textLine(line)
    c.drawText(text)
    c.drawString(20 * mm, H - 150 * mm, "Kind regards,")
    c.drawString(20 * mm, H - 165 * mm, rng.choice(["Accounts Receivable", "Finance Manager", "Director"]))
    c.drawString(20 * mm, H - 170 * mm, supplier["name"])
    _footer(c, 1, 1)
    c.save()
    return buf.getvalue()


def render_quote(doc: dict, supplier: dict) -> bytes:
    t = doc["truth"]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, H - 24 * mm, supplier["name"])
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(W - 20 * mm, H - 24 * mm, "QUOTATION")
    c.setFont("Helvetica", 9.5)
    c.drawRightString(W - 20 * mm, H - 31 * mm, f"Quote {t['quote_number']}  -  {_date(t['quote_date'], 2)}")
    c.drawString(20 * mm, H - 46 * mm, f"Prepared for {BUYER_NAME}")
    c.drawString(20 * mm, H - 56 * mm, f"Scope: {t['description']}")
    c.drawString(20 * mm, H - 66 * mm, f"Estimated price (incl. GST): {_money(t['total_inc_gst'])}")
    c.drawString(20 * mm, H - 76 * mm, f"This quotation is valid for {t['valid_days']} days and is not a request for payment.")
    _footer(c, 1, 1)
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
def scan(pdf_bytes: bytes, rng: random.Random, dpi: int = 140) -> bytes:
    """Rasterise page one and degrade it like a desktop scanner: greyscale, a small skew, a little
    blur and noise, and JPEG compression. Multi-page documents keep only page one when scanned."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    pdf = pdfium.PdfDocument(pdf_bytes)
    page = pdf[0]
    img = page.render(scale=dpi / 72).to_pil().convert("L")
    angle = rng.uniform(-1.4, 1.4)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=245)
    img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 0.8)))
    noise = Image.effect_noise(img.size, rng.uniform(8, 16))
    img = Image.blend(img, noise, 0.06)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=rng.randint(45, 68))
    return out.getvalue()
