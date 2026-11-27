"""Synthetic supplier inbox built on real AusTender contracts.

The notebooks generate the tabular skeletons with dbldatagen (supplier attributes, document
specs) and hand plain dict rows to the functions here. These functions add what dbldatagen
cannot express: purchase orders that respect each contract's value, invoice series that stay
within each order, ground-truth field values, injected defects, duplicates that point at a real
earlier invoice, statements that list the supplier's own invoices, letters that refer to them,
and a simulated processing history for documents older than the live queue window.

Pure Python and deterministic for a given seed. Nothing here touches Spark or the network.
"""

from __future__ import annotations

import datetime as dt
import random
from dataclasses import dataclass, field

from common import BUYER_ABN, BUYER_ADDRESS, BUYER_NAME, INVOICE_TYPES
from rules import (
    add_business_days,
    business_days_between,
    corrupt_abn,
    format_abn,
    interest_payable,
    is_business_day,
    make_abn,
    pay_by,
)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
NAME_WORDS = [
    "Kestrel", "Ironbark", "Coolabah", "Saltbush", "Riverbend", "Tasman", "Harbourline", "Granite",
    "Bluegum", "Mallee", "Stringybark", "Brolga", "Jabiru", "Quandong", "Lyrebird", "Spinifex",
    "Paperbark", "Currawong", "Bilby", "Wombat", "Ochre", "Basalt", "Sandstone", "Mulga",
    "Corella", "Pardalote", "Banksia", "Grevillea", "Yarran", "Boobook", "Galah", "Dunnart",
]
LANDFORMS = ["Ridge", "Creek", "Point", "Vale", "Hill", "Plains", "Bay", "Gully", "Range", "Flat", "Reach", "Downs"]
ENTITY_FORMS = ["Pty Ltd", "Pty Ltd", "Pty Ltd", "Pty Ltd", "Ltd", "Partners", "& Co"]

# UNSPSC segment (first two digits) -> (segment name, business words)
SEGMENTS = {
    "43": ("Information technology and telecommunications", ["Systems", "Technology", "Digital"]),
    "44": ("Office equipment and supplies", ["Supplies", "Office"]),
    "46": ("Defence, security and safety equipment", ["Protective", "Safety"]),
    "55": ("Published products", ["Print", "Publishing"]),
    "70": ("Environmental services", ["Environmental", "Land Management"]),
    "72": ("Building and construction services", ["Constructions", "Building", "Civil"]),
    "76": ("Industrial cleaning services", ["Facility Services", "Cleaning"]),
    "77": ("Environmental services", ["Environmental", "Ecology"]),
    "78": ("Transportation, storage and mail services", ["Logistics", "Freight"]),
    "80": ("Management and business professionals", ["Consulting", "Advisory", "Partners"]),
    "81": ("Engineering, research and technology services", ["Engineering", "Technical", "Digital"]),
    "82": ("Editorial, design, graphic and fine art services", ["Creative", "Design", "Communications"]),
    "83": ("Public utilities and public sector related services", ["Utilities", "Services"]),
    "84": ("Financial and insurance services", ["Financial", "Advisory"]),
    "85": ("Healthcare services", ["Health", "Medical"]),
    "86": ("Education and training services", ["Training", "Learning"]),
    "90": ("Travel, food, lodging and entertainment services", ["Travel", "Events"]),
    "92": ("National defence, public order and security services", ["Security", "Protective Services"]),
    "93": ("Politics and civic affairs services", ["Advisory", "Policy"]),
}
DEFAULT_SEGMENT = ("Other goods and services", ["Services", "Group"])

LINE_PATTERNS = {
    "80": ["Professional services - {d}", "Workshop facilitation and reporting", "Project management - {m}", "Disbursements - travel"],
    "81": ["Engineering services - {d}", "Technical advice - {m}", "Site inspection and report", "Design review"],
    "43": ["Software licence subscription - {m}", "Managed service fee - {m}", "Support hours", "Hardware - {d}"],
    "72": ["Progress claim - {d}", "Variation - minor works", "Site establishment", "Materials"],
    "78": ["Freight and handling - {m}", "Storage - {m}", "Courier services"],
    "86": ["Training delivery - {d}", "Course materials", "Assessment and certification"],
    "82": ["Design and production - {d}", "Copywriting", "Photography and image licensing"],
    "84": ["Advisory services - {d}", "Audit fieldwork", "Financial modelling"],
    "92": ["Security services - {m}", "Guarding hours", "Security assessment"],
}
DEFAULT_LINES = ["Services rendered - {d}", "Services - {m}", "Additional services"]

