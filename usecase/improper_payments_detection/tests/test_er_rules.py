"""Tests for src/er_rules.py. Pure Python: no Spark, no network."""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import er_rules as er  # noqa: E402


def supplier(key, name, street="", suburb="", postcode="", abn=None):
    return {"key": key, "kind": "supplier", "name": er.normalise_name(name), "abn": er.normalise_abn(abn),
            "street": er.normalise_street(street), "suburb": suburb, "postcode": postcode}


def claimant(key, given, family, dob, postcode="", street=""):
    return {"key": key, "kind": "claimant", "given": er.normalise_name(given), "family": er.normalise_name(family),
            "dob": dob, "postcode": postcode, "street": er.normalise_street(street),
            "name": er.normalise_name(f"{given} {family}")}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def test_abn_is_eleven_digits_whatever_the_formatting():
    assert er.normalise_abn("51 824 753 556") == "51824753556"
    assert er.normalise_abn("51-824-753-556") == "51824753556"
    assert er.normalise_abn("ABN 51824753556") == "51824753556"
    assert er.normalise_abn("5182475355") is None  # ten digits
    assert er.normalise_abn("") is None and er.normalise_abn(None) is None


def test_business_names_drop_legal_form_and_punctuation():
    expected = "NORTH HARBOUR SUPPLIES"
    assert er.normalise_name("North Harbour Supplies Pty. Ltd.") == expected
    assert er.normalise_name("NORTH HARBOUR SUPPLIES P/L") == expected
    assert er.normalise_name("North Harbour Supplies Proprietary Limited") == expected
    assert er.normalise_name("Riverbend & Sons") == "RIVERBEND AND SONS"


def test_street_types_are_expanded():
    assert er.normalise_street("12 Harbour St") == "12 HARBOUR STREET"
    assert er.normalise_street("4/7 Wattle Rd.") == "4 7 WATTLE ROAD"


def test_phone_international_prefix_becomes_national():
    assert er.normalise_phone("+61 412 345 678") == "0412345678"
    assert er.normalise_phone("0412 345 678") == "0412345678"


def test_bank_key_combines_bsb_and_account():
    assert er.normalise_bank("062-000", "12345678") == "062000-12345678"
    assert er.normalise_bank("062-000", "") is None


# ---------------------------------------------------------------------------
# String similarity
# ---------------------------------------------------------------------------
def test_jaro_winkler_matches_reference_values():
    assert abs(er.jaro_winkler("MARTHA", "MARHTA") - 0.9611) < 1e-3
    assert abs(er.jaro_winkler("DWAYNE", "DUANE") - 0.84) < 1e-2
    assert abs(er.jaro_winkler("DIXON", "DICKSONX") - 0.8133) < 1e-3
    assert er.jaro_winkler("ABC", "ABC") == 1.0
    assert er.jaro_winkler("ABC", "XYZ") == 0.0


# ---------------------------------------------------------------------------
# Matching and clustering
# ---------------------------------------------------------------------------
def test_registry_record_matches_master_record_on_abn_despite_name_drift():
    a = supplier("master:1", "North Harbour Supplies Pty Ltd", "12 Harbour St", "Parramatta", "2150", abn="51 824 753 556")
    b = supplier("registry:9", "NORTH HARBOUR SUPPLIES P/L", "12 Harbour Street", "Parramatta", "2150", abn="51824753556")
    prob, method = er.match_probability(a, b)
    assert prob >= 0.85 and method == "abn"


def test_homonym_at_another_address_is_not_merged():
    a = supplier("master:1", "North Harbour Supplies Pty Ltd", "12 Harbour St", "Parramatta", "2150")
    b = supplier("registry:2", "North Harbour Supplies Pty Ltd", "12 Harbour St", "Dandenong", "3175")
    assert er.match_probability(a, b)[0] == 0.0


