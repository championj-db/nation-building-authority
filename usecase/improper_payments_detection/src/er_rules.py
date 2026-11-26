"""Pure-Python entity resolution rules for the improper payments use case (no Spark).

Two jobs:

1. Normalisation - ABNs, business names, street addresses, phone numbers and person names are
   brought to one canonical form so that the same party written three ways in three systems
   compares equal. Registry entries drift in punctuation, legal suffixes and abbreviations; the
   rules here absorb that drift without making unrelated parties look alike.

2. Clustering - pairwise match probabilities (from the rules below, or from Splink when it is
   available) are assembled into entities with union-find. Entity ids are derived from the
   lexicographically smallest member key, so an entity keeps its id across reruns as long as its
   members do. Nothing is minted from a counter, so the ids do not depend on row order.

The Splink path (02_entity_resolution.py) reuses assign_entities(); only the scoring differs.
Kept free of Spark so it can be unit-tested locally.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Iterable

# Legal-form tokens that carry no identity. "P L" is the "P/L" abbreviation after punctuation
# is stripped.
LEGAL_TOKENS = frozenset({"PTY", "LTD", "LIMITED", "PROPRIETARY", "PL", "P", "L"})

STREET_ABBREVIATIONS = {
    "ST": "STREET", "RD": "ROAD", "AVE": "AVENUE", "AV": "AVENUE", "CT": "COURT", "DR": "DRIVE",
    "TCE": "TERRACE", "PDE": "PARADE", "CRES": "CRESCENT", "HWY": "HIGHWAY", "PL": "PLACE",
}

# Blocks larger than this are skipped rather than compared pairwise. A block that big is a
# generic value (a common surname with a postcode, say), not a meaningful candidate set.
MAX_BLOCK_SIZE = 300

_NON_ALNUM = re.compile(r"[^A-Z0-9 ]")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def normalise_abn(value) -> str | None:
    """Eleven digits, whatever the formatting ('51 824 753 556', '51-824-753-556', 'ABN 5182...')."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) == 11 else None


def normalise_name(value) -> str:
    """Upper-case, punctuation removed, legal-form tokens dropped.

    'North Harbour Supplies Pty. Ltd.' and 'NORTH HARBOUR SUPPLIES P/L' both become
    'NORTH HARBOUR SUPPLIES'.
    """
    text = _NON_ALNUM.sub(" ", str(value or "").upper().replace("&", " AND "))
    return " ".join(t for t in text.split() if t not in LEGAL_TOKENS)


def normalise_street(value) -> str:
    """Upper-case with common street-type abbreviations expanded ('12 Harbour St' -> '12 HARBOUR STREET')."""
    text = _NON_ALNUM.sub(" ", str(value or "").upper())
    return " ".join(STREET_ABBREVIATIONS.get(t, t) for t in text.split())


def normalise_phone(value) -> str | None:
    """Digits only, with an international '61' prefix turned into the national '0' form."""
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("61") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits or None


def normalise_email(value) -> str | None:
    text = str(value or "").strip().lower()
    return text or None


def normalise_bank(bsb, account) -> str | None:
    """Stable key for a bank account: BSB and account number, digits only."""
    b = re.sub(r"\D", "", str(bsb or ""))
    a = re.sub(r"\D", "", str(account or ""))
    return f"{b}-{a}" if a else None


def normalise_address(street, suburb, postcode) -> str | None:
    """Key for a physical address. Used for matching and for graph address nodes alike."""
    s, sub, pc = normalise_street(street), " ".join(str(suburb or "").upper().split()), str(postcode or "").strip()
    return f"{s}|{sub}|{pc}" if s and pc else None