STREETS = [
    ("Marcus Clarke Street", "Canberra", "ACT", "2601"), ("Northbourne Avenue", "Braddon", "ACT", "2612"),
    ("Collins Street", "Melbourne", "VIC", "3000"), ("George Street", "Sydney", "NSW", "2000"),
    ("Adelaide Street", "Brisbane", "QLD", "4000"), ("Hay Street", "Perth", "WA", "6000"),
    ("Grenfell Street", "Adelaide", "SA", "5000"), ("Macquarie Street", "Hobart", "TAS", "7000"),
    ("Mitchell Street", "Darwin", "NT", "0800"), ("Hunter Street", "Newcastle", "NSW", "2300"),
    ("Flinders Street", "Townsville", "QLD", "4810"), ("Lonsdale Street", "Dandenong", "VIC", "3175"),
    ("Brisbane Avenue", "Barton", "ACT", "2600"), ("Kent Street", "Sydney", "NSW", "2000"),
    ("Wickham Street", "Fortitude Valley", "QLD", "4006"), ("Murray Street", "Perth", "WA", "6000"),
]
OFFICERS = ["Priya Natarajan", "Tom Whitcombe", "Mei Lin Chau", "Daniel Okafor", "Sarah Kinnear", "Luca Bianchi"]
CONTRACT_MANAGERS = ["J. Hollis", "R. Abara", "K. Fitzgerald", "S. Nguyen", "M. Tremain", "A. Rahman", "L. Doherty"]

# Injected invoice defects. supplier-side defects make the invoice not correctly rendered.
DEFECTS = {
    "none": "Correctly rendered",
    "missing_po": "No purchase order quoted",
    "wrong_po": "Purchase order does not match",
    "gst_error": "GST miscalculated",
    "invalid_abn": "ABN fails check digits",
    "abn_mismatch": "ABN differs from vendor master",
    "wrong_recipient": "Addressed to another entity",
    "missing_recipient": "Recipient not shown (>= $1,000)",
    "over_po_value": "Exceeds remaining order value",
    "duplicate": "Duplicate of an earlier invoice",
    "not_tax_invoice": "Not identified as a tax invoice",
    "no_receipt": "Delivery not yet acknowledged",
}
# Expected check failing for each defect (used to score the pipeline against ground truth).
DEFECT_CHECK = {
    "missing_po": "po_quoted", "wrong_po": "po_matches", "gst_error": "gst_calculated",
    "invalid_abn": "supplier_abn_valid", "abn_mismatch": "supplier_abn_matches_vendor",
    "wrong_recipient": "addressed_to_buyer", "missing_recipient": "recipient_identity",
    "over_po_value": "within_po_value", "duplicate": "not_duplicate",
    "not_tax_invoice": "tax_invoice_label", "no_receipt": "delivery_acknowledged",
}
OTHER_ENTITIES = ["Department of Regional Development", "Infrastructure Delivery Office", "National Projects Agency"]

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


@dataclass
class World:
    contracts: list[dict]
    suppliers: list[dict]
    purchase_orders: list[dict] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)
    documents: list[dict] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Contracts and suppliers
# ---------------------------------------------------------------------------
def segment_of(unspsc: str | None) -> tuple[str, list[str]]:
    return SEGMENTS.get(str(unspsc or "")[:2], DEFAULT_SEGMENT)