def test_claimant_duplicate_with_name_drift_matches_on_dob():
    a = claimant("master:c1", "Amelia", "Harrow", "1984-03-02", "2150", "4 Wattle Street")
    b = claimant("master:c2", "Amelie", "HARROW", "1984-03-02", "3175", "9 Kestrel Road")
    prob, method = er.match_probability(a, b)
    assert prob >= 0.85 and method == "person_dob"


def test_different_claimants_with_same_phone_are_not_merged_by_rules():
    # Shared contact details are a graph signal, not an identity signal.
    a = claimant("c1", "Amelia", "Harrow", "1984-03-02", "2150")
    b = claimant("c2", "Oliver", "Tanaka", "1971-11-19", "2150")
    assert er.match_probability(a, b)[0] == 0.0


def test_assign_entities_chains_links_and_is_order_independent():
    keys = ["a", "b", "c", "d"]
    links = [("a", "b", 0.99, "abn"), ("b", "c", 0.90, "name_address")]
    rows_1 = er.assign_entities(keys, links)
    shuffled = list(keys)
    random.Random(7).shuffle(shuffled)
    rows_2 = er.assign_entities(shuffled, list(reversed(links)))
    by_key_1 = {r["key"]: r for r in rows_1}
    by_key_2 = {r["key"]: r for r in rows_2}
    assert by_key_1["a"]["entity_id"] == by_key_1["b"]["entity_id"] == by_key_1["c"]["entity_id"]
    assert by_key_1["d"]["entity_id"] != by_key_1["a"]["entity_id"]
    assert {k: v["entity_id"] for k, v in by_key_1.items()} == {k: v["entity_id"] for k, v in by_key_2.items()}
    assert by_key_1["d"]["method"] == "singleton" and by_key_1["d"]["match_probability"] == 1.0


def test_stable_id_is_the_hash_of_the_smallest_member_key():
    eid = er.stable_entity_id(["supplier_master:SM-2", "business_registry:BR-7"])
    assert eid == er.stable_entity_id(["business_registry:BR-7", "supplier_master:SM-2"])
    assert eid.startswith("ENT-") and len(eid) == 14


def test_links_below_threshold_do_not_merge():
    rows = er.assign_entities(["a", "b"], [("a", "b", 0.5, "fuzzy")], threshold=0.85)
    assert rows[0]["entity_id"] != rows[1]["entity_id"]


def test_resolve_records_end_to_end_on_a_small_population():
    records = [
        supplier("supplier_master:SM-1", "North Harbour Supplies Pty Ltd", "12 Harbour St", "Parramatta", "2150", "51 824 753 556"),
        supplier("business_registry:BR-1", "NORTH HARBOUR SUPPLIES P/L", "12 Harbour Street", "Parramatta", "2150", "51824753556"),
        supplier("business_registry:BR-2", "North Harbour Supplies Pty Ltd", "3 Other Road", "Dandenong", "3175", "10 000 000 009"),
        claimant("claimant:CR-1", "Amelia", "Harrow", "1984-03-02", "2150", "4 Wattle Street"),
        claimant("claimant:CR-2", "Amelie", "Harrow", "1984-03-02", "2150", "4 Wattle Street"),
    ]
    rows = {r["key"]: r for r in er.resolve_records(records)}
    assert rows["supplier_master:SM-1"]["entity_id"] == rows["business_registry:BR-1"]["entity_id"]
    assert rows["business_registry:BR-2"]["entity_id"] != rows["supplier_master:SM-1"]["entity_id"]
    assert rows["claimant:CR-1"]["entity_id"] == rows["claimant:CR-2"]["entity_id"]
    assert rows["claimant:CR-1"]["entity_id"] != rows["supplier_master:SM-1"]["entity_id"]


def test_candidate_pairs_never_cross_kinds():
    records = [
        supplier("s:1", "Same Name", "1 A St", "X", "2000"),
        {"key": "c:1", "kind": "claimant", "name": "SAME NAME", "postcode": "2000", "street": "1 A STREET"},
    ]
    assert er.candidate_pairs(records) == []
