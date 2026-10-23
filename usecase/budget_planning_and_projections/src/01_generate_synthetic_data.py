# Databricks notebook source
# MAGIC %md
# MAGIC # 01 Generate synthetic source extracts
# MAGIC
# MAGIC Builds a **wholly synthetic** national infrastructure portfolio and lands it in the landing volume as
# MAGIC the raw extracts that real source systems would deliver. Nothing here is real budget, project or
# MAGIC market data. The portfolio shape follows the public structure of Infrastructure Australia's
# MAGIC Major Public Infrastructure Pipeline (sectors, programs, projects, multi-year cost profiles, market
# MAGIC capacity categories) and the Gateway Reviews delivery-confidence scale.
# MAGIC
# MAGIC | Extract (landing folder) | Simulated source system | Format |
# MAGIC | --- | --- | --- |
# MAGIC | `programs`, `projects` | Portfolio register (pipeline) | CSV |
# MAGIC | `plan_versions`, `plan_phasing` | Budget system - endorsed plan monthly phasing | CSV |
# MAGIC | `gl_transactions`, `suppliers` | Financial system - general ledger postings (monthly deliveries) | CSV |
# MAGIC | `change_register` | Project controls - schedule, scope and packaging change requests | JSON |
# MAGIC | `gateway_reviews` | Assurance - Gateway review reports | JSON |
# MAGIC | `assumptions_register`, `escalation_rates`, `funding_envelope` | Portfolio economics and budget strategy | JSON / CSV |
# MAGIC | `capacity_categories`, `market_capacity`, `demand_intensity` | Market capacity model | CSV |
# MAGIC | `scenario_definitions`, `scenario_levers` | Planning office - seeded scenarios | JSON |
# MAGIC
# MAGIC `dbldatagen` generates the high-volume and attribute-rich data (ledger postings, suppliers, project
# MAGIC attributes). Financial structure (S-curve phasing, drivers, capacity calibration) uses the shared
# MAGIC engine in `_common` so the forecast can only explain the world through drivers recorded as data.
# MAGIC
# MAGIC **Modes.** `bootstrap` anchors the world on `world_anchor_date` (default today), stores the anchor and
# MAGIC seed, and lands every extract. `incremental` rebuilds the identical world from the stored anchor and
# MAGIC lands only general-ledger months that have closed since the last delivery (monthly actuals feed).

# COMMAND ----------

# MAGIC %pip install -q dbldatagen==0.4.0.post1

# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "")
dbutils.widgets.text("volume", "landing")
dbutils.widgets.text("seed", "42")
dbutils.widgets.dropdown("mode", "bootstrap", ["bootstrap", "incremental"])
dbutils.widgets.text("world_anchor_date", "")
dbutils.widgets.text("as_of_date", "")
dbutils.widgets.text("actuals_lag_days", "3")
dbutils.widgets.text("txn_per_project_month", "150")
dbutils.widgets.text("endorsed_window_target_aud_bn", "171.8")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
volume = dbutils.widgets.get("volume")
mode = dbutils.widgets.get("mode")
lag_days = int(dbutils.widgets.get("actuals_lag_days"))
txn_per_pm = int(dbutils.widgets.get("txn_per_project_month"))
window_target_m = float(dbutils.widgets.get("endorsed_window_target_aud_bn")) * 1000.0

# COMMAND ----------

# MAGIC %run ./_common

# COMMAND ----------

import dbldatagen as dg
import dbldatagen.distributions as dist

today = datetime.now(timezone.utc).date()
if mode == "bootstrap":
    seed = int(dbutils.widgets.get("seed"))
    anchor = date.fromisoformat(dbutils.widgets.get("world_anchor_date")) if dbutils.widgets.get("world_anchor_date") else today
    set_control("world_anchor_date", anchor.isoformat())
    set_control("seed", seed)
    set_control("gl_last_landed_month", "")
else:
    stored = get_control("world_anchor_date")
    assert stored, "No synthetic world anchor recorded - run the bootstrap job first"
    anchor, seed = date.fromisoformat(stored), int(get_control("seed"))

as_of = date.fromisoformat(dbutils.widgets.get("as_of_date")) if dbutils.widgets.get("as_of_date") else max(today, anchor)
if mode == "bootstrap":
    as_of = anchor

anchor_actuals_through = actuals_through_for(anchor, lag_days)
T0 = month_idx(anchor_actuals_through) + 1                    # first forecast month at the anchor
H0 = int(FY_OF_MONTH[T0])                                       # first financial year of the planning horizon
S = month_idx(fy_start(H0))                                     # first month of the horizon
HORIZON = list(range(H0, H0 + 5))
WINDOW = np.isin(FY_OF_MONTH, HORIZON)
land_through = actuals_through_for(as_of, lag_days)
rng = np.random.default_rng(seed)
print(f"mode={mode} seed={seed} anchor={anchor} as_of={as_of} horizon={fy_label(H0)}-{fy_label(H0 + 4)} "
      f"anchor actuals through {anchor_actuals_through}, landing GL through {land_through}")


def rel(days: int) -> date:
    """A business date relative to the world anchor (keeps the story stable for any anchor)."""
    return anchor + timedelta(days=int(days))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Portfolio register: programs and projects
# MAGIC
# MAGIC Five programs carry the stories visible in the design (Eastern Transit Corridor labour exposure,
# MAGIC North Grid Resilience long-lead equipment delay, Regional Water Security packaging saving, Western
# MAGIC Freight Link unexplained variance, Metro Renewal labour demand). The remaining programs and their
# MAGIC project attributes are generated with dbldatagen.

# COMMAND ----------