def pseudonymise_contracts(notices: list[dict], rng: random.Random, limit: int) -> list[dict]:
    """Keep the public substance of a contract notice and drop everything that identifies it.

    notices: dicts with description, unspsc, value, start_date, end_date, procurement_method,
    supplier_key (an opaque grouping key used only here to keep one supplier per real supplier).
    Descriptions that name their supplier are dropped rather than edited.
    """
    keep = []
    for n in notices:
        desc = " ".join(str(n.get("description") or "").split())
        if len(desc) < 12 or len(desc) > 120:
            continue
        supplier_tokens = {t.lower() for t in str(n.get("supplier_name") or "").replace(",", " ").split() if len(t) > 3}
        if supplier_tokens & {t.lower().strip(".,()") for t in desc.split()}:
            continue
        value = float(n.get("value") or 0)
        if not 20_000 <= value <= 3_000_000:
            continue
        keep.append({**n, "description": desc, "value": value})
    rng.shuffle(keep)
    keep = keep[:limit]
    out = []
    for i, n in enumerate(sorted(keep, key=lambda x: (x["start_date"], x["description"]))):
        seg_name, _ = segment_of(n.get("unspsc"))
        out.append({
            "contract_id": f"NBA-C-{10400 + i}",
            "description": n["description"],
            "unspsc": str(n.get("unspsc") or ""),
            "category": seg_name,
            "value_inc_gst": round(n["value"], 2),
            "start_date": n["start_date"],
            "end_date": n["end_date"],
            "procurement_method": n.get("procurement_method") or "Open tender",
            "supplier_key": n.get("supplier_key"),
            "contract_manager": rng.choice(CONTRACT_MANAGERS),
        })
    return out


def build_suppliers(contracts: list[dict], attrs: list[dict], rng: random.Random) -> list[dict]:
    """One synthetic supplier per distinct real supplier key, named for its main category.

    attrs: dbldatagen rows (at least as many as distinct supplier keys) with columns
    word_a, word_b, form, street_no, street_idx, phone_suffix, bsb, account, gst_registered,
    einvoicing, template, scan_rate.
    """
    keys = []
    for c in contracts:
        if c["supplier_key"] not in keys:
            keys.append(c["supplier_key"])
    used_names = set()
    suppliers = []
    for i, key in enumerate(keys):
        a = attrs[i % len(attrs)]
        main = next(c for c in contracts if c["supplier_key"] == key)
        _, words = segment_of(main["unspsc"])
        name = None
        for attempt in range(20):
            w1 = a["word_a"] if attempt == 0 else rng.choice(NAME_WORDS)
            w2 = a["word_b"] if attempt == 0 else rng.choice(LANDFORMS)
            word = words[(i + attempt) % len(words)]
            form = a["form"] if a["form"].split()[0] != word.split()[-1] else "Pty Ltd"  # no "Partners Partners"
            candidate = f"{w1} {w2} {word} {form}"
            if candidate not in used_names:
                name = candidate
                break
        used_names.add(name)
        street, suburb, state, postcode = STREETS[int(a["street_idx"]) % len(STREETS)]
        slug = "".join(ch for ch in name.split()[0] + name.split()[1] if ch.isalpha()).lower()
        prefix = "".join(w[0] for w in name.split()[:3]).upper()
        suppliers.append({
            "supplier_id": f"V{20000 + i}",
            "name": name,
            "abn": make_abn(rng),
            "gst_registered": bool(a["gst_registered"]),
            "einvoicing": bool(a["einvoicing"]),
            "address_1": f"{int(a['street_no'])} {street}",
            "address_2": f"{suburb} {state} {postcode}",
            "email": f"accounts@{slug}.example.com.au",
            "phone": f"(02) 6{int(a['phone_suffix']):07d}"[:14],
            "bsb": f"{int(a['bsb']):06d}",
            "account": f"{int(a['account']):08d}",
            "template": int(a["template"]),
            "scan_rate": float(a["scan_rate"]),
            "invoice_prefix": prefix,
            "invoice_seq": 1000 + rng.randint(0, 8000),
            "supplier_key": key,
        })
    for c in contracts:
        c["supplier_id"] = next(s["supplier_id"] for s in suppliers if s["supplier_key"] == c["supplier_key"])
    return suppliers


