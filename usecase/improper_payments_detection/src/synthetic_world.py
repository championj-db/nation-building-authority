"""Seeded, wholly synthetic source systems for the improper payments use case (pandas + numpy).

Everything here is invented. Business names come from word lists and are combined at random, so
they are fictional ("North Harbour Supplies Group"), not real companies. People are drawn from
word lists of given and family names. ABNs are random 11-digit strings and are not checked
against the ABR. Suburbs and postcodes are real Australian places, which is fine; street numbers
and street names are invented.

Four "disconnected systems" are modelled:
  supplier master   the accounts-payable vendor file (duplicates and format drift)
  business registry the ABN register (ABN format drift, legal-name drift, cancelled entries)
  claimant system   claimant records and the claims they lodged (duplicates, shared contacts)
  payments          one ledger over both programmes, with approver and bank account on each row

Improper patterns are injected with ground truth, and benign look-alikes are injected too so that
precision is below one: franchise branches sharing a parent account, households at one address,
new vendors that are legitimate, and cancelled suppliers that were not paid after cancellation.

Determinism: one numpy Generator seeded by the `seed` parameter. Dates are relative to `as_of`,
so the queue always looks current; the structure is the same for a given seed.

This module is pure Python (pandas and numpy only). It must not import pyspark.
"""

from __future__ import annotations

import datetime as dt
import math
import re

import numpy as np
import pandas as pd

WINDOW_DAYS = 548                 # payments span 18 months back from the run date
N_OFFICERS = 400
N_SUPPLIERS = 1600                # true supplier businesses
N_SUPPLIER_DUP_MASTER = 400       # extra supplier-master records for the same businesses
N_REGISTRY_TOTAL = 2500           # business registry rows, including registry-only businesses
N_HOMONYMS = 100                  # registry-only businesses reusing an existing business name
N_PERSONS = 7500                  # true claimants
N_CLAIMANT_DUPS = 500             # extra claimant records for the same people
N_CLAIMS = 25000
N_CLAIMS_PAID = 17000             # claims that produced a payment
N_FAMILIES = 8                    # benign: three people at one address sharing a household phone
N_CONTACT_CLUSTERS = 8            # injected: four to six claimants sharing a phone
N_ASSESSOR_LINKS = 16             # injected: claimant address equals the assessing officer's home

# Supplier plan: (ground-truth code, number of businesses). The rest are ordinary.
SUPPLIER_PLAN = [
    ("shared_bank_account", 25),          # injected, in groups of two or three
    ("benign_franchise_branch", 15),      # benign, in groups of two to four
    ("new_vendor_early_invoice", 20),     # injected
    ("benign_new_vendor", 14),            # benign: created 8-20 days before first invoice
    ("split_below_threshold", 12),        # injected
    ("duplicate_invoice", 15),            # injected
    ("officer_supplier_link", 12),        # injected
    ("cancelled_registration_paid", 20),  # injected
    ("benign_cancelled_inactive", 13),    # benign: cancelled and never paid after
]
INJECTED_SUPPLIER_CODES = {
    "shared_bank_account", "new_vendor_early_invoice", "split_below_threshold",
    "duplicate_invoice", "officer_supplier_link", "cancelled_registration_paid",
}

SUBURBS = [
    ("Parramatta", "2150", "NSW"), ("Bondi", "2026", "NSW"), ("Newcastle", "2300", "NSW"),
    ("Wollongong", "2500", "NSW"), ("Dandenong", "3175", "VIC"), ("Geelong", "3220", "VIC"),
    ("Footscray", "3011", "VIC"), ("Fyshwick", "2609", "ACT"), ("Braddon", "2612", "ACT"),
    ("Toowong", "4066", "QLD"), ("Toowoomba", "4350", "QLD"), ("Cairns", "4870", "QLD"),
    ("Mount Gravatt", "4122", "QLD"), ("Subiaco", "6008", "WA"), ("Fremantle", "6160", "WA"),
    ("Glenelg", "5045", "SA"), ("Modbury", "5092", "SA"), ("Sandy Bay", "7005", "TAS"),
    ("Launceston", "7250", "TAS"), ("Palmerston", "0830", "NT"),
]
STREET_NAMES = [
    "Harbour", "Wattle", "Banksia", "Jacaranda", "Kookaburra", "Ironbark", "Melaleuca", "Bluegum",
    "Sandpiper", "Lorikeet", "Marlin", "Tallowwood", "Ridgeline", "Quarry", "Mill", "Foundry",
]
STREET_TYPES = ["Street", "Road", "Avenue", "Court", "Drive", "Terrace"]