PROGRAMS = [
    # id, name, sector, subsector, jurisdictions, agency, mid(months from horizon start), mid_sd, dur_lo, dur_hi, pinned components
    dict(id="PRG-ETC", name="Eastern Transit Corridor", sector="Transport", subsector="Urban rail", juris=["NSW"],
         agency="Eastern Transit Delivery Authority", mid=42, sd=17, dur=(100, 158), window_target=18_400.0,
         components=["Enabling Works", "Twin-Bore Tunnels", "Underground Stations", "Elevated Viaduct",
                     "Rail Systems & Signalling", "Rolling Stock", "Stabling & Maintenance Facility",
                     "Interchange Precincts", "Operations Readiness"]),
    dict(id="PRG-RWS", name="Regional Water Security", sector="Water", subsector="Bulk water", juris=["QLD"],
         agency="Regional Water Infrastructure Office", mid=38, sd=19, dur=(64, 115), window_target=9_600.0,
         components=["Burdekin Weir Raising", "Southern Downs Pipeline", "Fitzroy Off-Stream Storage",
                     "Mary Valley Treatment Upgrade", "Wide Bay Interconnector", "Western Downs Bore Network"]),
    dict(id="PRG-NGR", name="North Grid Resilience", sector="Energy", subsector="Transmission", juris=["VIC"],
         agency="National Grid Delivery Office", mid=44, sd=14, dur=(64, 115), window_target=14_100.0,
         components=["Western Victoria 500 kV Line", "Gippsland Terminal Station", "Murray Interconnector Upgrade",
                     "Ballarat Substation Rebuild", "North-West Synchronous Condensers", "Bendigo 220 kV Augmentation",
                     "Latrobe Grid Battery Connection", "Shepparton Transformer Replacement", "Mildura Network Hardening",
                     "Geelong Cable Tunnel", "Wodonga Switchyard Upgrade", "Grid Control System Modernisation"]),
    dict(id="PRG-WFL", name="Western Freight Link", sector="Transport", subsector="Freight rail", juris=["WA"],
         agency="Western Freight Projects Office", mid=40, sd=14, dur=(57, 100), window_target=6_400.0,
         components=["Kwinana Intermodal Terminal", "Avon Valley Rail Duplication", "Perth-Kalgoorlie Passing Loops",
                     "Fremantle Port Rail Link"]),
    dict(id="PRG-MTR", name="Metro Renewal", sector="Transport", subsector="Urban rail", juris=["VIC"],
         agency="Metropolitan Rail Renewal Authority", mid=40, sd=22, dur=(64, 115), window_target=8_900.0,
         components=["Signalling Upgrade (CBTC)", "Station Accessibility Upgrades", "Track & Turnout Renewal",
                     "Level Crossing Removals Package 3", "Traction Power Upgrade"]),
    # generated programs: n projects, attributes from dbldatagen
    dict(id="PRG-IHU", name="Inland Highway Upgrades", sector="Transport", subsector="Roads", juris=["QLD", "NSW"], n=7,
         agency="Inland Roads Program Office", mid=36, sd=29, dur=(57, 115)),
    dict(id="PRG-RRS", name="Regional Roads Safety Package", sector="Transport", subsector="Roads", juris=["NSW", "VIC", "SA"], n=6,
         agency="Road Safety Investment Office", mid=28, sd=24, dur=(43, 86)),
    dict(id="PRG-PCE", name="Port Capacity Expansion", sector="Transport", subsector="Ports", juris=["SA", "QLD"], n=3,
         agency="Ports Development Office", mid=42, sd=19, dur=(57, 100)),
    dict(id="PRG-NAF", name="Northern Australia Freight Roads", sector="Transport", subsector="Roads", juris=["NT", "WA", "QLD"], n=4,
         agency="Northern Infrastructure Office", mid=38, sd=24, dur=(57, 100)),
    dict(id="PRG-BRP", name="Bridges Renewal Program", sector="Transport", subsector="Roads", juris=["TAS", "NSW", "VIC"], n=3,
         agency="Inland Roads Program Office", mid=26, sd=17, dur=(43, 72)),
    dict(id="PRG-REZ", name="Renewable Energy Zone Connections", sector="Energy", subsector="Transmission", juris=["NSW", "QLD"], n=6,
         agency="National Grid Delivery Office", mid=48, sd=19, dur=(64, 115)),
    dict(id="PRG-PHS", name="Pumped Hydro & Storage", sector="Energy", subsector="Generation & storage", juris=["TAS", "NSW"], n=3,
         agency="Energy Storage Delivery Office", mid=50, sd=17, dur=(100, 158)),
    dict(id="PRG-CDS", name="Coastal Desalination", sector="Water", subsector="Desalination", juris=["WA", "SA"], n=3,
         agency="Regional Water Infrastructure Office", mid=42, sd=19, dur=(57, 100)),
    dict(id="PRG-UWR", name="Urban Water Recycling", sector="Water", subsector="Wastewater & recycling", juris=["VIC", "ACT"], n=4,
         agency="Urban Water Projects Office", mid=34, sd=22, dur=(50, 100)),
    dict(id="PRG-RHR", name="Regional Hospitals Renewal", sector="Social", subsector="Health", juris=["NSW", "QLD", "WA", "SA", "TAS"], n=6,
         agency="Health Infrastructure Delivery Office", mid=34, sd=24, dur=(50, 86)),
    dict(id="PRG-STB", name="Schools & TAFE Build", sector="Social", subsector="Education", juris=["VIC", "QLD", "NT"], n=5,
         agency="Education Infrastructure Office", mid=28, sd=19, dur=(36, 72)),
]
PINNED = {p["id"] for p in PROGRAMS if "components" in p}

PLACES = {
    "NSW": ["Dubbo", "Tamworth", "Wagga Wagga", "Orange", "Armidale", "Port Macquarie", "Goulburn", "Lismore", "Bathurst"],
    "VIC": ["Ballarat", "Bendigo", "Geelong", "Shepparton", "Mildura", "Warrnambool", "Traralgon", "Wodonga"],
    "QLD": ["Toowoomba", "Rockhampton", "Mackay", "Townsville", "Bundaberg", "Emerald", "Gympie", "Mount Isa"],
    "WA": ["Geraldton", "Bunbury", "Kalgoorlie", "Albany", "Port Hedland", "Karratha", "Northam"],
    "SA": ["Whyalla", "Port Augusta", "Mount Gambier", "Murray Bridge", "Port Lincoln"],
    "TAS": ["Launceston", "Devonport", "Burnie", "Huonville"],
    "NT": ["Katherine", "Tennant Creek", "Alice Springs", "Nhulunbuy"],
    "ACT": ["Belconnen", "Tuggeranong", "Gungahlin"],
}
ASSETS = {
    "Roads": ["Highway Duplication", "Bypass", "Corridor Upgrade", "Interchange", "Freight Route Sealing", "Bridge Replacement", "Safety Upgrade"],
    "Ports": ["Berth Extension", "Channel Deepening", "Container Terminal Expansion"],
    "Transmission": ["330 kV Transmission Line", "Terminal Station", "REZ Network Connection", "Substation Upgrade"],
    "Generation & storage": ["Pumped Hydro Scheme", "Grid-Scale Battery", "Hydro Refurbishment"],
    "Desalination": ["Desalination Plant", "Desalination Plant Expansion"],
    "Wastewater & recycling": ["Recycled Water Plant", "Sewer Trunk Main", "Treatment Plant Upgrade"],
    "Health": ["Base Hospital Redevelopment", "Regional Cancer Centre", "Mental Health Unit", "Emergency Department Expansion"],
    "Education": ["TAFE Trade Training Centre", "Secondary College", "Regional Campus"],
}
TEC_MEDIAN_M = {"Urban rail": 2600, "Freight rail": 1100, "Roads": 750, "Ports": 900, "Transmission": 1200,
                "Generation & storage": 1800, "Bulk water": 900, "Desalination": 1300, "Wastewater & recycling": 600,
                "Health": 700, "Education": 260}

