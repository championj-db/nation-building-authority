"""Pure-Python relationship graph for the improper payments use case (no Spark).

The graph is bipartite in practice: party nodes (supplier, claimant) connect to attribute nodes
(bank_account, address, phone, email, director, officer, assessor). Two parties are related when
they reach the same attribute node, which is the "2-hop shared-attribute link" the case view is
built on.

What lives here:
  * build_graph         - adjacency from node and edge rows (silver_graph_node / _edge)
  * components          - groups of member nodes joined through shared attribute nodes. Used to
                          form claimant clusters (claimants sharing a phone, email or account).
  * related_entities    - the parties linked to a subject through a shared attribute
  * case_subgraph       - a bounded, deterministic neighbourhood for one case (<= max_nodes),
                          so the same case always draws the same picture

Ordering is always by explicit keys, never by insertion order, so results are identical for
identical inputs however the rows arrived.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

# Priority when a case graph has more candidates than it can show. Lower is shown first.
KIND_RANK = {
    "bank_account": 0,
    "assessor": 1,
    "officer": 2,
    "address": 3,
    "director": 4,
    "phone": 5,
    "email": 6,
}
PARTY_KINDS = frozenset({"supplier", "claimant"})
OFFICER_KINDS = frozenset({"officer", "assessor"})


@dataclass
class Graph:
    nodes: dict = field(default_factory=dict)   # node_id -> {"kind", "label", "sub_label"}
    adj: dict = field(default_factory=lambda: defaultdict(dict))  # node -> {other: (relation, weight)}
    edges: list = field(default_factory=list)    # (src, dst, relation, weight), as supplied

    def kind(self, node: str) -> str:
        return self.nodes[node]["kind"]

    def weight(self, a: str, b: str) -> float:
        return self.adj[a][b][1] if b in self.adj.get(a, {}) else 0.0


def build_graph(nodes: Iterable[dict], edges: Iterable[tuple]) -> Graph:
    """nodes: dicts with id, kind, label, sub_label. edges: (src, dst, relation, weight)."""
    g = Graph()
    for n in nodes:
        g.nodes[n["id"]] = {"kind": n["kind"], "label": n.get("label", ""), "sub_label": n.get("sub_label", "")}
    for src, dst, relation, weight in sorted(edges, key=lambda e: (e[0], e[1], e[2])):
        if src not in g.nodes or dst not in g.nodes or src == dst:
            continue
        g.edges.append((src, dst, relation, float(weight)))
        for a, b in ((src, dst), (dst, src)):
            prev = g.adj[a].get(b)
            if prev is None or float(weight) > prev[1]:
                g.adj[a][b] = (relation, float(weight))
    return g


def neighbours(g: Graph, node: str) -> list[str]:
    return sorted(g.adj.get(node, {}))


def components(g: Graph, member_kinds: Iterable[str], via_kinds: Iterable[str]) -> list[list[str]]:
    """Connected groups of member nodes, where two members are joined if they share a via node.

    Example: claimants joined through shared phone, email or bank-account nodes. Members that share
    nothing come back as singleton groups. Output groups and their members are sorted.
    """
    members = {n for n, meta in g.nodes.items() if meta["kind"] in set(member_kinds)}
    vias = set(via_kinds)
    seen: set[str] = set()
    out: list[list[str]] = []
    for start in sorted(members):
        if start in seen:
            continue
        group, stack = set(), [start]
        seen.add(start)
        while stack:
            cur = stack.pop()
            group.add(cur)
            for via in neighbours(g, cur):
                if g.kind(via) not in vias:
                    continue
                for other in neighbours(g, via):
                    if other in members and other not in seen:
                        seen.add(other)
                        stack.append(other)
        out.append(sorted(group))
    return sorted(out)


def related_entities(g: Graph, subject: str, party_kinds: Iterable[str] = PARTY_KINDS) -> dict[str, list[str]]:
    """Other parties that share at least one attribute node with `subject`.

    Returns {related_party: [shared attribute node ids]}, both sorted.
    """
    parties = set(party_kinds)
    out: dict[str, set[str]] = defaultdict(set)
    for attr in neighbours(g, subject):
        if g.kind(attr) in parties:
            continue
        for other in neighbours(g, attr):
            if other != subject and g.kind(other) in parties:
                out[other].add(attr)
    return {k: sorted(v) for k, v in sorted(out.items())}


def case_subgraph(g: Graph, subject: str, max_nodes: int = 8) -> dict:
    """Bounded neighbourhood for one case.

    Candidates are the subject's attribute neighbours (hop 1) and the parties that share those
    attributes (hop 2). They are ranked by (kind rank, hop, strongest link weight, id) and the
    subject is always kept. Returns {"nodes": [ordered ids, subject first], "edges": [(src, dst,
    relation)] among the kept nodes, "hop": {id: 1 | 2}, "via": {related id: shared attr id}}.
    """
    if subject not in g.nodes:
        raise KeyError(f"unknown subject {subject!r}")
    if max_nodes < 1:
        raise ValueError("max_nodes must be at least 1")
    party = PARTY_KINDS
    candidates: dict[str, tuple] = {}
    hop: dict[str, int] = {}
    via: dict[str, str] = {}

    for attr in neighbours(g, subject):
        if g.kind(attr) in party:
            continue
        candidates[attr] = (KIND_RANK.get(g.kind(attr), 9), 1, -g.weight(subject, attr), attr)
        hop[attr] = 1
    for other, shared in related_entities(g, subject).items():
        best = min(shared, key=lambda a: (KIND_RANK.get(g.kind(a), 9), a))
        candidates[other] = (KIND_RANK.get(g.kind(best), 9), 2, -g.weight(best, other), other)
        hop[other] = 2
        via[other] = best

    # Evidence first: an officer or assessor one hop away who is also registered at one of the
    # subject's own addresses (approver at the director's address, claimant at the assessor's) is
    # the link that scored the case. Keep that person and the shared address ahead of everything,
    # and report the person as related (hop 2, via the address) so it reads as a second party.
    subject_attrs = set(neighbours(g, subject))
    for attr in sorted(subject_attrs):
        if g.kind(attr) not in OFFICER_KINDS:
            continue
        shared = sorted(a for a in neighbours(g, attr) if a in subject_attrs and g.kind(a) == "address")
        if not shared:
            continue
        candidates[attr] = (-2, 0, 0.0, attr)
        candidates[shared[0]] = (-1, 0, 0.0, shared[0])
        hop[attr] = 2
        hop[shared[0]] = 1
        via[attr] = shared[0]

    ordered = sorted(candidates, key=lambda n: candidates[n])
    kept = [subject] + ordered[: max(max_nodes - 1, 0)]
    kept_set = set(kept)
    edges = sorted({(s, d, rel) for s, d, rel, _w in g.edges if s in kept_set and d in kept_set})
    return {
        "nodes": kept,
        "edges": edges,
        "hop": {n: hop[n] for n in kept if n in hop},
        "via": {n: via[n] for n in kept if n in via},
    }



# ---------------------------------------------------------------------------
# Building the graph from resolved entities and payments
# ---------------------------------------------------------------------------
def _short(text: str, limit: int = 16) -> str:
    """Whole words up to `limit` characters."""
    words, out = str(text or "").split(), ""
    for w in words:
        candidate = f"{out} {w}".strip()
        if len(candidate) > limit:
            break
        out = candidate
    return out or str(text or "")[:limit]


def graph_rows(parties: list[dict], xref: list[dict], entities: list[dict], payments: list[dict],
               officers: list[dict]) -> tuple[list[dict], list[tuple]]:
    """Node and edge rows for silver_graph_node and silver_graph_edge.

    parties   normalised party records (er_rules.party_records): phone, email, bank and address keys
    xref      party key -> entity_id (er_rules.assign_entities)
    entities  entity rows (er_rules.build_entities)
    payments  dicts with entity_id, bank_key, approver_officer_id and assessor_officer_id (or None)
    officers  dicts with officer_id, role, home_key

    Edges: entity -pays into-> bank account (weight = payments), entity -registered at-> address
    (business and director), entity -shares-> phone, email or director, entity -approved by->
    officer (weight = payments approved), entity -assessed by-> assessor (weight = claims assessed),
    officer -registered at-> home address.
    """
    nodes: dict[str, dict] = {}
    weights: dict[tuple, float] = {}

    def add_node(node_id, kind, label, sub_label):
        nodes.setdefault(node_id, {"id": node_id, "kind": kind, "label": label, "sub_label": sub_label})

    def add_edge(src, dst, relation, weight=1.0):
        weights[(src, dst, relation)] = weights.get((src, dst, relation), 0.0) + float(weight)

    def address_node(address_key, label_sub):
        add_node(f"addr:{address_key}", "address", label_sub.title()[:16], "Address")
        return f"addr:{address_key}"

    entity_of = {x["key"]: x["entity_id"] for x in xref}
    for e in entities:
        ent_node = f"ent:{e['entity_id']}"
        if e["entity_kind"] == "claimant":
            add_node(ent_node, "claimant", f"Claimant {e['entity_id'][-4:]}", "Claimant")
        else:
            add_node(ent_node, "supplier", _short(e.get("display_name") or e["entity_id"]), "Supplier")
        if e.get("address_key"):
            add_edge(ent_node, address_node(e["address_key"], e["address_key"].split("|")[1]), "registered at")
        if e["entity_kind"] == "supplier" and e.get("director_address_key"):
            add_edge(ent_node, address_node(e["director_address_key"], e["director_address_key"].split("|")[1]), "registered at")
        if e["entity_kind"] == "supplier" and e.get("director_name"):
            add_node(f"dir:{e['director_name']}", "director", _short(e["director_name"].title()), "Director")
            add_edge(ent_node, f"dir:{e['director_name']}", "shares")

    for rec in parties:
        eid = entity_of.get(rec["key"])
        if eid is None:
            continue
        ent_node = f"ent:{eid}"
        if rec.get("phone"):
            add_node(f"tel:{rec['phone']}", "phone", f"Phone ··{rec['phone'][-3:]}", "Phone")
            add_edge(ent_node, f"tel:{rec['phone']}", "shares")
        if rec.get("email"):
            local = rec["email"].split("@")[0]
            add_node(f"mail:{rec['email']}", "email", _short(local, 16), "Email")
            add_edge(ent_node, f"mail:{rec['email']}", "shares")

    for pay in payments:
        ent_node = f"ent:{pay['entity_id']}"
        if pay.get("bank_key"):
            acct = pay["bank_key"].split("-")[-1]
            add_node(f"bank:{pay['bank_key']}", "bank_account", f"Account ··{acct[-3:]}", "Bank account")
            add_edge(ent_node, f"bank:{pay['bank_key']}", "pays into")
        if pay.get("approver_officer_id"):
            add_edge(ent_node, f"off:{pay['approver_officer_id']}", "approved by")
        if pay.get("assessor_officer_id"):
            add_edge(ent_node, f"off:{pay['assessor_officer_id']}", "assessed by")

    officer_by_id = {o["officer_id"]: o for o in officers}
    for pay in payments:
        for key in ("approver_officer_id", "assessor_officer_id"):
            oid = pay.get(key)
            if oid and f"off:{oid}" not in nodes and oid in officer_by_id:
                o = officer_by_id[oid]
                kind = "assessor" if o["role"] == "assessor" else "officer"
                sub = "Assessor" if kind == "assessor" else "Approver"
                add_node(f"off:{oid}", kind, f"Officer {oid[-3:]}", sub)
                if o.get("home_key"):
                    add_edge(f"off:{oid}", address_node(o["home_key"], o["home_key"].split("|")[1]), "registered at")

    edge_rows = [(s, d, r, w) for (s, d, r), w in sorted(weights.items())]
    return list(nodes.values()), edge_rows