BUSINESS_A = [
    "North Harbour", "Metro Field", "Riverbend", "Coastal Trade", "Southern Cross", "Granite Ridge",
    "Blue Gum", "Eastfield", "Kestrel", "Bayview", "Ironbark", "Sandstone", "Lakeside", "Highland",
    "Wattle Creek", "Pacific Rim", "Summit Peak", "Redgum", "Oakleaf", "Westbrook", "Corella",
    "Tallowood", "Marlin", "Harbourline", "Quarry Hill", "Silverstream", "Northgate",
    "Gumtree Valley", "Tidewater", "Kookaburra",
]
BUSINESS_B = [
    "Supplies", "Field Services", "Maintenance", "Trade Co", "Logistics", "Builders", "Cleaning",
    "Facilities", "Consulting", "Engineering", "Catering", "Security", "Electrical", "Plumbing",
    "Landscaping", "Print Co", "IT Solutions", "Office Fitouts", "Road Services", "Waste Management",
]
BUSINESS_C = ["Group", "Regional", "Metro", "Coastal", "Central", "Australia", "Partners"]

GIVEN_NAMES = [
    "Amelia", "Oliver", "Priya", "Liam", "Mei", "Ethan", "Aroha", "Lucas", "Sienna", "Hamish",
    "Chloe", "Ravi", "Zara", "Mason", "Nadia", "Jack", "Ivy", "Tomasz", "Leah", "Kofi", "Hana",
    "Noah", "Grace", "Sami", "Isla", "Arjun", "Maeve", "Theo", "Yara", "Callum",
]
FAMILY_NAMES = [
    "Harrow", "Tanaka", "Okafor", "Brennan", "Lindqvist", "Mahmoud", "Doherty", "Kowalski",
    "Ferreira", "Nguyen", "Whitcombe", "Sato", "Adeyemi", "Gallagher", "Petrov", "Mitchell",
    "Oduya", "Reyes", "Hartley", "Kaur", "Pemberton", "Yilmaz", "Costa", "Blackwood", "Dunmore",
    "Ashworth", "Iyer", "Quinlan", "Marsh", "Varga",
]
CLAIM_TYPES = ["Workplace injury", "Property damage", "Income support", "Medical expenses", "Travel"]

# Normal payments are drawn so they never land in the $9,000-$9,999 band the split pattern uses.
BAND_LOW, BAND_HIGH = 9000.0, 10000.0


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())[:24]