# dbldatagen: attribute-rich rows for the generated programs' projects.
n_generated = sum(p.get("n", 0) for p in PROGRAMS if p["id"] not in PINNED)
attr_spec = (
    dg.DataGenerator(spark, name="project_attributes", rows=n_generated, partitions=1, randomSeed=seed,
                     randomSeedMethod="hash_fieldname")
    .withIdOutput()
    .withColumn("delivery_model", "string", values=["Alliance", "Design & Construct", "Early Contractor Involvement",
                                                     "Managed Contractor", "Public Private Partnership"],
                weights=[25, 35, 20, 12, 8], random=True)
    .withColumn("priority_tier", "int", values=[1, 2, 3], weights=[25, 50, 25], random=True)
    .withColumn("schedule_flexibility", "string", values=["Fixed", "Deferrable"], weights=[50, 50], random=True)
    .withColumn("region_type", "string", values=["Metropolitan", "Regional", "Remote"], weights=[25, 60, 15], random=True)
    .withColumn("funding_source", "string", values=["Commonwealth", "Co-funded 50:50", "Co-funded 80:20", "State-led with Commonwealth contribution"],
                weights=[30, 35, 25, 10], random=True)
    .withColumn("place_u", "double", minValue=0.0, maxValue=0.9999, random=True)
    .withColumn("asset_u", "double", minValue=0.0, maxValue=0.9999, random=True)
    .withColumn("juris_u", "double", minValue=0.0, maxValue=0.9999, random=True)
    .withColumn("bcr", "double", minValue=0.8, maxValue=3.4, distribution=dist.Gamma(2.5, 1.0), random=True)
)
attrs = attr_spec.build().orderBy("id").toPandas()

rows, used_names, a_i = [], set(), 0
for prog in PROGRAMS:
    if prog["id"] in PINNED:
        for comp in prog["components"]:
            rows.append(dict(program_id=prog["id"], project_name=f"{prog['name']} - {comp}", jurisdiction=prog["juris"][0],
                             delivery_model=None, priority_tier=None, schedule_flexibility=None, region_type=None,
                             funding_source=None, bcr=None))
        continue
    for _ in range(prog["n"]):
        a = attrs.iloc[a_i]; a_i += 1
        juris = prog["juris"][int(a.juris_u * len(prog["juris"]))]
        places, assets = PLACES[juris], ASSETS[prog["subsector"]]
        k = int(a.place_u * len(places))
        name = f"{places[k]} {assets[int(a.asset_u * len(assets))]}"
        while name in used_names:  # keep names unique and deterministic
            k = (k + 1) % len(places)
            name = f"{places[k]} {assets[int(a.asset_u * len(assets))]}"
        used_names.add(name)
        rows.append(dict(program_id=prog["id"], project_name=name, jurisdiction=juris, delivery_model=a.delivery_model,
                         priority_tier=int(a.priority_tier), schedule_flexibility=a.schedule_flexibility,
                         region_type=a.region_type, funding_source=a.funding_source, bcr=round(float(a.bcr), 2)))

projects = pd.DataFrame(rows)
projects.insert(0, "project_id", [f"PRJ-{i + 1:04d}" for i in range(len(projects))])
prog_by_id = {p["id"]: p for p in PROGRAMS}
projects["sector"] = projects.program_id.map(lambda x: prog_by_id[x]["sector"])
projects["subsector"] = projects.program_id.map(lambda x: prog_by_id[x]["subsector"])
projects["delivery_agency"] = projects.program_id.map(lambda x: prog_by_id[x]["agency"])

# Pinned program attributes (the design stories).
PINNED_ATTRS = {
    "PRG-ETC": dict(delivery_model="Alliance", priority_tier=1, schedule_flexibility="Fixed", region_type="Metropolitan", funding_source="Co-funded 50:50", bcr=1.42),
    "PRG-RWS": dict(delivery_model="Early Contractor Involvement", priority_tier=1, schedule_flexibility="Deferrable", region_type="Regional", funding_source="Co-funded 80:20", bcr=2.08),
    "PRG-NGR": dict(delivery_model="Design & Construct", priority_tier=1, schedule_flexibility="Fixed", region_type="Regional", funding_source="Commonwealth", bcr=1.87),
    "PRG-WFL": dict(delivery_model="Design & Construct", priority_tier=2, schedule_flexibility="Deferrable", region_type="Regional", funding_source="Co-funded 50:50", bcr=1.31),
    "PRG-MTR": dict(delivery_model="Alliance", priority_tier=2, schedule_flexibility="Deferrable", region_type="Metropolitan", funding_source="Co-funded 50:50", bcr=1.56),
}
for pid, attrs_ in PINNED_ATTRS.items():
    m = projects.program_id == pid
    for k, v in attrs_.items():
        projects.loc[m, k] = v
projects["priority_tier"] = projects["priority_tier"].astype(int)
print(f"{len(projects)} projects across {len(PROGRAMS)} programs")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Schedules, cost estimates and the endorsed plan
# MAGIC
# MAGIC Each project gets a baseline start, duration and S-curve. Total estimated cost (P50) is drawn from a
# MAGIC subsector lognormal and then calibrated so the endorsed plan over the five-year horizon matches the
# MAGIC configured envelope (and each design program matches its story).

# COMMAND ----------

sched = []
for r in projects.itertuples():
    prog = prog_by_id[r.program_id]
    lo, hi = prog["dur"]
    for _ in range(50):
        dur = int(rng.integers(lo, hi + 1))
        mid = S + prog["mid"] + rng.normal(0, prog["sd"])
        start = int(round(mid - dur / 2))
        if start + dur - 1 >= T0 + 12 and start <= S + 48 and start >= 0:  # active and inside the planning window
            break
    sched.append(dict(project_id=r.project_id, start_idx=start, duration=dur,
                      beta_a=round(float(rng.uniform(1.8, 2.6)), 3), beta_b=round(float(rng.uniform(2.2, 3.2)), 3),
                      tec_raw=float(TEC_MEDIAN_M[r.subsector] * rng.lognormal(0, 0.45))))
projects = projects.merge(pd.DataFrame(sched), on="project_id")

unit_paths = {r.project_id: s_curve(1.0, r.start_idx, r.duration, r.beta_a, r.beta_b) for r in projects.itertuples()}
projects["window_share"] = projects.project_id.map(lambda p: unit_paths[p][WINDOW].sum())

pinned_target = 0.0
for prog in PROGRAMS:
    m = projects.program_id == prog["id"]
    if prog["id"] in PINNED:
        k = prog["window_target"] / (projects.loc[m, "tec_raw"] * projects.loc[m, "window_share"]).sum()
        projects.loc[m, "tec_p50_m"] = projects.loc[m, "tec_raw"] * k
        pinned_target += prog["window_target"]
m = ~projects.program_id.isin(PINNED)
k = (window_target_m - pinned_target) / (projects.loc[m, "tec_raw"] * projects.loc[m, "window_share"]).sum()
projects.loc[m, "tec_p50_m"] = projects.loc[m, "tec_raw"] * k
projects["tec_p50_m"] = projects["tec_p50_m"].round(1)
projects["tec_p90_m"] = (projects["tec_p50_m"] * rng.uniform(1.12, 1.32, len(projects))).round(1)
projects["contingency_pct"] = rng.uniform(8, 18, len(projects)).round(1)
projects["baseline_start"] = projects.start_idx.map(month_start)
projects["baseline_finish"] = (projects.start_idx + projects.duration - 1).map(month_end)


def lifecycle(r):
    if r.start_idx > T0 + 12:
        return "Planning"
    if r.start_idx > T0:
        return "Procurement"
    progress = unit_paths[r.project_id][:T0].sum()
    return "Commissioning" if progress >= 0.9 else "Delivery"


projects["lifecycle_stage"] = [lifecycle(r) for r in projects.itertuples()]
projects["benefits_pv_m"] = (projects.bcr * projects.tec_p50_m * rng.uniform(0.8, 0.9, len(projects))).round(1)
projects["benefit_category"] = projects.sector.map({"Transport": "Travel time and freight productivity", "Energy": "Reliability and lower wholesale prices",
                                                    "Water": "Water security and drought resilience", "Social": "Service access and outcomes"})
