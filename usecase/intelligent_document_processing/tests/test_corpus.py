import datetime as dt
import random

import corpus
import rules

HOL = {dt.date(2026, 12, 25)}


def _world(seed=7):
    rng = random.Random(seed)
    notices = [{"description": f"Professional services stage {i}", "unspsc": "80101500", "value": 80000 + 1000 * i,
                "start_date": "2026-01-01", "end_date": "2027-06-30", "procurement_method": "Open tender",
                "supplier_key": f"k{i % 6}", "supplier_name": "Real Supplier Name"} for i in range(20)]
    notices.append({"description": "Real Supplier Name audit", "unspsc": "80", "value": 90000, "start_date": "2026-01-01",
                    "end_date": "2027-01-01", "supplier_key": "kx", "supplier_name": "Real Supplier Name"})
    contracts = corpus.pseudonymise_contracts(notices, rng, 50)
    attrs = [dict(word_a="Kestrel", word_b="Ridge", form="Pty Ltd", street_no=1, street_idx=i, phone_suffix=1234567, bsb=62000,
                  account=12345678, gst_registered=True, einvoicing=False, template=i % 5, scan_rate=0.1) for i in range(10)]
    w = corpus.World(contracts=contracts, suppliers=corpus.build_suppliers(contracts, attrs, rng))
    w.purchase_orders = corpus.build_purchase_orders(contracts, dt.date(2026, 11, 27), rng)
    specs = [dict(doc_type="tax_invoice", defect=d, scanned=False, stamp=False, bd_offset=20 - i % 20, hour=9.5, channel="email")
             for i, d in enumerate(["none"] * 30 + list(corpus.DEFECTS))]
    corpus.build_documents(w, specs, dt.date(2026, 11, 27), HOL, rng, live_window_bd=5)
    corpus.build_receipts(w, HOL, rng, dt.date(2026, 11, 27))
    corpus.build_history(w, HOL, rng, 0.1151)
    return w


def test_pseudonymisation_drops_identifying_descriptions_and_ids():
    w = _world()
    assert all("Real Supplier" not in c["description"] for c in w.contracts)
    assert all(c["contract_id"].startswith("NBA-C-") for c in w.contracts)
    assert all("Real Supplier" not in s["name"] for s in w.suppliers)
    assert len({s["name"] for s in w.suppliers}) == len(w.suppliers)


def test_deterministic_for_a_seed():
    a, b = _world(3), _world(3)
    assert [d["truth"] for d in a.documents] == [d["truth"] for d in b.documents]


def test_invoice_truth_is_internally_consistent():
    w = _world()
    for d in w.documents:
        t = d["truth"]
        if d["defect"] in ("gst_error", "duplicate"):
            continue
        assert rules.gst_consistent(t["subtotal_ex_gst"], t["gst_amount"], t["total_inc_gst"])
        assert abs(sum(ln["amount"] for ln in d["lines"]) - abs(t["subtotal_ex_gst"])) < 0.02
        assert rules.abn_valid(t["supplier_abn"]) == (d["defect"] != "invalid_abn")


def test_defects_land_and_duplicates_point_backwards():
    w = _world()
    by = {d["doc_id"]: d for d in w.documents}
    for d in w.documents:
        if d["defect"] == "duplicate":
            orig = by[d["related_doc_id"]]
            assert orig["arrival_ts"] <= d["arrival_ts"]
            assert orig["truth"]["invoice_number"] == d["truth"]["invoice_number"]
        if d["defect"] == "missing_po":
            assert d["truth"]["po_number"] is None


def test_history_only_for_documents_outside_live_window():
    w = _world()
    live = {d["doc_id"] for d in w.documents if d["live"]}
    assert live and not live & {h["doc_id"] for h in w.history}