class _World:
    def __init__(self, seed: int, as_of: dt.date):
        self.rng = np.random.default_rng(seed)
        self.as_of = as_of
        self.start = as_of - dt.timedelta(days=WINDOW_DAYS)
        self.officers: list[dict] = []
        self.suppliers: list[dict] = []
        self.master: list[dict] = []
        self.registry: list[dict] = []
        self.persons: list[dict] = []
        self.claimant_rows: list[dict] = []
        self.claims: list[dict] = []
        self.payments: list[dict] = []

    # -------------------------------------------------------------- primitives
    def _int(self, lo: int, hi: int) -> int:
        """Inclusive integer draw."""
        return int(self.rng.integers(lo, hi + 1))

    def _choice(self, seq):
        return seq[self._int(0, len(seq) - 1)]

    def _date_between(self, lo: dt.date, hi: dt.date) -> dt.date:
        span = max((hi - lo).days, 0)
        return lo + dt.timedelta(days=self._int(0, span))

    def _address(self) -> dict:
        suburb, postcode, state = self._choice(SUBURBS)
        return {
            "street": f"{self._int(1, 240)} {self._choice(STREET_NAMES)} {self._choice(STREET_TYPES)}",
            "suburb": suburb, "state": state, "postcode": postcode,
        }

    def _person_name(self) -> str:
        return f"{self._choice(GIVEN_NAMES)} {self._choice(FAMILY_NAMES)}"

    def _abn(self) -> str:
        return str(self._int(10**10, 10**11 - 1))

    def _phone(self) -> str:
        return f"04{self._int(10**7, 10**8 - 1):08d}"

    def _bank(self) -> dict:
        return {"bsb": f"{self._int(100, 999):03d}-{self._int(100, 999):03d}",
                "account": str(self._int(10**5, 10**9 - 1))}

    @staticmethod
    def _abn_formatted(abn: str, variant: int) -> str:
        if variant == 0:
            return f"{abn[:2]} {abn[2:5]} {abn[5:8]} {abn[8:]}"
        if variant == 1:
            return f"{abn[:2]}-{abn[2:5]}-{abn[5:8]}-{abn[8:]}"
        return abn

    def _amount(self, scale: float) -> float:
        amt = float(np.exp(self.rng.normal(math.log(scale), 0.45)))
        amt = min(max(amt, 120.0), 60000.0)
        if BAND_LOW - 100 <= amt < BAND_HIGH:
            amt -= 1500.0
        return round(amt, 2)

    # -------------------------------------------------------------- officers
    def build_officers(self) -> None:
        roles = np.array(["approver"] * 260 + ["assessor"] * 60 + ["both"] * 80)
        self.rng.shuffle(roles)
        for i in range(N_OFFICERS):
            home = self._address()
            self.officers.append({
                "officer_id": f"OFF-{i + 1:04d}", "officer_name": self._person_name(), "role": str(roles[i]),
                "home_street": home["street"], "home_suburb": home["suburb"],
                "home_state": home["state"], "home_postcode": home["postcode"],
            })
        self.approver_ids = [o["officer_id"] for o in self.officers if o["role"] in ("approver", "both")]
        self.assessors = [o for o in self.officers if o["role"] in ("assessor", "both")]

    def _officer_by_id(self, officer_id: str) -> dict:
        return next(o for o in self.officers if o["officer_id"] == officer_id)

    # -------------------------------------------------------------- suppliers
    def build_suppliers(self) -> None:
        rng = self.rng
        labels: list[str] = []
        for code, n in SUPPLIER_PLAN:
            labels += [code] * n
        labels += ["none"] * (N_SUPPLIERS - len(labels))
        labels = [labels[i] for i in rng.permutation(N_SUPPLIERS)]

        # distinct business names: (A, B, C) combinations, drawn without replacement
        combos = [(a, b, c) for a in BUSINESS_A for b in BUSINESS_B for c in BUSINESS_C]
        pick = rng.permutation(len(combos))
        names = [" ".join(combos[k]) for k in pick[: N_SUPPLIERS + N_REGISTRY_TOTAL]]

        for i, label in enumerate(labels):
            injected = label in INJECTED_SUPPLIER_CODES
            # vendor creation and first invoice
            if label in ("new_vendor_early_invoice", "benign_new_vendor"):
                first_invoice = self._date_between(self.start + dt.timedelta(days=30), self.as_of - dt.timedelta(days=90))
                gap = self._int(3, 20) if label == "new_vendor_early_invoice" else self._int(8, 20)
                created = first_invoice - dt.timedelta(days=gap)
            else:
                first_invoice = None
                created = self.start - dt.timedelta(days=self._int(0, 1500))
            address = self._address()
            director_address = address if rng.random() < 0.3 else self._address()
            bank = self._bank()
            supplier = {
                "key": f"TS-{i + 1:04d}", "pattern": label, "injected": injected,
                "name": names[i], "abn": self._abn(), "phone": self._phone(),
                "slug": _slug(names[i]), "address": address, "director": self._person_name(),
                "director_address": director_address, "bank": bank, "created": created,
                "first_invoice": first_invoice, "in_registry": injected or rng.random() > 0.1,
                "status": "Active", "status_date": None, "group": None, "linked_officer": None,
            }
            self.suppliers.append(supplier)

        self._assign_groups("shared_bank_account", [2, 3], shared=True)
        self._assign_groups("benign_franchise_branch", [2, 3, 4], shared=True)
        self._assign_officer_links()
        self._assign_cancellations()

        # supplier-master and registry rows
        for s in self.suppliers:
            self._master_row(s, duplicate=False)
        for i in rng.choice(N_SUPPLIERS, size=N_SUPPLIER_DUP_MASTER, replace=False):
            self._master_row(self.suppliers[int(i)], duplicate=True)
        for s in self.suppliers:
            if s["in_registry"]:
                self._registry_row(s)
        self._registry_only(names[N_SUPPLIERS:])

    def _assign_groups(self, code: str, sizes: list[int], shared: bool) -> None:
        members = [s for s in self.suppliers if s["pattern"] == code]
        i = 0
        while i < len(members):
            k = self._choice(sizes)
            if len(members) - i - k == 1:
                k += 1
            group = members[i:i + k]
            group_bank = self._bank()
            group_id = f"{code}-{i}"
            for s in group:
                s["group"] = group_id
                if shared:
                    s["bank"] = group_bank
                    s["in_registry"] = True
            i += k

    def _assign_officer_links(self) -> None:
        members = [s for s in self.suppliers if s["pattern"] == "officer_supplier_link"]
        linked = self.rng.choice(self.approver_ids, size=len(members), replace=False)
        for s, officer_id in zip(members, linked):
            o = self._officer_by_id(str(officer_id))
            s["linked_officer"] = o["officer_id"]
            s["director_address"] = {"street": o["home_street"], "suburb": o["home_suburb"],
                                     "state": o["home_state"], "postcode": o["home_postcode"]}

    def _assign_cancellations(self) -> None:
        for s in self.suppliers:
            if s["pattern"] == "cancelled_registration_paid":
                s["status"] = "Cancelled"
                s["status_date"] = self.as_of - dt.timedelta(days=self._int(200, 480))
            elif s["pattern"] == "benign_cancelled_inactive":
                s["status"] = "Cancelled"
                s["status_date"] = self.as_of - dt.timedelta(days=self._int(120, 420))

    def _master_row(self, s: dict, duplicate: bool) -> None:
        variant = self._int(0, 2) if duplicate else 0
        name = s["name"]
        if variant == 0:
            entered = f"{name} Pty Ltd"
        elif variant == 1:
            entered = f"{name.upper()} PTY LTD"
        else:
            entered = f"{name} P/L"
        abn_entered = self._abn_formatted(s["abn"], self._int(0, 2)) if self.rng.random() < 0.7 else None
        address = s["address"]
        street = address["street"].replace("Street", "St").replace("Road", "Rd") if duplicate else address["street"]
        sid = f"SM-{len(self.master) + 1:05d}"
        self.master.append({
            "supplier_src_id": sid, "supplier_name": entered, "trading_name": name,
            "abn_as_entered": abn_entered, "bank_bsb": s["bank"]["bsb"], "bank_account_no": s["bank"]["account"],
            "phone": s["phone"], "email": f"accounts@{s['slug']}.example.com",
            "street": street, "suburb": address["suburb"], "state": address["state"],
            "postcode": address["postcode"], "director_name": s["director"],
            "director_street": s["director_address"]["street"], "director_suburb": s["director_address"]["suburb"],
            "director_state": s["director_address"]["state"], "director_postcode": s["director_address"]["postcode"],
            "vendor_created_date": s["created"], "loaded_date": self.as_of,
            "_key": s["key"], "_dup": duplicate,
        })
        if duplicate:
            s["dup_master"] = sid
        else:
            s["master_src_id"] = sid

    def _registry_row(self, s: dict) -> None:
        legal = self._choice(["Pty. Ltd.", "P/L", "PROPRIETARY LIMITED", "Pty Ltd"])
        entity_name = f"{s['name'].upper() if self.rng.random() < 0.3 else s['name']} {legal}"
        registered = s["created"] - dt.timedelta(days=self._int(30, 400))
        self.registry.append({
            "registry_id": f"BR-{len(self.registry) + 1:05d}", "abn": self._abn_formatted(s["abn"], self._int(0, 2)),
            "entity_name": entity_name, "registration_status": s["status"],
            "status_date": s["status_date"] or registered, "registered_date": registered,
            "principal_street": s["address"]["street"], "principal_suburb": s["address"]["suburb"],
            "principal_state": s["address"]["state"], "principal_postcode": s["address"]["postcode"],
            "director_name": s["director"], "director_street": s["director_address"]["street"],
            "director_suburb": s["director_address"]["suburb"], "director_state": s["director_address"]["state"],
            "director_postcode": s["director_address"]["postcode"],
        })

    def _registry_only(self, spare_names: list[str]) -> None:
        n_only = N_REGISTRY_TOTAL - len(self.registry)
        homonym_sources = self.rng.choice(N_SUPPLIERS, size=N_HOMONYMS, replace=False)
        for j in range(n_only):
            if j < N_HOMONYMS:
                src = self.suppliers[int(homonym_sources[j])]
                name = src["name"]
                address = self._address()
                while address["postcode"] == src["address"]["postcode"]:
                    address = self._address()
            else:
                name = spare_names[j - N_HOMONYMS] if j - N_HOMONYMS < len(spare_names) else f"Registry Only {j}"
                address = self._address()
            legal = self._choice(["Pty Ltd", "PTY. LTD.", "P/L"])
            director = self._person_name()
            self.registry.append({
                "registry_id": f"BR-{len(self.registry) + 1:05d}", "abn": self._abn_formatted(self._abn(), self._int(0, 2)),
                "entity_name": f"{name} {legal}", "registration_status": "Active",
                "status_date": self.as_of - dt.timedelta(days=self._int(0, 2000)),
                "registered_date": self._date_between(self.start - dt.timedelta(days=2000), self.as_of),
                "principal_street": address["street"], "principal_suburb": address["suburb"],
                "principal_state": address["state"], "principal_postcode": address["postcode"],
                "director_name": director, "director_street": address["street"], "director_suburb": address["suburb"],
                "director_state": address["state"], "director_postcode": address["postcode"],
            })

    # -------------------------------------------------------------- claimants
    def build_claimants(self) -> None:
        rng = self.rng
        order = rng.permutation(N_PERSONS)
        roles = {int(i): "ordinary" for i in range(N_PERSONS)}
        pos = 0
        families, clusters, assessor_links = [], [], []
        for f in range(N_FAMILIES):
            members = [int(order[pos + k]) for k in range(3)]
            pos += 3
            families.append(members)
            for m in members:
                roles[m] = "family"
        for c in range(N_CONTACT_CLUSTERS):
            size = self._int(4, 6)
            members = [int(order[pos + k]) for k in range(size)]
            pos += size
            clusters.append(members)
            for m in members:
                roles[m] = "cluster"
        for a in range(N_ASSESSOR_LINKS):
            m = int(order[pos])
            pos += 1
            assessor_links.append(m)
            roles[m] = "assessor_link"

        for i in range(N_PERSONS):
            home = self._address()
            self.persons.append({
                "key": f"TC-{i + 1:05d}", "src": f"CR-{i + 1:05d}", "given": self._choice(GIVEN_NAMES),
                "family": self._choice(FAMILY_NAMES),
                "dob": self._date_between(dt.date(1940, 1, 1), dt.date(2005, 12, 31)),
                "phone": self._phone(), "email": None, "bank": self._bank(), "address": home,
                "role": roles[i], "cluster": None, "family_id": None, "assessor_id": None, "dup_src": None,
            })
            p = self.persons[-1]
            p["email"] = f"{p['given'].lower()}.{p['family'].lower()}{i + 1}@example.net"

        for f, members in enumerate(families):
            household = self._address()
            household_phone = f"02{self._int(10**7, 10**8 - 1):08d}"
            for m in members:
                self.persons[m]["address"] = household
                self.persons[m]["phone"] = household_phone
                self.persons[m]["family_id"] = f"FAM-{f + 1}"
        for c, members in enumerate(clusters):
            cluster_phone = self._phone()
            share_bank = c % 2 == 0
            shared_bank = self._bank()
            for m in members:
                self.persons[m]["phone"] = cluster_phone
                self.persons[m]["cluster"] = f"CL-{c + 1}"
                if share_bank:
                    self.persons[m]["bank"] = shared_bank
        for m in assessor_links:
            self.persons[m]["address"] = {"street": "", "suburb": "", "state": "", "postcode": ""}  # set after claims

        # duplicate claimant records (name drift), used by some claims
        dup_people = rng.choice(N_PERSONS, size=N_CLAIMANT_DUPS, replace=False)
        for j, idx in enumerate(dup_people):
            self.persons[int(idx)]["dup_src"] = f"CR-{N_PERSONS + j + 1:05d}"

        self._persons_meta = {"families": families, "clusters": clusters, "assessor_links": assessor_links}

    def _claimant_rows_out(self) -> None:
        for p in self.persons:
            a = p["address"]
            self.claimant_rows.append({
                "claimant_src_id": p["src"], "given_name": p["given"], "family_name": p["family"],
                "dob": p["dob"], "phone": p["phone"], "email": p["email"], "bank_bsb": p["bank"]["bsb"],
                "bank_account_no": p["bank"]["account"], "street": a["street"], "suburb": a["suburb"],
                "state": a["state"], "postcode": a["postcode"],
            })
            if p["dup_src"]:
                self.claimant_rows.append({
                    "claimant_src_id": p["dup_src"], "given_name": p["given"][:1] + p["given"][1:].lower(),
                    "family_name": p["family"].upper(), "dob": p["dob"],
                    "phone": "+61 " + p["phone"][1:], "email": p["email"].upper(),
                    "bank_bsb": p["bank"]["bsb"], "bank_account_no": p["bank"]["account"],
                    "street": a["street"].replace("Street", "St"), "suburb": a["suburb"], "state": a["state"],
                    "postcode": a["postcode"],
                })

    # -------------------------------------------------------------- claims
    def build_claims(self) -> None:
        rng = self.rng
        meta = self._persons_meta
        for m in meta["assessor_links"]:
            assessor = self.assessors[int(m) % len(self.assessors)]  # spread across assessors
            p = self.persons[m]
            p["assessor_id"] = assessor["officer_id"]
            p["address"] = {"street": assessor["home_street"], "suburb": assessor["home_suburb"],
                            "state": assessor["home_state"], "postcode": assessor["home_postcode"]}

        reserved: list[tuple[int, str | None]] = []   # (person index, forced assessor id or None)
        for members in meta["clusters"]:
            for m in members:
                reserved += [(m, None), (m, None)]
        for m in meta["assessor_links"]:
            reserved += [(m, self.persons[m]["assessor_id"]), (m, self.persons[m]["assessor_id"])]
        reserved_idx = {m for m, _ in reserved}
        n_free = N_CLAIMS - len(reserved)
        free_pool = [i for i in range(N_PERSONS) if i not in reserved_idx]
        free_draw = rng.choice(free_pool, size=n_free, replace=True)
        all_claims = reserved + [(int(m), None) for m in free_draw]
        order = rng.permutation(len(all_claims))
        for n, k in enumerate(order):
            m, forced = all_claims[int(k)]
            p = self.persons[m]
            lodged = self._date_between(self.start, self.as_of - dt.timedelta(days=30))
            assessor_id = forced or self._choice(self.assessors)["officer_id"]
            src = p["dup_src"] if (p["dup_src"] and rng.random() < 0.3) else p["src"]
            amount = float(np.exp(rng.normal(math.log(6000), 1.0)))
            self.claims.append({
                "claim_id": f"CL-{n + 1:07d}", "claimant_src_id": src, "person_idx": m, "person": p["key"],
                "assessor_officer_id": assessor_id, "claim_type": self._choice(CLAIM_TYPES),
                "claim_amount": round(min(max(amount, 300.0), 80000.0), 2),
                "lodged_date": lodged, "claim_status": self._choice(["Assessed", "Closed"]),
            })
        self.claims.sort(key=lambda c: c["claim_id"])

    # -------------------------------------------------------------- payments
    def build_supplier_payments(self) -> None:
        rng = self.rng
        for s in self.suppliers:
            code = s["pattern"]
            scale = float(np.exp(rng.uniform(math.log(800), math.log(9000))))
            if code in ("new_vendor_early_invoice", "benign_new_vendor"):
                dates = [s["first_invoice"]] + sorted(
                    self._date_between(s["first_invoice"], s["first_invoice"] + dt.timedelta(days=60))
                    for _ in range(7))
            elif code == "benign_cancelled_inactive":
                hi = s["status_date"] - dt.timedelta(days=1)
                dates = sorted(self._date_between(max(self.start, s["created"]), hi) for _ in range(10))
            elif code == "cancelled_registration_paid":
                hi = s["status_date"] - dt.timedelta(days=1)
                before = [self._date_between(max(self.start, s["created"]), hi) for _ in range(10)]
                after = [self._date_between(s["status_date"] + dt.timedelta(days=1), self.as_of - dt.timedelta(days=1))
                         for _ in range(8)]
                dates = sorted(before + after)
            else:
                lo = max(self.start, s["created"]) + dt.timedelta(days=1)
                dates = sorted(self._date_between(lo, self.as_of - dt.timedelta(days=1))
                               for _ in range(self._int(15, 40)))

            for d in dates:
                approver = self._choice(self.approver_ids)
                if code == "officer_supplier_link" and rng.random() < 0.7:
                    approver = s["linked_officer"]
                truth = "none"
                improper = False
                if code == "benign_franchise_branch":
                    truth = code
                elif code == "benign_new_vendor" or code == "benign_cancelled_inactive":
                    truth = code
                elif code == "new_vendor_early_invoice":
                    truth, improper = code, True
                elif code == "shared_bank_account":
                    truth, improper = code, True
                elif code == "cancelled_registration_paid" and d > s["status_date"]:
                    truth, improper = code, True
                elif code == "officer_supplier_link" and approver == s["linked_officer"]:
                    truth, improper = code, True
                self._add_payment(s, d, self._amount(scale), approver, truth, improper)

            if code == "split_below_threshold":
                anchor = self._date_between(self.start + dt.timedelta(days=60), self.as_of - dt.timedelta(days=20))
                for k in range(self._int(4, 6)):
                    d = anchor + dt.timedelta(days=self._int(0, 10))
                    amt = round(float(rng.uniform(9000, 9990)), 2)
                    self._add_payment(s, d, amt, self._choice(self.approver_ids), code, True)

            if code == "duplicate_invoice":
                originals = [p for p in self.payments if p["entity"] == s["key"] and p["truth"] == "none"]
                for orig in rng.choice(len(originals), size=min(4, len(originals)), replace=False):
                    o = originals[int(orig)]
                    d = o["payment_date"] + dt.timedelta(days=self._int(1, 6))
                    d = min(d, self.as_of - dt.timedelta(days=1))
                    amt = round(o["amount"] * (1 + float(rng.uniform(-0.004, 0.004))), 2)
                    ref = o["invoice_ref"]
                    digits = re.sub(r"\D", "", ref)
                    variant = self._int(0, 2)
                    dup_ref = [f"INV{d.year}{digits[-6:]}", f"inv {d.year}-{digits[-4:]}", f"INV-{d.year}-{digits[-6:]} "][variant]
                    self._add_payment(s, d, amt, o["approver"], code, True, invoice_ref=dup_ref,
                                      bank=o["bank_obj"], payee=o["payee"])

    def _add_payment(self, s, d, amount, approver, truth, improper, invoice_ref=None, bank=None, payee=None) -> None:
        if payee is None:
            payee = s.get("dup_master") if (s.get("dup_master") and self.rng.random() < 0.25) else s.get("master_src_id")
        bank = bank or s["bank"]
        ref = invoice_ref or f"INV-{d.year}-{self._int(100000, 999999)}"
        self.payments.append({
            "payee_src_id": payee, "program": "supplier", "amount": round(float(amount), 2),
            "payment_date": d, "invoice_ref": ref, "approver": approver,
            "bank_bsb": bank["bsb"], "bank_account_no": bank["account"], "bank_obj": bank,
            "entity": s["key"], "truth": truth, "improper": improper, "payee": payee,
        })

    def build_claim_payments(self) -> None:
        rng = self.rng
        reserved_claims = {c["claim_id"] for c in self.claims
                           if self.persons[c["person_idx"]]["role"] in ("cluster", "assessor_link")}
        rest = [c["claim_id"] for c in self.claims if c["claim_id"] not in reserved_claims]
        n_more = max(N_CLAIMS_PAID - len(reserved_claims), 0)
        chosen = reserved_claims | set(rng.choice(rest, size=min(n_more, len(rest)), replace=False).tolist())
        by_id = {c["claim_id"]: c for c in self.claims}
        for cid in sorted(chosen):
            c = by_id[cid]
            p = self.persons[c["person_idx"]]
            lodged = c["lodged_date"]
            d = min(lodged + dt.timedelta(days=self._int(14, 70)), self.as_of - dt.timedelta(days=1))
            amt = round(c["claim_amount"] * float(rng.uniform(0.7, 1.0)), 2)
            if p["role"] == "cluster":
                truth, improper = "claimant_contact_reuse", True
            elif p["role"] == "assessor_link" and c["assessor_officer_id"] == p["assessor_id"]:
                truth, improper = "claimant_assessor_address", True
            elif p["role"] == "family":
                truth, improper = "benign_family_address", False
            else:
                truth, improper = "none", False
            self.payments.append({
                "payee_src_id": c["claimant_src_id"], "program": "claims", "amount": amt, "payment_date": d,
                "invoice_ref": c["claim_id"], "approver": self._choice(self.approver_ids),
                "bank_bsb": p["bank"]["bsb"], "bank_account_no": p["bank"]["account"], "bank_obj": p["bank"],
                "entity": p["key"], "truth": truth, "improper": improper, "payee": c["claimant_src_id"],
            })

    # -------------------------------------------------------------- output
    def tables(self) -> dict[str, pd.DataFrame]:
        self._claimant_rows_out()
        pay = pd.DataFrame(self.payments)
        pay = pay.sort_values(["payment_date", "entity", "invoice_ref"], kind="mergesort").reset_index(drop=True)
        pay.insert(0, "payment_id", [f"PAY-{i + 1:08d}" for i in range(len(pay))])
        ground = pay[["payment_id", "entity", "truth", "improper"]].rename(
            columns={"entity": "entity_id", "truth": "pattern_code", "improper": "is_improper"})
        payment = pay[["payment_id", "payee_src_id", "program", "amount", "payment_date", "invoice_ref",
                       "approver", "bank_bsb", "bank_account_no"]].rename(
            columns={"payee_src_id": "payee_src_id", "approver": "approver_officer_id"})

        master = pd.DataFrame(self.master).drop(columns=["_key", "_dup"])
        registry = pd.DataFrame(self.registry)
        claimants = pd.DataFrame(self.claimant_rows)
        claims = pd.DataFrame(self.claims).drop(columns=["person", "person_idx"])
        officers = pd.DataFrame(self.officers)
        return {
            "bronze_supplier_master": master,
            "bronze_business_registry": registry,
            "bronze_claimant": claimants,
            "bronze_claim": claims,
            "bronze_officer": officers,
            "bronze_payment": payment,
            "bronze_ground_truth": ground,
        }


def generate(seed: int, as_of: dt.date) -> dict[str, pd.DataFrame]:
    """Build every bronze source table for one seed and run date. Same inputs, same tables."""
    w = _World(seed, as_of)
    w.build_officers()
    w.build_suppliers()
    w.build_claimants()
    w.build_claims()
    w.build_supplier_payments()
    w.build_claim_payments()
    return w.tables()