projects["commonwealth_share_pct"] = projects.funding_source.map({"Commonwealth": 100.0, "Co-funded 50:50": 50.0, "Co-funded 80:20": 80.0,
                                                                   "State-led with Commonwealth contribution": 30.0})
plan = {r.project_id: unit_paths[r.project_id] * r.tec_p50_m for r in projects.itertuples()}
print(f"Endorsed plan {fy_label(H0)}-{fy_label(H0 + 4)}: ${sum(p[WINDOW].sum() for p in plan.values()) / 1000:,.1f}bn")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Economic assumptions, true drivers and the change register
# MAGIC
# MAGIC The world's "truth" is a set of drivers per project: schedule slip and delay cost, approved scope
# MAGIC and packaging changes, escalation above the endorsed assumption, and an unrecorded cost-performance
# MAGIC drift (`u`). Everything except `u` is recorded in source extracts; `u` only shows up in actuals, which
# MAGIC is what the variance report surfaces as **unexplained**.

# COMMAND ----------

SECTOR_CODES = {"Transport": "TRN", "Energy": "ENE", "Water": "WAT", "Social": "SOC"}
ENDORSED_ESC = {"Transport": 0.032, "Energy": 0.034, "Water": 0.030, "Social": 0.030}
CURRENT_ESC = {  # horizon years 1..5, then long-run
    "Transport": [0.068, 0.060, 0.050, 0.042, 0.036, 0.033],
    "Energy": [0.072, 0.064, 0.054, 0.044, 0.038, 0.035],
    "Water": [0.044, 0.040, 0.036, 0.033, 0.031, 0.030],
    "Social": [0.048, 0.043, 0.038, 0.034, 0.031, 0.030],
}
esc_rows = []
for sector, cur in CURRENT_ESC.items():
    for fy in range(H0 - 3, H0 + 10):
        i = fy - H0
        esc_rows.append(dict(assumption_id=f"ESC-{SECTOR_CODES[sector]}", sector=sector, fy=fy, financial_year=fy_label(fy),
                             endorsed_rate=ENDORSED_ESC[sector],
                             current_rate=ENDORSED_ESC[sector] if i < 0 else cur[min(i, len(cur) - 1)]))
escalation = pd.DataFrame(esc_rows)
cpi = [0.029, 0.026, 0.025, 0.025, 0.025, 0.025]
deflator = pd.DataFrame([dict(assumption_id="CPI-DEF", fy=fy, financial_year=fy_label(fy), cpi_rate=cpi[min(max(fy - H0, 0), 5)])
                         for fy in range(H0 - 3, H0 + 10)])
esc_factor = {s: escalation_factor_by_month(escalation, s, H0) for s in CURRENT_ESC}

DELAY_COST_RATE = 0.0025  # share of P50 per month of slip (preliminaries, extended overheads)
STORY = {  # program -> (slip months, scope share, packaging share, u)
    "PRG-ETC": (6, 0.045, 0.0, 0.040),
    "PRG-NGR": (11, 0.0, 0.0, 0.020),
    "PRG-RWS": (0, 0.0, -0.075, -0.020),
    "PRG-WFL": (4, 0.030, 0.0, 0.110),
    "PRG-MTR": (3, 0.010, 0.0, 0.010),
}
SLIP_REASON = {
    "Transport": ["Skilled labour shortfall on civil packages", "Utility relocation delays", "Planning approval conditions", "Geotechnical conditions"],
    "Energy": ["Long-lead transformer and switchgear delivery", "Easement and access negotiations", "Outage window availability"],
    "Water": ["Wet-weather delays", "Environmental approval conditions", "Pipe supply lead times"],
    "Social": ["Design development and user group changes", "Trade availability in regional markets"],
}
SCOPE_REASON = {
    "Transport": ["Additional station entrance and concourse", "Network integration works added", "Extended noise walls and urban design"],
    "Energy": ["Additional bay and protection upgrades", "Network hardening for bushfire risk"],
    "Water": ["Additional treatment stage", "Extended reticulation"],
    "Social": ["Additional clinical services", "Expanded learning spaces"],
}

drivers, changes, cr_seq = [], [], 0


def add_change(r, change_type, amount, months, description, status="Approved", approved_days=None):
    global cr_seq
    cr_seq += 1
    raised = rel(-int(rng.integers(30, 240)))
    approved = rel(approved_days if approved_days is not None else -int(rng.integers(5, 25))) if status == "Approved" else None
    if approved is not None and approved < raised:
        raised = approved - timedelta(days=int(rng.integers(14, 60)))
    changes.append(dict(change_id=f"CR-{cr_seq:05d}", project_id=r.project_id, change_type=change_type,
                        description=description, cost_impact_aud=round(amount * 1e6, 0), schedule_impact_months=int(months),
                        status=status, raised_date=raised.isoformat(), approved_date=approved.isoformat() if approved else None,
                        approver="Portfolio Investment Committee" if status == "Approved" else None,
                        source_system="Project controls"))


for r in projects.itertuples():
    if r.program_id in STORY:
        slip, scope_s, pack_s, u = STORY[r.program_id]
        slip = max(0, int(round(slip + rng.normal(0, 1.5)))) if slip else 0
        u = u + rng.normal(0, 0.006)
    else:
        slip = int(rng.choice([0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 8, 10]))
        scope_s = float(rng.uniform(0.01, 0.07)) if rng.random() < 0.40 else 0.0
        pack_s = -float(rng.uniform(0.01, 0.03)) if rng.random() < 0.12 else 0.0
        u = float(rng.normal(0.012, 0.022))
    in_future = plan[r.project_id][T0:].sum() > 0.05 * r.tec_p50_m
    if not in_future:
        slip, scope_s, pack_s = 0, 0.0, 0.0
    delay = slip * DELAY_COST_RATE * r.tec_p50_m
    if slip:
        add_change(r, "Schedule", delay, slip, rng.choice(SLIP_REASON[r.sector]))
    if scope_s:
        add_change(r, "Scope", scope_s * r.tec_p50_m, 0, rng.choice(SCOPE_REASON[r.sector]))
    if pack_s:
        add_change(r, "Packaging", pack_s * r.tec_p50_m, 0,
                   "Contract repackaging into regional alliance bundles" if r.program_id == "PRG-RWS" else "Combined procurement with adjacent package")
    if rng.random() < 0.25:  # pending requests: visible in the register, not yet in the forecast
        add_change(r, rng.choice(["Scope", "Schedule"]), float(rng.uniform(0.005, 0.03)) * r.tec_p50_m,
                   int(rng.integers(0, 4)), "Change request under assessment", status="Pending")
    drivers.append(dict(project_id=r.project_id, slip=slip, delay=delay, scope=scope_s * r.tec_p50_m, packaging=pack_s * r.tec_p50_m, u=u))
drivers = pd.DataFrame(drivers).set_index("project_id")
changes = pd.DataFrame(changes)