def build_purchase_orders(contracts: list[dict], as_of: dt.date, rng: random.Random) -> list[dict]:
    pos = []
    seq = 4500180000 + rng.randint(0, 9999)
    for c in contracts:
        n = 1 if c["value_inc_gst"] < 150_000 else rng.choice([1, 2, 2, 3])
        remaining = c["value_inc_gst"]
        for k in range(n):
            share = remaining if k == n - 1 else round(remaining * rng.uniform(0.3, 0.6), 2)
            remaining -= share
            seq += rng.randint(3, 400)
            raised = as_of - dt.timedelta(days=rng.randint(70, 240))
            pos.append({
                "po_number": f"PO-{seq}",
                "contract_id": c["contract_id"],
                "supplier_id": c["supplier_id"],
                "raised_date": raised,
                "po_value_inc_gst": round(share, 2),
                "status": "open",
                "description": c["description"],
                "cost_centre": f"CC-{rng.choice([1140, 1210, 2305, 3120, 4410, 5120])}",
                "contract_manager": c["contract_manager"],
            })
    # A handful of orders were closed after their last invoice; quoting one is a wrong_po defect.
    for po in rng.sample(pos, k=max(1, len(pos) // 25)):
        po["status"] = "closed"
    return pos


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def _arrival(as_of: dt.date, bd_offset: int, hour: float, holidays: set[dt.date], now: dt.datetime | None = None) -> dt.datetime:
    day = as_of
    back = 0
    while back < bd_offset:
        day -= dt.timedelta(days=1)
        if is_business_day(day, holidays):
            back += 1
    while bd_offset > 0 and not is_business_day(day, holidays):
        day -= dt.timedelta(days=1)  # mail from earlier days arrived on a business day; today's may not
    h = int(hour)
    m = int((hour - h) * 60)
    when = dt.datetime.combine(day, dt.time(h, m))
    if now is not None and when > now:  # today's mail cannot have arrived after the run
        when = now - dt.timedelta(minutes=int((hour * 60) % 120) + 1)
    return when


def _lines(po: dict, amount_ex: float, when: dt.date, rng: random.Random) -> list[dict]:
    seg = str(po.get("unspsc") or "")[:2]
    patterns = LINE_PATTERNS.get(seg, DEFAULT_LINES)
    n = rng.choice([1, 1, 2, 2, 3])
    shares = [rng.uniform(0.2, 1.0) for _ in range(n)]
    total = sum(shares)
    lines, running = [], 0.0
    desc = po["description"][:60]
    for i, s in enumerate(shares):
        amount = round(amount_ex - running, 2) if i == n - 1 else round(amount_ex * s / total, 2)
        running += amount
        qty = rng.choice([1, 1, 1, 2, 4, 5, 8, 10, 12]) if amount > 400 else 1
        unit = round(amount / qty, 2)
        amount = round(unit * qty, 2)
        text = patterns[i % len(patterns)].format(d=desc, m=f"{MONTHS[when.month - 1]} {when.year}")
        lines.append({"description": text, "quantity": qty, "unit_price": unit, "amount": amount})
    return lines


def _invoice_number(s: dict) -> str:
    s["invoice_seq"] += 1
    return f"{s['invoice_prefix']}-{s['invoice_seq']}"


def build_documents(world: World, specs: list[dict], as_of: dt.date, holidays: set[dt.date],
                    rng: random.Random, live_window_bd: int, start_doc_no: int = 1, batch_id: str = "seed",
                    now: dt.datetime | None = None) -> None:
    """Turn dbldatagen document specs into concrete documents with ground truth.

    specs: rows with doc_type, defect, scanned, stamp, bd_offset, hour, channel.
    Invoices are drawn against open purchase orders; each order's invoices stay within its value
    unless the spec injects over_po_value.
    """
    sup = {s["supplier_id"]: s for s in world.suppliers}
    contracts = {c["contract_id"]: c for c in world.contracts}
    for po in world.purchase_orders:
        po.setdefault("unspsc", contracts[po["contract_id"]]["unspsc"])
        po.setdefault("_billed", float(po.get("invoiced_to_date_inc_gst", 0.0)))
    open_pos = [p for p in world.purchase_orders if p["status"] == "open"]
    closed_pos = [p for p in world.purchase_orders if p["status"] == "closed"]
    prior_invoices = [d for d in world.documents if d["doc_type"] == "tax_invoice" and d["defect"] != "duplicate"]

    doc_no = start_doc_no
    # Oldest first, so duplicates and statements can refer back to earlier invoices.
    for spec in sorted(specs, key=lambda r: (-int(r["bd_offset"]), float(r["hour"]))):
        arrival = _arrival(as_of, int(spec["bd_offset"]), float(spec["hour"]), holidays, now)
        doc_type = spec["doc_type"]
        defect = spec["defect"] if doc_type == "tax_invoice" else "none"
        if defect == "duplicate" and not prior_invoices:
            defect = "none"  # nothing earlier to duplicate yet
        doc = {
            "doc_id": f"DOC-{doc_no:06d}", "doc_type": doc_type, "defect": defect,
            "arrival_ts": arrival, "channel": spec["channel"], "batch_id": batch_id,
            "scanned": bool(spec["scanned"]), "stamp": bool(spec["stamp"]),
            "live": int(spec["bd_offset"]) < live_window_bd, "truth": {}, "lines": [], "related_doc_id": None,
        }
        doc_no += 1

        if doc_type == "tax_invoice" and defect == "duplicate" and prior_invoices:
            original = rng.choice(prior_invoices[-60:])
            doc.update({k: original[k] for k in ("supplier_id", "po_number", "lines", "template")})
            doc["truth"] = dict(original["truth"])
            doc["related_doc_id"] = original["doc_id"]
            doc["truth"]["invoice_date"] = original["truth"]["invoice_date"]
            doc["scanned"] = not original["scanned"] if rng.random() < 0.5 else original["scanned"]
        elif doc_type in INVOICE_TYPES:
            pool = open_pos
            po = rng.choice(pool)
            if defect == "wrong_po" and rng.random() < 0.5 and closed_pos:
                quoted = rng.choice(closed_pos)["po_number"]
            elif defect == "wrong_po":
                quoted = f"PO-{int(po['po_number'][3:]) + rng.randint(11, 97)}"
            else:
                quoted = po["po_number"]
            s = sup[po["supplier_id"]]
            remaining = po["po_value_inc_gst"] - po["_billed"]
            if doc_type == "adjustment_note":
                total = -round(rng.uniform(150, 4000), 2)
            elif defect == "over_po_value":
                total = round(max(remaining, 0) + po["po_value_inc_gst"] * rng.uniform(0.08, 0.25), 2)
            else:
                cap = max(min(remaining * 0.45, po["po_value_inc_gst"] * 0.22), 0)
                if cap < 600:  # this order is nearly spent; bill a smaller amount
                    cap = max(remaining * 0.9, 0)
                total = round(rng.uniform(0.35, 1.0) * cap, 2) if cap > 0 else 0
                if total < 250 and remaining > 1000:
                    total = round(min(remaining * 0.3, 800 + rng.uniform(0, 600)), 2)
                if rng.random() < 0.08:  # small invoices, below the recipient-identity threshold
                    total = round(rng.uniform(180, 990), 2)
            gst_reg = s["gst_registered"]
            sub = round(total / 1.1, 2) if gst_reg else total
            gst = round(total - sub, 2) if gst_reg else 0.0
            invoice_date = (arrival.date() - dt.timedelta(days=rng.choice([0, 1, 1, 2, 3, 6, 9])))
            lines = _lines(po, abs(sub), invoice_date, rng)
            sub = round(sum(ln["amount"] for ln in lines), 2) * (-1 if total < 0 else 1)
            gst = round(sub * 0.1, 2) if gst_reg else 0.0
            total = round(sub + gst, 2)
            if defect == "gst_error":
                gst = round(gst * rng.choice([1.5, 0.5, 1.1]) + rng.choice([0, 12.5, -9.0]), 2)
                total = round(sub + gst + rng.choice([0, 0, 25.0]), 2)
            truth = {
                "document_title": "Adjustment note" if doc_type == "adjustment_note" else ("Invoice" if defect == "not_tax_invoice" or not gst_reg else "Tax invoice"),
                "supplier_name": s["name"],
                "supplier_abn": s["abn"],
                "recipient_name": BUYER_NAME,
                "recipient_abn": BUYER_ABN,
                "invoice_number": _invoice_number(s),
                "original_invoice_number": None,
                "invoice_date": invoice_date.isoformat(),
                "po_number": quoted,
                "contract_reference": po["contract_id"] if rng.random() < 0.6 else None,
                "subtotal_ex_gst": sub, "gst_amount": gst, "total_inc_gst": total,
                "bank_bsb": s["bsb"], "bank_account": s["account"],
            }
            if defect == "missing_po":
                truth["po_number"] = None
            if defect == "invalid_abn":
                truth["supplier_abn"] = corrupt_abn(s["abn"], rng)
            if defect == "abn_mismatch":
                truth["supplier_abn"] = make_abn(rng)
            if defect == "wrong_recipient":
                truth["recipient_name"] = rng.choice(OTHER_ENTITIES)
                truth["recipient_abn"] = None
            if defect == "missing_recipient":
                truth["recipient_name"] = None
                truth["recipient_abn"] = None
                if abs(truth["total_inc_gst"]) < 1000:
                    scale = 1000 / max(abs(truth["total_inc_gst"]), 1) + 0.4
                    for ln in lines:
                        ln["unit_price"] = round(ln["unit_price"] * scale, 2)
                        ln["amount"] = round(ln["unit_price"] * ln["quantity"], 2)
                    truth["subtotal_ex_gst"] = round(sum(ln["amount"] for ln in lines), 2)
                    truth["gst_amount"] = round(truth["subtotal_ex_gst"] * 0.1, 2) if gst_reg else 0.0
                    truth["total_inc_gst"] = round(truth["subtotal_ex_gst"] + truth["gst_amount"], 2)
            if doc_type == "adjustment_note":
                earlier = [d for d in prior_invoices if d["supplier_id"] == s["supplier_id"]]
                if earlier:
                    ref = rng.choice(earlier)
                    truth["original_invoice_number"] = ref["truth"]["invoice_number"]
                    truth["po_number"] = ref["truth"]["po_number"] or quoted
                    doc["related_doc_id"] = ref["doc_id"]
            if doc_type == "tax_invoice" and defect in ("none", "no_receipt"):  # what AP will actually accept
                po["_billed"] += truth["total_inc_gst"]
            doc.update({"supplier_id": s["supplier_id"], "po_number": po["po_number"], "lines": lines,
                        "template": s["template"], "truth": truth})
            if doc_type == "tax_invoice":
                prior_invoices.append(doc)
        elif doc_type == "supplier_statement":
            s = rng.choice(world.suppliers)
            theirs = [d for d in prior_invoices if d["supplier_id"] == s["supplier_id"]][-6:]
            balance = round(sum(abs(d["truth"]["total_inc_gst"] or 0) for d in theirs), 2)
            overdue = round(sum(abs(d["truth"]["total_inc_gst"] or 0) for d in theirs[:max(len(theirs) - 2, 0)]) * rng.choice([0, 0, 1]), 2)
            doc.update({"supplier_id": s["supplier_id"], "template": s["template"], "related_invoices": [d["doc_id"] for d in theirs],
                        "truth": {"supplier_name": s["name"], "statement_date": arrival.date().isoformat(),
                                  "balance_due": balance, "overdue_amount": overdue,
                                  "invoice_numbers": [d["truth"]["invoice_number"] for d in theirs]}})
        elif doc_type == "correspondence":
            s = rng.choice(world.suppliers)
            theirs = [d for d in prior_invoices if d["supplier_id"] == s["supplier_id"]][-3:]
            intent = rng.choices(["payment_query", "bank_details_change", "delivery_dispute", "remittance_request"], [5, 2, 2, 1])[0]
            refs = [d["truth"]["invoice_number"] for d in theirs[-(1 if intent != "remittance_request" else 2):]] if theirs else []
            truth = {"supplier_name": s["name"], "letter_date": arrival.date().isoformat(), "intent": intent,
                     "referenced_invoice_numbers": refs, "new_bank_bsb": None, "new_bank_account": None}
            if intent == "bank_details_change":
                truth["new_bank_bsb"] = f"{rng.randint(10000, 999999):06d}"
                truth["new_bank_account"] = f"{rng.randint(10000000, 99999999)}"
            doc.update({"supplier_id": s["supplier_id"], "template": s["template"], "truth": truth,
                        "related_invoices": [d["doc_id"] for d in theirs if d["truth"]["invoice_number"] in refs]})
        else:  # quote
            c = rng.choice(world.contracts)
            s = sup[c["supplier_id"]]
            amount = round(rng.uniform(4000, 60000), 2)
            doc.update({"supplier_id": s["supplier_id"], "template": s["template"],
                        "truth": {"supplier_name": s["name"], "quote_number": f"Q-{rng.randint(1000, 9999)}",
                                  "quote_date": arrival.date().isoformat(), "total_inc_gst": amount,
                                  "valid_days": rng.choice([30, 60, 90]), "description": c["description"]}})
        # Peppol e-invoices only come from suppliers registered for e-invoicing with the Authority.
        einvoicer = bool(sup.get(doc.get("supplier_id"), {}).get("einvoicing"))
        if doc["channel"] == "peppol" and not einvoicer:
            doc["channel"] = "email"
        elif einvoicer and doc_type in INVOICE_TYPES and rng.random() < 0.7:
            doc["channel"] = "peppol"
        ext = "jpg" if doc["scanned"] else "pdf"
        label = {"tax_invoice": "Invoice", "adjustment_note": "AdjustmentNote", "supplier_statement": "Statement",
                 "correspondence": "Letter", "quote": "Quote"}[doc_type]
        ref = doc["truth"].get("invoice_number") or doc["truth"].get("quote_number") or arrival.strftime("%Y%m%d")
        doc["attachment_name"] = f"{label}_{ref}.{ext}" if not doc["scanned"] else f"scan_{doc_no:05d}.{ext}"
        doc["rel_path"] = f"inbox/{arrival:%Y/%m/%d}/{doc['doc_id']}_{doc['attachment_name']}"
        world.documents.append(doc)


# ---------------------------------------------------------------------------
# Receipts and simulated history
# ---------------------------------------------------------------------------
def build_receipts(world: World, holidays: set[dt.date], rng: random.Random, as_of: dt.date) -> None:
    """Delivery acknowledgements. Services are usually receipted before or soon after the invoice
    arrives; a no_receipt defect means nothing is recorded yet (or, in history, it came late)."""
    n = len(world.receipts)
    for d in world.documents:
        if d["doc_type"] != "tax_invoice" or d["defect"] == "duplicate" or d.get("po_number") is None:
            continue
        arrived = d["arrival_ts"].date()
        if d["defect"] == "no_receipt":
            if d["live"]:
                continue
            when = add_business_days(arrived, rng.randint(3, 9), holidays)
            if when > as_of:
                continue
        else:
            when = arrived - dt.timedelta(days=rng.choice([1, 2, 4, 7, 12, 20]))
            if rng.random() < 0.15:
                when = add_business_days(arrived, rng.randint(1, 2), holidays)
                if when > as_of:
                    when = arrived
        n += 1
        world.receipts.append({"receipt_id": f"GR-{70000 + n}", "po_number": d["po_number"], "doc_id": d["doc_id"],
                               "amount_inc_gst": round(float(d["truth"]["total_inc_gst"]), 2),
                               "receipted_date": when, "receipted_by": rng.choice(CONTRACT_MANAGERS)})


def build_history(world: World, holidays: set[dt.date], rng: random.Random, gic_rate: float, as_of: dt.date | None = None) -> None:
    """Simulated AP decisions for documents older than the live window.

    Correctly rendered invoices are accepted after a handling lag and paid in a payment run; the
    lag distribution has a tail, so some breach today's 20-day term and more would breach the
    2027 10-business-day term. Defective invoices are returned. Labelled 'simulated' everywhere.
    """
    receipts = {r["doc_id"]: r["receipted_date"] for r in world.receipts}
    for d in world.documents:
        if d["live"] or d["doc_type"] not in INVOICE_TYPES:
            continue
        arrived = d["arrival_ts"].date()
        officer = rng.choice(OFFICERS)
        supplier_defect = d["defect"] not in ("none", "no_receipt")
        if supplier_defect:
            decided = add_business_days(arrived, rng.choice([1, 1, 2, 3, 5]), holidays)
            if as_of and decided > as_of:
                d["live"] = True  # not decided yet: still open
                continue
            world.history.append({"doc_id": d["doc_id"], "decision": "returned", "reason": DEFECT_CHECK[d["defect"]],
                                  "decided_date": decided, "decided_by": officer, "trigger_date": None,
                                  "paid_date": None, "pay_by_current": None, "pay_by_2027": None,
                                  "late_days_current": None, "late_days_2027": None, "interest_current": 0.0})
            continue
        if d["doc_type"] == "adjustment_note":
            decided = add_business_days(arrived, rng.choice([1, 2, 3]), holidays)
            world.history.append({"doc_id": d["doc_id"], "decision": "accepted", "reason": None, "decided_date": decided,
                                  "decided_by": officer, "trigger_date": arrived, "paid_date": None, "pay_by_current": None,
                                  "pay_by_2027": None, "late_days_current": None, "late_days_2027": None, "interest_current": 0.0})
            continue
        receipt = receipts.get(d["doc_id"])
        trigger = max(arrived, receipt) if receipt else None
        if trigger is None:
            continue
        handling = rng.choices([1, 2, 3, 5, 8, 12, 16], [18, 22, 20, 16, 12, 8, 4])[0]
        decided = add_business_days(trigger, handling, holidays)
        if as_of and decided > as_of:
            d["live"] = True  # an aged item still in the queue
            continue
        # Payment runs are Tuesdays and Thursdays.
        paid = add_business_days(decided, rng.choice([1, 2, 3]), holidays)
        while paid.weekday() not in (1, 3):
            paid += dt.timedelta(days=1)
        if as_of and paid > as_of:
            paid = None  # accepted, waiting for the next payment run
        einv = d["channel"] == "peppol"
        cur = pay_by(trigger, holidays, einvoice=einv, regime="current").pay_by
        new = pay_by(trigger, holidays, einvoice=einv, regime="2027").pay_by
        late_cur = (paid - cur).days if paid else None
        late_new = business_days_between(new, paid, holidays) if paid else None
        world.history.append({
            "doc_id": d["doc_id"], "decision": "accepted", "reason": None, "decided_date": decided, "decided_by": officer,
            "trigger_date": trigger, "paid_date": paid, "pay_by_current": cur, "pay_by_2027": new,
            "late_days_current": max(late_cur, 0) if paid else None, "late_days_2027": max(late_new, 0) if paid else None,
            "interest_current": interest_payable(d["truth"]["total_inc_gst"], late_cur, gic_rate) if paid else 0.0,
        })


def apply_history_to_orders(world: World) -> None:
    """invoiced_to_date on each order = accepted, paid invoices in the simulated history."""
    by_doc = {d["doc_id"]: d for d in world.documents}
    billed: dict[str, float] = {}
    for h in world.history:
        if h["decision"] == "accepted" and h["paid_date"] is not None:
            d = by_doc[h["doc_id"]]
            billed[d["po_number"]] = billed.get(d["po_number"], 0.0) + float(d["truth"]["total_inc_gst"])
    for po in world.purchase_orders:
        po["invoiced_to_date_inc_gst"] = round(billed.get(po["po_number"], 0.0), 2)


def truth_rows(world: World) -> list[dict]:
    """Flat ground truth: one row per document with its truth fields serialised."""
    import json

    out = []
    for d in world.documents:
        out.append({
            "doc_id": d["doc_id"], "rel_path": d["rel_path"], "doc_type": d["doc_type"], "defect": d["defect"],
            "expected_failed_check": DEFECT_CHECK.get(d["defect"]), "scanned": d["scanned"], "stamp": d["stamp"],
            "supplier_id": d.get("supplier_id"), "po_number": d.get("po_number"), "related_doc_id": d.get("related_doc_id"),
            "truth_json": json.dumps(d["truth"], default=str), "lines_json": json.dumps(d.get("lines", [])),
            "batch_id": d["batch_id"],
        })
    return out


def buyer_block() -> list[str]:
    return [BUYER_NAME, *BUYER_ADDRESS, f"ABN {format_abn(BUYER_ABN)}"]