# ---------------------------------------------------------------------------
# String similarity (Jaro-Winkler, pure Python)
# ---------------------------------------------------------------------------
def jaro(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if not len1 or not len2:
        return 0.0
    window = max(max(len1, len2) // 2 - 1, 0)
    matched1 = [False] * len1
    matched2 = [False] * len2
    matches = 0
    for i, ch in enumerate(s1):
        lo, hi = max(0, i - window), min(i + window + 1, len2)
        for j in range(lo, hi):
            if not matched2[j] and s2[j] == ch:
                matched1[i] = matched2[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    transpositions, k = 0, 0
    for i in range(len1):
        if matched1[i]:
            while not matched2[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1
    transpositions /= 2
    return (matches / len1 + matches / len2 + (matches - transpositions) / matches) / 3


def jaro_winkler(s1: str, s2: str, prefix_scale: float = 0.1) -> float:
    """Jaro-Winkler similarity in [0, 1]; boosts strings that share a 4-character prefix."""
    score = jaro(s1, s2)
    prefix = 0
    for a, b in zip(s1[:4], s2[:4]):
        if a != b:
            break
        prefix += 1
    return score + prefix * prefix_scale * (1 - score)


# ---------------------------------------------------------------------------
# Record-level matching
# ---------------------------------------------------------------------------
# A record is a plain dict: key (unique, "system:source_id"), kind ("supplier" | "claimant"),
# abn, name, street, suburb, postcode, given, family, dob, email, phone. Values are already
# normalised by the caller with the functions above.

def block_keys(rec: dict) -> list[str]:
    """Blocking keys: only pairs sharing a key are ever compared."""
    keys = []
    if rec.get("abn"):
        keys.append(f"abn:{rec['abn']}")
    if rec.get("name") and rec.get("postcode"):
        keys.append(f"name:{rec['postcode']}:{rec['name'][:6]}")
    if rec.get("family") and rec.get("dob"):
        keys.append(f"person:{rec['family'][:4]}:{rec['dob']}")
    if rec.get("family") and rec.get("postcode"):
        keys.append(f"family:{rec['postcode']}:{rec['family']}")
    return keys


def candidate_pairs(records: list[dict]) -> list[tuple[int, int]]:
    """Index pairs (i < j) that share at least one blocking key, of the same kind."""
    blocks: dict[str, list[int]] = defaultdict(list)
    for idx, rec in enumerate(records):
        for key in block_keys(rec):
            blocks[f"{rec['kind']}|{key}"].append(idx)
    pairs: set[tuple[int, int]] = set()
    for members in blocks.values():
        if 1 < len(members) <= MAX_BLOCK_SIZE:
            for a in range(len(members)):
                for b in range(a + 1, len(members)):
                    i, j = members[a], members[b]
                    pairs.add((min(i, j), max(i, j)))
    return sorted(pairs)


def match_probability(a: dict, b: dict) -> tuple[float, str]:
    """Rule-based match probability and the rule that produced it. 0.0 means no evidence."""
    if a["kind"] != b["kind"]:
        return 0.0, "kind_mismatch"
    if a.get("abn") and a.get("abn") == b.get("abn"):
        return 0.99, "abn"
    same_postcode = bool(a.get("postcode")) and a.get("postcode") == b.get("postcode")
    street_sim = jaro_winkler(a.get("street", ""), b.get("street", "")) if a.get("street") and b.get("street") else 0.0
    if a["kind"] == "claimant":
        if (a.get("dob") and a.get("dob") == b.get("dob") and a.get("family") and b.get("family")
                and jaro_winkler(a["family"], b["family"]) >= 0.92
                and jaro_winkler(a.get("given", ""), b.get("given", "")) >= 0.92):
            return 0.95, "person_dob"
        # Same person at the same address, with a name variant. Members of one household share
        # an address and a surname but not a given name, so the given name must agree too.
        same_address = bool(a.get("address_key")) and a.get("address_key") == b.get("address_key")
        if (same_address and jaro_winkler(a.get("family", ""), b.get("family", "")) >= 0.92
                and jaro_winkler(a.get("given", ""), b.get("given", "")) >= 0.85):
            return 0.85, "person_address"
        return 0.0, "none"
    if a.get("name") and a.get("name") == b.get("name") and same_postcode and street_sim >= 0.9:
        return 0.95, "name_address"
    # Names that differ only in a trailing word ("... Group" and "... Regional") are different
    # businesses, so fuzzy name matching needs the same street address and a near-identical name.
    same_address = bool(a.get("address_key")) and a.get("address_key") == b.get("address_key")
    if (a.get("name") and b.get("name") and same_address
            and jaro_winkler(a["name"], b["name"]) >= 0.95):
        return 0.90, "fuzzy_name_address"
    return 0.0, "none"


def score_pairs(records: list[dict], pairs: Iterable[tuple[int, int]]) -> list[tuple[str, str, float, str]]:
    """(key_a, key_b, probability, method) for each candidate pair with any evidence."""
    out = []
    for i, j in pairs:
        p, method = match_probability(records[i], records[j])
        if p > 0:
            out.append((records[i]["key"], records[j]["key"], p, method))
    return out


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------
class UnionFind:
    """Union-find over string keys. The smaller root always wins, so the outcome does not depend
    on the order in which links are applied."""

    def __init__(self, keys: Iterable[str]):
        self.parent = {k: k for k in keys}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def stable_entity_id(member_keys: Iterable[str], prefix: str = "ENT") -> str:
    """Id that depends only on the members: hash of the smallest member key."""
    smallest = min(member_keys)
    return f"{prefix}-" + hashlib.sha1(smallest.encode("utf-8")).hexdigest()[:10].upper()


def assign_entities(keys: Iterable[str], links: Iterable[tuple[str, str, float, str]],
                    threshold: float = 0.85) -> list[dict]:
    """Cluster keys over links at or above threshold.

    Returns one row per key: key, entity_id, match_probability (the strongest accepted link that
    touches the key, 1.0 for a record that linked to nothing) and method.
    """
    keys = sorted(set(keys))
    uf = UnionFind(keys)
    accepted = [(a, b, p, m) for a, b, p, m in links if p >= threshold and a != b]
    best: dict[str, tuple[float, str]] = {}
    for a, b, p, m in accepted:
        uf.union(a, b)
        for k in (a, b):
            if k not in best or p > best[k][0]:
                best[k] = (p, m)
    members: dict[str, list[str]] = defaultdict(list)
    for k in keys:
        members[uf.find(k)].append(k)
    rows = []
    for k in keys:
        entity_id = stable_entity_id(members[uf.find(k)])
        prob, method = best.get(k, (1.0, "singleton"))
        rows.append({"key": k, "entity_id": entity_id, "match_probability": float(prob), "method": method})
    return rows


def resolve_records(records: list[dict], threshold: float = 0.85) -> list[dict]:
    """Rules-only resolution: candidate pairs, scoring, clustering. Used when Splink is unavailable."""
    links = score_pairs(records, candidate_pairs(records))
    return assign_entities([r["key"] for r in records], links, threshold)


# ---------------------------------------------------------------------------
# Source systems -> party records
# ---------------------------------------------------------------------------
def _iso(value) -> str | None:
    if value is None:
        return None
    text = str(value)[:10]
    return None if text in ("", "None", "NaT", "nan") else text


_LEGAL_SUFFIX = re.compile(r"\s+(pty\.?\s*ltd\.?|p/l|proprietary limited|limited)\s*$", re.IGNORECASE)


def display_name(raw) -> str:
    """Raw source name without the legal form, in title case when the source shouted it in capitals."""
    text = _LEGAL_SUFFIX.sub("", " ".join(str(raw or "").split())).strip()
    return text.title() if text.isupper() else text


def _party(**fields) -> dict:
    base = {"key": None, "source_system": None, "source_id": None, "kind": None, "name": None,
            "abn": None, "given": None, "family": None, "dob": None, "street": None, "suburb": None,
            "postcode": None, "address_key": None, "director_name": None, "director_address_key": None,
            "phone": None, "email": None, "bank_key": None, "vendor_created": None, "registered": None,
            "registry_status": None, "status_date": None, "display": None}
    base.update(fields)
    base["key"] = f"{base['source_system']}:{base['source_id']}"
    return base


def party_records(master: list[dict], registry: list[dict], claimants: list[dict]) -> list[dict]:
    """One normalised party record per source row, across the three disconnected systems.

    master, registry and claimants are lists of dicts with the bronze column names
    (supplier_master, business_registry and claimant respectively). Records keep their source
    identity; linking them into entities is assign_entities()'s job.
    """
    out = []
    for r in master:
        out.append(_party(
            source_system="supplier_master", source_id=str(r["supplier_src_id"]), kind="supplier",
            name=normalise_name(r.get("supplier_name")), display=display_name(r.get("supplier_name")),
            abn=normalise_abn(r.get("abn_as_entered")),
            street=normalise_street(r.get("street")), suburb=normalise_name(r.get("suburb")),
            postcode=str(r.get("postcode") or ""),
            address_key=normalise_address(r.get("street"), r.get("suburb"), r.get("postcode")),
            director_name=normalise_name(r.get("director_name")),
            director_address_key=normalise_address(r.get("director_street"), r.get("director_suburb"), r.get("director_postcode")),
            phone=normalise_phone(r.get("phone")), email=normalise_email(r.get("email")),
            bank_key=normalise_bank(r.get("bank_bsb"), r.get("bank_account_no")),
            vendor_created=_iso(r.get("vendor_created_date")),
        ))
    for r in registry:
        out.append(_party(
            source_system="business_registry", source_id=str(r["registry_id"]), kind="supplier",
            name=normalise_name(r.get("entity_name")), display=display_name(r.get("entity_name")),
            abn=normalise_abn(r.get("abn")),
            street=normalise_street(r.get("principal_street")), suburb=normalise_name(r.get("principal_suburb")),
            postcode=str(r.get("principal_postcode") or ""),
            address_key=normalise_address(r.get("principal_street"), r.get("principal_suburb"), r.get("principal_postcode")),
            director_name=normalise_name(r.get("director_name")),
            director_address_key=normalise_address(r.get("director_street"), r.get("director_suburb"), r.get("director_postcode")),
            registered=_iso(r.get("registered_date")),
            registry_status=str(r.get("registration_status") or "").strip() or None,
            status_date=_iso(r.get("status_date")),
        ))
    for r in claimants:
        given, family = normalise_name(r.get("given_name")), normalise_name(r.get("family_name"))
        out.append(_party(
            source_system="claimant", source_id=str(r["claimant_src_id"]), kind="claimant",
            name=normalise_name(f"{given} {family}"), given=given, family=family, dob=_iso(r.get("dob")),
            display=display_name(f"{r.get('given_name', '')} {r.get('family_name', '')}"),
            street=normalise_street(r.get("street")), suburb=normalise_name(r.get("suburb")),
            postcode=str(r.get("postcode") or ""),
            address_key=normalise_address(r.get("street"), r.get("suburb"), r.get("postcode")),
            phone=normalise_phone(r.get("phone")), email=normalise_email(r.get("email")),
            bank_key=normalise_bank(r.get("bank_bsb"), r.get("bank_account_no")),
        ))
    return out


# ---------------------------------------------------------------------------
# Entities: attributes per resolved entity, and claimant clusters
# ---------------------------------------------------------------------------
def build_entities(parties: list[dict], xref: list[dict]) -> tuple[list[dict], list[dict]]:
    """Assemble one entity row per resolved entity from its party records.

    Claimant clusters are the connected groups of claimant entities that share a phone, email or
    bank account (graph.components). Suppliers are never clustered: suppliers that share an
    account are separately registered businesses, and the sharing is a graph signal, not identity.
    Returns (entity rows, xref rows with cluster_id added to the entity rows).
    """
    from graph import build_graph, components

    by_key = {p["key"]: p for p in parties}
    members: dict[str, list[dict]] = defaultdict(list)
    for x in xref:
        members[x["entity_id"]].append(by_key[x["key"]])

    nodes, edges = [], []
    for eid, recs in members.items():
        if recs[0]["kind"] != "claimant":
            continue
        pid = f"party:{eid}"
        nodes.append({"id": pid, "kind": "claimant"})
        for rec in recs:
            for attr_kind, value in (("phone", rec["phone"]), ("email", rec["email"]), ("bank_account", rec["bank_key"])):
                if value:
                    aid = f"{attr_kind}:{value}"
                    nodes.append({"id": aid, "kind": attr_kind})
                    edges.append((pid, aid, "shares", 1.0))
    cluster_of: dict[str, str] = {}
    for group in components(build_graph(nodes, edges), ["claimant"], ["phone", "email", "bank_account"]):
        entity_ids = [n[len("party:"):] for n in group]
        cid = stable_entity_id(entity_ids, prefix="CLU")
        for eid in entity_ids:
            cluster_of[eid] = cid

    entities = []
    for eid in sorted(members):
        recs = sorted(members[eid], key=lambda r: r["key"])
        kind = recs[0]["kind"]
        sup = [r for r in recs if r["source_system"] == "supplier_master"]
        reg = [r for r in recs if r["source_system"] == "business_registry"]
        first = lambda field, pool=recs: next((r[field] for r in pool if r.get(field)), None)  # noqa: E731
        cancelled = next((r for r in reg if (r.get("registry_status") or "").lower() == "cancelled"), None)
        label_src = sup[0] if sup else (reg[0] if reg else recs[0])
        entities.append({
            "entity_id": eid,
            "entity_kind": "claimant" if kind == "claimant" else "supplier",
            "cluster_id": cluster_of.get(eid, eid),
            "display_name": label_src.get("display") or "",
            "abn": first("abn", reg) or first("abn", sup),
            "vendor_created": min((r["vendor_created"] for r in sup if r.get("vendor_created")), default=None),
            "registry_status": (cancelled or (reg[0] if reg else {})).get("registry_status"),
            "status_date": (cancelled or (reg[0] if reg else {})).get("status_date"),
            "address_key": first("address_key"),
            "director_name": first("director_name"),
            "director_address_key": first("director_address_key"),
            "dob": first("dob"),
            "source_record_count": len(recs),
        })
    xref_out = []
    for x in xref:
        system, source_id = x["key"].split(":", 1)
        xref_out.append({"source_system": system, "source_id": source_id, "entity_id": x["entity_id"],
                         "cluster_id": cluster_of.get(x["entity_id"], x["entity_id"]),
                         "match_probability": x["match_probability"], "method": x["method"]})
    return entities, xref_out