# True outturn path, then seasonal / noisy monthly actuals. History follows the plan with drift `u`.
SEASON = np.array([0.95, 1.00, 1.02, 1.03, 1.05, 0.85, 0.72, 0.98, 1.05, 1.00, 1.08, 1.27])  # Jul..Jun
SEASON = SEASON / SEASON.mean()
season_by_month = np.array([SEASON[i % 12] for i in range(N_MONTHS)])
truth, truth_smooth = {}, {}
for r in projects.itertuples():
    d = drivers.loc[r.project_id]
    paths = explained_paths(plan[r.project_id], T0, slip_months=d.slip, delay_cost=d.delay,
                            esc_factor=esc_factor[r.sector], scope=d.scope, packaging=d.packaging)
    smooth = paths["packaging"] * (1 + d.u)
    noise = rng.lognormal(-0.5 * 0.10 ** 2, 0.10, N_MONTHS)
    truth_smooth[r.project_id] = smooth
    truth[r.project_id] = smooth * season_by_month * noise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Market capacity model
# MAGIC
# MAGIC Twelve delivery-input categories, each with a demand intensity per $m of spend by subsector and
# MAGIC an annual supply available to this portfolio. Supply grows smoothly; its level is calibrated so the
# MAGIC synthetic market is tight where the public reporting says it is (skilled civil labour, electrical
# MAGIC equipment), with the peak in the third horizon year.

# COMMAND ----------

CATEGORIES = [
    # id, name, unit, growth p.a., peak utilisation target, portfolio share of national supply
    ("CIV_LAB", "Skilled civil labour", "FTE", 0.012, 1.18, 0.21),
    ("ELE_EQP", "Electrical equipment", "HV equipment units", 0.030, 1.12, 0.34),
    ("CONCRETE", "Concrete", "'000 m3", 0.020, 0.96, 0.14),
    ("ENG_SVC", "Engineering services", "FTE", 0.020, 0.91, 0.18),
    ("TUNNEL", "Tunnel boring capacity", "TBM-years", 0.000, 0.88, 0.45),
    ("ELE_TRD", "Electrical trades", "FTE", 0.015, 0.86, 0.16),
    ("PIPES", "Pipes & precast", "kt", 0.020, 0.83, 0.20),
    ("PM_SVC", "Project & commercial management", "FTE", 0.020, 0.79, 0.17),
    ("STEEL", "Steel", "kt", 0.020, 0.74, 0.12),
    ("PLANT", "Heavy plant & equipment", "machine-years", 0.020, 0.71, 0.15),
    ("AGGREG", "Quarry aggregates", "Mt", 0.020, 0.66, 0.10),
    ("ASPHALT", "Asphalt", "kt", 0.020, 0.58, 0.09),
]
SUBSECTORS = ["Urban rail", "Freight rail", "Roads", "Ports", "Transmission", "Generation & storage", "Bulk water",
              "Desalination", "Wastewater & recycling", "Health", "Education"]
INTENSITY = {  # units per $m of annual spend, in SUBSECTORS order
    "CIV_LAB": [1.70, 1.60, 1.50, 1.30, 0.90, 1.10, 1.40, 1.00, 1.20, 0.80, 0.90],
    "ELE_EQP": [0.12, 0.04, 0.02, 0.05, 0.90, 0.60, 0.08, 0.25, 0.15, 0.10, 0.05],
    "CONCRETE": [0.90, 0.70, 0.80, 1.10, 0.25, 0.90, 1.40, 0.60, 0.80, 0.50, 0.60],
    "ENG_SVC": [0.35, 0.30, 0.28, 0.30, 0.38, 0.40, 0.30, 0.35, 0.30, 0.25, 0.20],
    "TUNNEL": [0.0040, 0.0, 0.0, 0.0, 0.0002, 0.0010, 0.0, 0.0, 0.0010, 0.0, 0.0],
    "ELE_TRD": [0.45, 0.20, 0.12, 0.20, 0.80, 0.60, 0.15, 0.40, 0.30, 0.50, 0.40],
    "PIPES": [0.08, 0.03, 0.10, 0.05, 0.02, 0.10, 0.60, 0.40, 0.70, 0.03, 0.03],
    "PM_SVC": [0.24, 0.22, 0.20, 0.20, 0.22, 0.22, 0.20, 0.22, 0.20, 0.24, 0.22],
    "STEEL": [0.12, 0.15, 0.08, 0.14, 0.18, 0.12, 0.06, 0.08, 0.05, 0.06, 0.05],
    "PLANT": [0.030, 0.045, 0.050, 0.040, 0.020, 0.040, 0.040, 0.020, 0.025, 0.010, 0.010],
    "AGGREG": [0.005, 0.010, 0.012, 0.006, 0.002, 0.006, 0.008, 0.003, 0.004, 0.002, 0.002],
    "ASPHALT": [0.10, 0.20, 0.90, 0.30, 0.02, 0.03, 0.05, 0.02, 0.05, 0.03, 0.03],
}
intensity = pd.DataFrame([dict(subsector=s, category_id=c, units_per_aud_m=INTENSITY[c][i])
                          for c in INTENSITY for i, s in enumerate(SUBSECTORS)])

# Expected annual spend by subsector over the horizon (smooth truth), used only to calibrate supply.
fy_spend = {}
for r in projects.itertuples():
    for fy in HORIZON:
        fy_spend[(r.subsector, fy)] = fy_spend.get((r.subsector, fy), 0.0) + truth_smooth[r.project_id][FY_OF_MONTH == fy].sum()
peak_fy = H0 + 2
cap_version = f"CAP-{anchor:%Y.%m}"
capacity_rows = []
for cid, cname, unit, growth, target, share in CATEGORIES:
    # Level the supply curve so the tightest horizon year sits exactly at the target utilisation.
    demand_fy = {fy: sum(fy_spend[(s, fy)] * INTENSITY[cid][i] for i, s in enumerate(SUBSECTORS)) for fy in HORIZON}
    peak_supply = max(demand_fy[fy] / (1 + growth) ** (fy - peak_fy) for fy in HORIZON) / target
    for fy in range(H0 - 2, H0 + 8):
        available = peak_supply * (1 + growth) ** (fy - peak_fy) * rng.normal(1, 0.004)
        capacity_rows.append(dict(model_version=cap_version, category_id=cid, fy=fy, financial_year=fy_label(fy),
                                  available_units=round(available, 3), national_units=round(available / share, 3),
                                  portfolio_share_pct=round(share * 100, 1), assumption_id=f"CAP-{cid}"))
market_capacity = pd.DataFrame(capacity_rows)
capacity_categories = pd.DataFrame([dict(category_id=c, category_name=n, unit=u, growth_rate=g, assumption_id=f"CAP-{c}",
                                         constrained_threshold_pct=90.0, breach_threshold_pct=100.0)
                                    for c, n, u, g, _, _ in CATEGORIES])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assurance: Gateway reviews and the assumptions register

# COMMAND ----------

GATE_NAMES = {0: "Gate 0 - Business need", 1: "Gate 1 - Business case", 2: "Gate 2 - Delivery strategy",
              3: "Gate 3 - Investment decision", 4: "Gate 4 - Readiness for service", 5: "Gate 5 - Benefits realisation"}
