import datetime as dt
import json

import assess

ELEMENTS = [
    {"id": 0, "type": "text", "content": "Invoice number: KRC-20431\nPurchase order: PO-4500183921", "bbox": [{"coord": [941, 330, 1434, 519], "page_id": 0}]},
    {"id": 1, "type": "table", "content": "Total (incl. GST) $11,330.00", "bbox": [{"coord": [155, 648, 1499, 968], "page_id": 0}]},
]
CITATIONS = [{"id": 3, "bbox": [{"coord": [941, 330, 1434, 519], "page_id": 0}]}, {"id": 4, "bbox": [{"coord": [155, 648, 1499, 968], "page_id": 0}]}]


def test_citation_resolves_to_region_and_text():
    regions, text = assess.resolve_citation([4], CITATIONS, assess.index_elements(json.dumps(ELEMENTS)))
    assert regions == [{"page": 0, "x0": 155, "y0": 648, "x1": 1499, "y1": 968}]
    assert "$11,330.00" in text


def test_field_rows_ground_against_cited_text():
    fields = {"invoice_number": {"value": "KRC-20431", "confidence_score": 1, "citation_ids": [3]},
              "total_inc_gst": {"value": 11330, "confidence_score": 0.99, "citation_ids": [4]},
              "po_number": {"value": "PO-4500183922", "confidence_score": 0.97, "citation_ids": [3]}}
    rows = {r["field"]: r for r in assess.field_rows(json.dumps(fields), json.dumps(CITATIONS), json.dumps(ELEMENTS))}
    assert rows["invoice_number"]["grounded"] and rows["invoice_number"]["routing_confidence"] == 1.0
    assert rows["total_inc_gst"]["value"] == "11330.00"
    assert not rows["po_number"]["grounded"] and rows["po_number"]["below_threshold"]  # misread digit is caught
    assert rows["supplier_abn"]["routing_confidence"] == 0.0 and rows["supplier_abn"]["below_threshold"]


def _ledger():
    pos = [{"po_number": "PO-1", "contract_id": "C1", "supplier_id": "V1", "status": "open", "po_value_inc_gst": 20000.0}]
    sups = [{"supplier_id": "V1", "name": "Kestrel Ridge Consulting Pty Ltd", "abn": "51 824 753 556", "gst_registered": True, "einvoicing": False}]
    rec = [{"receipt_id": "GR-1", "po_number": "PO-1", "amount_inc_gst": 11000.0, "receipted_date": dt.date(2026, 11, 10)},
           {"receipt_id": "GR-2", "po_number": "PO-1", "amount_inc_gst": 8800.0, "receipted_date": dt.date(2026, 11, 12)}]
    return assess.Ledger(pos, sups, rec)


def _doc(doc_id, number, total, arrival):
    sub = round(total / 1.1, 2)
    f = {"document_title": "Tax invoice", "supplier_name": "Kestrel Ridge Consulting Pty Ltd", "supplier_abn": "51824753556",
         "recipient_name": "Nation Building Authority", "invoice_number": number, "invoice_date": arrival.isoformat(),
         "po_number": "PO-1", "subtotal_ex_gst": sub, "gst_amount": round(total - sub, 2), "total_inc_gst": total}
    text = "\n".join(f"{k}: {v}" for k, v in f.items()) + f"\n${total:,.2f}\n${sub:,.2f}\n${total - sub:,.2f}\n{arrival:%d/%m/%Y}"
    fields = {k: {"value": v, "confidence_score": 0.99, "citation_ids": []} for k, v in f.items()}
    return {"doc_id": doc_id, "doc_type": "tax_invoice", "arrival_date": arrival, "channel": "email",
            "fields_json": json.dumps(fields), "citations_json": "[]", "elements_json": "[]", "full_text": text}


def test_three_way_match_duplicate_and_order_value():
    ledger = _ledger()
    hol = set()
    today = dt.date(2026, 11, 27)
    a = assess.assess_invoice(_doc("DOC-1", "KRC-1", 11000.0, dt.date(2026, 11, 13)), ledger, hol, today)["summary"]
    assert a["status"] == "ready" and a["receipt_id"] == "GR-1"
    assert a["trigger_date"] == dt.date(2026, 11, 13) and a["pay_by_date"] == dt.date(2026, 12, 3)
    dup = assess.assess_invoice(_doc("DOC-2", "KRC-1", 11000.0, dt.date(2026, 11, 16)), ledger, hol, today)["summary"]
    assert dup["status"] == "exception" and "not_duplicate" in dup["failed_checks"] and dup["duplicate_of"] == "DOC-1"
    over = assess.assess_invoice(_doc("DOC-3", "KRC-2", 9900.0, dt.date(2026, 11, 17)), ledger, hol, today)["summary"]
    assert "within_po_value" in over["failed_checks"]  # 11,000 already billed of 20,000
    no_receipt = assess.assess_invoice(_doc("DOC-4", "KRC-3", 3300.0, dt.date(2026, 11, 18)), ledger, hol, today)["summary"]
    assert no_receipt["status"] == "awaiting_delivery" and no_receipt["trigger_date"] is None
