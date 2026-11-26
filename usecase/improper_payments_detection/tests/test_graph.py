"""Tests for src/graph.py. Pure Python: no Spark, no network."""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import graph as gr  # noqa: E402


def sample_graph(order_seed=None):
    nodes = [
        {"id": "s:A", "kind": "supplier", "label": "North Harbour"},
        {"id": "s:B", "kind": "supplier", "label": "Metro Field"},
        {"id": "s:C", "kind": "supplier", "label": "Riverbend"},
        {"id": "s:D", "kind": "supplier", "label": "Lone Co"},
        {"id": "acct:1", "kind": "bank_account", "label": "Account ··824"},
        {"id": "off:29", "kind": "officer", "label": "Officer 029"},
        {"id": "addr:X", "kind": "address", "label": "Parramatta"},
        {"id": "c:1", "kind": "claimant", "label": "Claimant 1"},
        {"id": "c:2", "kind": "claimant", "label": "Claimant 2"},
        {"id": "c:3", "kind": "claimant", "label": "Claimant 3"},
        {"id": "tel:1", "kind": "phone", "label": "Phone ··111"},
    ]
    edges = [
        ("s:A", "acct:1", "pays into", 1),
        ("s:B", "acct:1", "pays into", 1),
        ("s:C", "acct:1", "pays into", 1),
        ("s:A", "off:29", "approved by", 12),
        ("s:A", "addr:X", "registered at", 1),
        ("c:1", "tel:1", "shares", 1),
        ("c:2", "tel:1", "shares", 1),
        ("c:3", "tel:1", "shares", 1),
        ("s:D", "addr:X", "registered at", 1),
    ]
    if order_seed is not None:
        random.Random(order_seed).shuffle(nodes)
        random.Random(order_seed + 1).shuffle(edges)
    return gr.build_graph(nodes, edges)


def test_neighbours_are_sorted_and_undirected():
    g = sample_graph()
    assert gr.neighbours(g, "acct:1") == ["s:A", "s:B", "s:C"]
    assert "acct:1" in gr.neighbours(g, "s:A")


def test_components_group_claimants_through_shared_phone():
    g = sample_graph()
    groups = gr.components(g, member_kinds={"claimant"}, via_kinds={"phone", "email", "bank_account"})
    assert groups == [["c:1", "c:2", "c:3"]]


def test_components_return_singletons_for_unshared_members():
    g = sample_graph()
    groups = gr.components(g, member_kinds={"supplier"}, via_kinds={"phone", "email"})
    assert groups == [["s:A"], ["s:B"], ["s:C"], ["s:D"]]


def test_related_entities_are_two_hops_through_shared_attributes():
    g = sample_graph()
    related = gr.related_entities(g, "s:A")
    assert related == {"s:B": ["acct:1"], "s:C": ["acct:1"], "s:D": ["addr:X"]}


def test_case_subgraph_keeps_subject_and_respects_the_node_budget():
    g = sample_graph()
    sub = gr.case_subgraph(g, "s:A", max_nodes=3)
    assert sub["nodes"][0] == "s:A"
    assert len(sub["nodes"]) == 3
    # bank accounts rank first, so the shared account is shown before the officer or address
    assert sub["nodes"][1] == "acct:1"


def test_case_subgraph_edges_only_join_kept_nodes():
    g = sample_graph()
    sub = gr.case_subgraph(g, "s:A", max_nodes=4)
    kept = set(sub["nodes"])
    assert sub["edges"]
    assert all(s in kept and d in kept for s, d, _r in sub["edges"])


def test_case_subgraph_marks_hop_and_via_for_related_parties():
    g = sample_graph()
    sub = gr.case_subgraph(g, "s:A", max_nodes=8)
    assert sub["hop"]["acct:1"] == 1
    assert sub["hop"]["s:B"] == 2 and sub["via"]["s:B"] == "acct:1"
    assert len(sub["nodes"]) <= 8


def test_case_subgraph_is_identical_however_the_rows_arrived():
    a = gr.case_subgraph(sample_graph(), "s:A", max_nodes=5)
    b = gr.case_subgraph(sample_graph(order_seed=3), "s:A", max_nodes=5)
    assert a == b


def test_unknown_subject_and_bad_budget_raise():
    g = sample_graph()
    for call in (lambda: gr.case_subgraph(g, "nope"), lambda: gr.case_subgraph(g, "s:A", max_nodes=0)):
        try:
            call()
        except (KeyError, ValueError):
            continue
        raise AssertionError("expected an error")


def test_case_subgraph_keeps_officer_at_subject_address_first():
    nodes = [{"id": "ent:s", "kind": "supplier", "label": "S", "sub_label": "Supplier"}]
    nodes += [{"id": f"off:{i}", "kind": "officer", "label": f"Officer {i}", "sub_label": "Approver"} for i in range(10)]
    nodes += [{"id": "addr:home", "kind": "address", "label": "1 Home St", "sub_label": "Address"},
              {"id": "bank:a", "kind": "bank_account", "label": "Account", "sub_label": "Bank account"}]
    edges = [("ent:s", f"off:{i}", "approved by", 1.0) for i in range(10)]
    edges += [("ent:s", "addr:home", "registered at", 1.0), ("off:7", "addr:home", "registered at", 1.0),
              ("ent:s", "bank:a", "pays into", 5.0)]
    g = gr.build_graph(nodes, edges)
    sub = gr.case_subgraph(g, "ent:s", max_nodes=4)
    assert sub["nodes"][:3] == ["ent:s", "off:7", "addr:home"]
    assert sub["hop"]["off:7"] == 2 and sub["via"]["off:7"] == "addr:home"
    assert ("off:7", "addr:home", "registered at") in sub["edges"]