RATINGS = ["Green", "Amber/Green", "Amber", "Amber/Red", "Red"]
STORY_RATING = {"PRG-ETC": ["Amber/Red", "Amber"], "PRG-NGR": ["Amber", "Amber/Red"], "PRG-RWS": ["Green", "Amber/Green"],
                "PRG-WFL": ["Amber", "Amber/Red"], "PRG-MTR": ["Amber/Green", "Amber"]}
REVIEW_LEADS = ["M. Okafor", "J. Nguyen", "S. Patel", "R. Whitfield", "A. Kowalski", "L. Tran", "D. Murray", "K. Anand",
                "H. Bergstrom", "P. O'Connell", "T. Watanabe", "C. Fitzgerald"]
FINDINGS = {
    "Green": "Delivery appears highly likely; no major outstanding issues.",
    "Amber/Green": "Successful delivery probable; issues require timely management attention.",
    "Amber": "Successful delivery feasible but significant issues already exist requiring management attention.",
    "Amber/Red": "Successful delivery in doubt; major risks or issues apparent in a number of key areas.",
    "Red": "Successful delivery appears unachievable without urgent action.",
}
reviews, rv = [], 0
for r in projects.itertuples():
    last_gate = {"Planning": 1, "Procurement": 2, "Delivery": 3, "Commissioning": 4}[r.lifecycle_stage]
    days_back = int(rng.integers(10, 120))
    for gate in range(last_gate, -1, -1):
        rv += 1
        if gate == last_gate:
            rating = (rng.choice(STORY_RATING[r.program_id], p=[0.7, 0.3]) if r.program_id in STORY_RATING
                      else rng.choice(RATINGS, p=[0.22, 0.38, 0.27, 0.11, 0.02]))
        else:
            rating = rng.choice(RATINGS[:4], p=[0.35, 0.40, 0.20, 0.05])
        if r.program_id == "PRG-ETC" and gate == last_gate and "Underground Stations" in r.project_name:
            rating, days_back = "Amber/Red", 11  # the Gate 2 review called out in the assurance register
        report_date = rel(-days_back)
        crit = {"Green": 0, "Amber/Green": 0, "Amber": 1, "Amber/Red": 3, "Red": 5}[rating]
        reviews.append(dict(review_id=f"GR-{rv:05d}", project_id=r.project_id, gate=gate, gate_name=GATE_NAMES[gate],
                            review_type="Gateway review", review_start=(report_date - timedelta(days=5)).isoformat(),
                            report_date=report_date.isoformat(), delivery_confidence=rating,
                            recommendations_total=int(crit + rng.integers(2, 9)), recommendations_critical=int(crit + rng.integers(0, 2)),
                            review_team_lead=str(rng.choice(REVIEW_LEADS)), senior_responsible_official=f"{r.delivery_agency} SRO",
                            summary=FINDINGS[rating]))
        days_back += int(rng.integers(240, 540))
gateway_reviews = pd.DataFrame(reviews)

OWNERS = {"Economic assumption": "Portfolio Economics", "Market assumption": "Capacity Office", "Fiscal assumption": "Budget Strategy",
          "Delivery assumption": "Portfolio Office", "Cost estimate": "Program Executive"}
register = []


def add_assumption(aid, title, atype, confidence, status, reviewed_days, value_summary, version=None, owner=None):
    register.append(dict(assumption_id=aid, title=title, assumption_type=atype, owner=owner or OWNERS[atype], confidence=confidence,
                         approval_status=status, version=int(version or rng.integers(2, 9)), effective_from=fy_start(H0).isoformat(),
                         last_reviewed=rel(-reviewed_days).isoformat(), next_review_due=rel(-reviewed_days + 90).isoformat(),
                         evidence_reference=f"EDRMS-{rng.integers(100000, 999999)}", value_summary=value_summary))


for sector, code in SECTOR_CODES.items():
    add_assumption(f"ESC-{code}", f"Construction escalation - {sector.lower()}", "Economic assumption",
                   "Medium", "Endorsed" if sector in ("Transport", "Water") else "Working", 5 if sector == "Transport" else int(rng.integers(8, 40)),
                   f"{CURRENT_ESC[sector][0] * 100:.1f}% falling to {CURRENT_ESC[sector][4] * 100:.1f}% p.a. vs {ENDORSED_ESC[sector] * 100:.1f}% endorsed")
add_assumption("CPI-DEF", "Price deflator (CPI)", "Economic assumption", "High", "Endorsed", 30, "2.9% then 2.5% p.a.")
for cid, cname, unit, growth, target, share in CATEGORIES:
    status = "Working" if cid == "ELE_EQP" else ("Awaiting attestation" if cid in ("TUNNEL", "PIPES") else "Endorsed")
    add_assumption(f"CAP-{cid}", f"{cname} capacity", "Market assumption", "Low" if cid in ("CIV_LAB", "ELE_EQP") else "Medium",
                   status, 15 if cid == "ELE_EQP" else int(rng.integers(5, 60)),
                   f"Portfolio-available supply grows {growth * 100:.1f}% p.a.; {share * 100:.0f}% of national supply", version=3)
add_assumption("INT-DEMAND", "Demand intensity coefficients", "Market assumption", "Medium", "Endorsed", 45, "Units of input per $m by subsector")
add_assumption("FUND-ENV", "Five-year funding envelope", "Fiscal assumption", "High", "Endorsed", 160, "Endorsed plan plus 6% portfolio headroom")
add_assumption("DELAY-COST", "Delay cost rate", "Delivery assumption", "Medium", "Endorsed", 70, f"{DELAY_COST_RATE * 100:.2f}% of P50 per month of slip")
for prog in PROGRAMS:
    rating = STORY_RATING.get(prog["id"], ["Amber/Green"])[0]
    conf = {"Green": "High", "Amber/Green": "Medium", "Amber": "Medium", "Amber/Red": "Low", "Red": "Low"}[rating]
    status = "Action required" if rating in ("Amber/Red", "Red") else ("Awaiting attestation" if rng.random() < 0.45 else "Endorsed")
    add_assumption(f"EST-{prog['id'][4:]}", f"{prog['name']} cost estimate (P50)", "Cost estimate", conf, status,
                   11 if prog["id"] == "PRG-ETC" else int(rng.integers(5, 120)), "Program P50 estimate including contingency")
assumptions_register = pd.DataFrame(register)

funding_envelope = pd.DataFrame([dict(fy=fy, financial_year=fy_label(fy), assumption_id="FUND-ENV",
                                      envelope_aud=round(sum(p[FY_OF_MONTH == fy].sum() for p in plan.values()) * 1.06, 1) * 1e6)
                                 for fy in HORIZON])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Seeded scenarios (inputs as data)

# COMMAND ----------

scen_ts = datetime.combine(rel(-3), datetime.min.time()).isoformat()
scenario_definitions = pd.DataFrame([
    dict(scenario_id="BASE", scenario_name="Working baseline", version=12, base_scenario_id=None, method="as_forecast", status="Locked",
         decision_purpose="Portfolio forecast from recorded drivers", description="Current forecast: endorsed plan adjusted for approved changes, current escalation and cost performance.",
         created_by="planning.office", created_at=scen_ts, source="seed"),
    dict(scenario_id="ENDORSED", scenario_name="Endorsed plan", version=8, base_scenario_id=None, method="plan", status="Endorsed",
         decision_purpose="Budget as endorsed", description="Endorsed plan phasing without subsequent changes.",
         created_by="budget.strategy", created_at=datetime.combine(date(H0 - 1, 5, 12), datetime.min.time()).isoformat(), source="seed"),
    dict(scenario_id="CAP_BAL", scenario_name="Capacity balanced", version=4, base_scenario_id="BASE", method="auto_sequence", status="Draft",
         decision_purpose="Executive Budget Committee review", description="Resequence deferrable, lower-priority work so modelled demand stays within market capacity.",
         created_by="planning.office", created_at=scen_ts, source="seed"),
    dict(scenario_id="ACCEL", scenario_name="Accelerated delivery", version=3, base_scenario_id="BASE", method="levers", status="Draft",
         decision_purpose="Test bringing forward tier-1 transport and energy programs", description="Accelerate priority programs by six months; market heats.",
         created_by="planning.office", created_at=scen_ts, source="seed"),
])
levers = [
    ("CAP_BAL", 4, "capacity_uplift_pct", "capacity_category", "CIV_LAB", 3.0, "Skilled migration and apprenticeship pipeline uplift", "CAP-CIV_LAB"),
    ("ACCEL", 3, "accelerate_months", "program", "PRG-ETC", 6.0, "Bring forward tunnelling and stations", "EST-ETC"),
    ("ACCEL", 3, "accelerate_months", "program", "PRG-NGR", 6.0, "Bring forward transmission to support REZ timing", "EST-NGR"),
    ("ACCEL", 3, "accelerate_months", "program", "PRG-REZ", 6.0, "Bring forward REZ connections", "EST-REZ"),
    ("ACCEL", 3, "accelerate_months", "program", "PRG-IHU", 6.0, "Bring forward highway duplication", "EST-IHU"),
    ("ACCEL", 3, "escalation_delta_pp", "sector", "Transport", 0.6, "Market heat from compressed delivery", "ESC-TRN"),
    ("ACCEL", 3, "escalation_delta_pp", "sector", "Energy", 0.8, "Market heat from compressed delivery", "ESC-ENE"),
]
scenario_levers = pd.DataFrame([dict(lever_id=f"LV-{s}-{i + 1:03d}", scenario_id=s, scenario_version=v, lever_type=t, target_type=tt,
                                     target_id=tid, value=val, rationale=why, assumption_id=aid, created_by="planning.office",
                                     created_at=scen_ts, source="seed")
                                for i, (s, v, t, tt, tid, val, why, aid) in enumerate(levers)])

# COMMAND ----------

# MAGIC %md
# MAGIC ## Suppliers and general-ledger postings (dbldatagen)
# MAGIC
# MAGIC Monthly project spend from the true path is split into individual postings. dbldatagen draws each
# MAGIC posting's project-month, cost element, size (gamma), posting day, document type and supplier
# MAGIC (exponential concentration - a few large contractors take most of the value). Amounts are then
# MAGIC normalised so each project-month reconciles exactly to the true spend.

# COMMAND ----------

ELEMENTS = [  # cost element, supplier category, share by sector (Transport, Energy, Water, Social)
    ("Civil works labour", "Civil contractor", (0.30, 0.16, 0.26, 0.22)),
    ("Electrical & mechanical labour", "Electrical contractor", (0.07, 0.17, 0.08, 0.14)),
    ("Materials - concrete & aggregates", "Concrete & quarry supplier", (0.12, 0.05, 0.14, 0.10)),
    ("Materials - steel", "Steel supplier", (0.07, 0.06, 0.05, 0.06)),
    ("Electrical equipment", "Electrical equipment OEM", (0.05, 0.24, 0.07, 0.05)),
    ("Plant & equipment hire", "Plant hire", (0.07, 0.04, 0.07, 0.03)),
    ("Engineering & design services", "Engineering consultancy", (0.10, 0.11, 0.10, 0.12)),
    ("Project management & overheads", "Project management consultancy", (0.09, 0.09, 0.09, 0.12)),
    ("Land & property", "Property & valuation", (0.06, 0.04, 0.05, 0.06)),
    ("Utilities relocation", "Utility services", (0.04, 0.02, 0.05, 0.03)),
    ("Other direct costs", "General supplier", (0.03, 0.02, 0.04, 0.07)),
]
SECTOR_POS = {"Transport": 0, "Energy": 1, "Water": 2, "Social": 3}
SUP_CATS = sorted({e[1] for e in ELEMENTS})

supplier_spec = (
    dg.DataGenerator(spark, name="suppliers", rows=480, partitions=1, randomSeed=seed, randomSeedMethod="hash_fieldname")
    .withIdOutput()
    .withColumn("supplier_category", "string", values=SUP_CATS, random=True)
    .withColumn("prefix", "string", values=["Southern Cross", "Ironbark", "Red Gum", "Kestrel", "Coastline", "Brolga", "Stringybark",
                                             "Jarrah", "Wombat Hill", "Arnhem", "Gulf Country", "Nullarbor", "Darling", "Snowy",
                                             "Barossa", "Lachlan", "Hunter Valley", "Derwent", "Gippsland", "Bellarine", "Whitsunday",
                                             "Blue Range", "Granite Belt", "Saltbush", "Kookaburra", "Murray", "Highland", "Eureka",
                                             "Sandstone", "Wattle", "Gondwana", "Pilbara", "Riverina", "Tasman", "Capricorn", "Banksia",
                                             "Yarra", "Hawkesbury", "Kimberley", "Flinders", "Otway", "Bluegum", "Mallee", "Coral Sea"],
                random=True, omit=True)
    .withColumn("noun", "string", values=["Civil", "Constructions", "Infrastructure", "Engineering", "Group", "Projects",
                                           "Contracting", "Industries", "Services", "Partners"], random=True, omit=True)
    .withColumn("supplier_name", "string", expr="concat(prefix, ' ', noun, ' Pty Ltd')", baseColumn=["prefix", "noun"])
    .withColumn("abn", "string", template=r"dd ddd ddd ddd", random=True)
    .withColumn("state", "string", values=list(PLACES), weights=[30, 25, 20, 10, 7, 3, 2, 3], random=True)
    .withColumn("supplier_tier", "string", values=["Tier 1", "Tier 2", "Tier 3"], weights=[12, 38, 50], random=True)
    .withColumn("indigenous_business", "boolean", values=[True, False], weights=[7, 93], random=True)
    .withColumn("onboarded_date", "date", data_range=dg.DateRange("2012-01-01 00:00:00", "2025-12-31 00:00:00", "days=1"), random=True)
)
suppliers = (supplier_spec.build()
             .dropDuplicates(["supplier_name"])
             .withColumn("supplier_id", F.format_string("SUP-%05d", F.col("id") + 1))
             .withColumn("rank_in_category", F.row_number().over(Window.partitionBy("supplier_category").orderBy("id")) - 1)
             .drop("id"))
sup_counts = suppliers.groupBy("supplier_category").agg(F.count("*").alias("n_in_category"))

# COMMAND ----------

last_landed = get_control("gl_last_landed_month") or ""
first_month = month_idx(date.fromisoformat(last_landed)) + 1 if last_landed else 0
last_month = month_idx(land_through)
pm_rows = [dict(pm_id=0, project_id=r.project_id, sector=r.sector, month_idx=int(m), total_aud=float(truth[r.project_id][m] * 1e6))
           for r in projects.itertuples() for m in range(first_month, last_month + 1) if truth[r.project_id][m] > 1e-4]
print(f"GL months to land: {month_start(first_month) if pm_rows else '-'} .. {land_through} ({len(pm_rows)} project-months)")

if mode == "bootstrap":  # a rebuilt world replaces the ledger feed rather than appending to it
    dbutils.fs.rm(f"{LANDING_ROOT}/gl_transactions", recurse=True)

if pm_rows:
    pm = pd.DataFrame(pm_rows)
    pm["pm_id"] = np.arange(len(pm))
    pm["period"] = pm.month_idx.map(lambda m: f"{month_start(m):%Y-%m}")
    pm["month_start"] = pm.month_idx.map(month_start)
    pm_df = spark.createDataFrame(pm)
    share_df = spark.createDataFrame(pd.DataFrame([dict(sector=s, cost_element=e, supplier_category=c, share=sh[p])
                                                   for e, c, sh in ELEMENTS for s, p in SECTOR_POS.items()]))
    gl_spec = (
        dg.DataGenerator(spark, name="gl_postings", rows=len(pm) * txn_per_pm, partitions=16, randomSeed=seed + first_month,
                         randomSeedMethod="hash_fieldname")
        .withIdOutput()
        .withColumn("pm_id", "long", minValue=0, maxValue=len(pm) - 1, random=True)
        .withColumn("cost_element", "string", values=[e for e, _, _ in ELEMENTS], random=True)
        .withColumn("w", "double", minValue=0.01, maxValue=100.0, distribution=dist.Gamma(0.6, 2.0), random=True)
        .withColumn("posting_day", "int", minValue=1, maxValue=28, random=True)
        .withColumn("document_type", "string", values=["Progress claim", "Supplier invoice", "Accrual", "Journal"],
                    weights=[45, 35, 15, 5], random=True)
        .withColumn("supplier_u", "double", minValue=0.0, maxValue=1.0, distribution=dist.Exponential(4.0), random=True)
        .withColumn("document_number", "string", template=r"dddddddddd", random=True)
    )
    raw = (gl_spec.build().join(pm_df, "pm_id").join(share_df, ["sector", "cost_element"])
           .withColumn("raw_amount", F.col("w") * F.col("share")))
    norm = Window.partitionBy("pm_id")
    gl = (raw.withColumn("amount_aud", F.round(F.col("total_aud") * F.col("raw_amount") / F.sum("raw_amount").over(norm), 2))
          .join(sup_counts, "supplier_category")
          .withColumn("rank_in_category", F.least(F.floor(F.col("supplier_u") * F.col("n_in_category")), F.col("n_in_category") - 1).cast("int"))
          .join(suppliers.select("supplier_category", "rank_in_category", "supplier_id"), ["supplier_category", "rank_in_category"])
          .withColumn("posting_date", F.date_add(F.col("month_start"), F.col("posting_day") - 1))
          .withColumn("txn_id", F.concat(F.lit("GL-"), F.regexp_replace("period", "-", ""), F.lit("-"), F.lpad(F.col("id").cast("string"), 9, "0")))
          .withColumn("wbs_code", F.concat_ws(".", F.col("project_id"), F.lpad((F.abs(F.hash("cost_element")) % 90 + 10).cast("string"), 2, "0")))
          .withColumn("currency", F.lit("AUD"))
          .withColumn("ledger", F.lit("CAPEX"))
          .withColumn("document_number", F.concat(F.lit("DOC"), F.col("document_number")))
          .select("txn_id", "period", "posting_date", "project_id", "wbs_code", "cost_element", "supplier_id",
                  "document_type", "document_number", "amount_aud", "currency", "ledger"))
    gl.write.mode("append").partitionBy("period").option("header", True).csv(f"{LANDING_ROOT}/gl_transactions")
    set_control("gl_last_landed_month", month_start(last_month).isoformat())
    print(f"Landed GL postings for {len(pm)} project-months")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Land snapshot extracts (bootstrap only)

# COMMAND ----------


def land(pdf, extract: str, fmt: str = "csv"):
    path = f"{LANDING_ROOT}/{extract}/delivery_date={anchor.isoformat()}"
    df = pdf if isinstance(pdf, DataFrame) else spark.createDataFrame(pdf.astype(object).where(pd.notnull(pdf), None))
    w_ = df.coalesce(1).write.mode("overwrite")
    (w_.option("header", True).csv(path) if fmt == "csv" else w_.json(path))
    print(f"landed {extract:<22} {df.count():>7} rows -> {path}")


if mode == "bootstrap":
    land(pd.DataFrame([dict(program_id=p["id"], program_name=p["name"], sector=p["sector"], subsector=p["subsector"],
                            lead_jurisdiction=p["juris"][0], delivery_agency=p["agency"],
                            program_executive=f"{p['name']} Program Executive") for p in PROGRAMS]), "programs")
    proj_out = projects[["project_id", "program_id", "project_name", "sector", "subsector", "jurisdiction", "region_type",
                         "delivery_agency", "delivery_model", "lifecycle_stage", "priority_tier", "schedule_flexibility",
                         "funding_source", "commonwealth_share_pct", "tec_p50_m", "tec_p90_m", "contingency_pct",
                         "baseline_start", "baseline_finish", "bcr", "benefits_pv_m", "benefit_category"]].copy()
    for c in ("tec_p50", "tec_p90", "benefits_pv"):
        proj_out[f"{c}_aud"] = (proj_out.pop(f"{c}_m") * 1e6).round(0)
    proj_out["baseline_start"] = proj_out.baseline_start.map(lambda d: d.isoformat())
    proj_out["baseline_finish"] = proj_out.baseline_finish.map(lambda d: d.isoformat())
    land(proj_out, "projects")
    land(pd.DataFrame([dict(plan_version="EP-v8", plan_name="Endorsed plan", version=8, approved_date=date(H0 - 1, 5, 12).isoformat(),
                            approved_by="Expenditure Review Committee", status="Endorsed", price_basis="Nominal, endorsed escalation")]), "plan_versions")
    phasing = pd.DataFrame([dict(plan_version="EP-v8", project_id=pid, month=month_start(m).isoformat(), amount_aud=round(float(v) * 1e6, 0))
                            for pid, p in plan.items() for m, v in enumerate(p) if v > 1e-4])
    land(phasing, "plan_phasing")
    land(suppliers.drop("rank_in_category"), "suppliers")
    land(changes, "change_register", "json")
    land(gateway_reviews, "gateway_reviews", "json")
    land(assumptions_register, "assumptions_register", "json")
    land(escalation, "escalation_rates")
    land(deflator, "price_deflator")
    land(funding_envelope, "funding_envelope")
    land(capacity_categories, "capacity_categories")
    land(market_capacity, "market_capacity")
    land(intensity, "demand_intensity")
    land(scenario_definitions, "scenario_definitions", "json")
    land(scenario_levers, "scenario_levers", "json")

print("Synthetic generation complete")
