"""Shared model contract for the critical infrastructure monitoring use case.

A national, cross-sector Infrastructure Operations Centre: one operating picture across roads,
rail, water and energy assets run by many operators. Every pipeline step imports this module so
the synthetic generators (01, 02), the conformance step (04) and the risk engine (05, 06) agree on
the same asset classes, metrics and engineering limits, hazard behaviour, storylines and risk
weights. If a definition changes it changes here, and every step picks it up on the next run.

No environment-specific value lives in this file: catalog, schema and volume names arrive as job
parameters, never as literals. All geography is real public Australian place data; every asset,
operator, reading and warning is synthetic.
"""

import datetime as dt
import math
from contextlib import contextmanager
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Sectors and asset classes
# ---------------------------------------------------------------------------
SECTORS = ["roads", "rail", "water", "energy"]
SECTOR_LABELS = {"roads": "Roads", "rail": "Rail", "water": "Water", "energy": "Energy"}

# key: (sector, label, code prefix, relative count, metrics, people served range,
#       needs power from a zone substation, states it occurs in (None = all))
_RAIL_STATES = ["NSW", "VIC", "QLD", "SA", "WA", "ACT"]
ASSET_CLASSES = {
    "bridge":            ("roads",  "Bridge",              "BR", 10, ["strain_microstrain", "vibration_mm_s"], (5_000, 90_000),   False, None),
    "tunnel":            ("roads",  "Road tunnel",         "TN",  3, ["co_ppm"],                               (20_000, 120_000), True,  ["NSW", "VIC", "QLD"]),
    "road_corridor":     ("roads",  "Road corridor",       "RC", 10, ["surface_water_mm"],                     (3_000, 60_000),   False, None),
    "track_section":     ("rail",   "Track section",       "TK", 10, ["rail_temp_c"],                          (2_000, 60_000),   False, _RAIL_STATES),
    "signalling":        ("rail",   "Signalling interlocking", "SG", 6, ["signal_faults"],                     (10_000, 150_000), True,  _RAIL_STATES),
    "overhead_wiring":   ("rail",   "Overhead wiring",     "OW",  5, ["wire_temp_c"],                          (10_000, 120_000), True,  ["NSW", "VIC", "QLD", "SA", "WA"]),
    "level_crossing":    ("rail",   "Level crossing",      "LX",  5, ["activation_faults"],                    (1_000, 15_000),   True,  _RAIL_STATES),
    "reservoir":         ("water",  "Reservoir",           "RS",  6, ["level_pct"],                            (20_000, 400_000), False, None),
    "trunk_main":        ("water",  "Trunk main",          "TM",  8, ["pressure_kpa"],                         (10_000, 250_000), False, None),
    "pump_station":      ("water",  "Pumping station",     "PS",  7, ["pump_load_pct"],                        (5_000, 120_000),  True,  None),
    "treatment_plant":   ("water",  "Treatment plant",     "TP",  3, ["turbidity_ntu"],                        (50_000, 900_000), True,  None),
    "zone_substation":   ("energy", "Zone substation",     "ZS", 10, ["transformer_temp_c", "load_pct"],       (12_000, 200_000), False, None),
    "transmission_line": ("energy", "Transmission line",   "TL",  5, ["line_load_pct"],                        (50_000, 600_000), False, None),
    "feeder":            ("energy", "Distribution feeder", "FD",  8, ["feeder_faults"],                        (1_000, 12_000),   False, None),
}

# Fictional operators. Real infrastructure is run by many organisations per sector; the centre's
# job is to see across all of them. Names are deliberately generic and invented.
OPERATORS = {
    "roads": ["Eastern Highways Authority", "Southern Road Network", "Northern Roads Corporation", "Western Motorways"],
    "rail": ["Coastal Rail Network", "Metropolitan Rail Services", "Inland Rail Freight", "Southern Cross Rail"],
    "water": ["Harbour Water", "Riverlands Water Corporation", "Coastal Water Utilities", "Western Water Supply"],
    "energy": ["Southern Grid", "Eastern Distribution", "National Transmission Co", "Northern Power Networks"],
}

# Real public geography (name, state, latitude, longitude, relative asset density).
LOCALITIES = [
    ("Sydney", "NSW", -33.87, 151.21, 6), ("Parramatta", "NSW", -33.81, 151.00, 4), ("Penrith", "NSW", -33.75, 150.69, 4),
    ("Liverpool", "NSW", -33.92, 150.92, 3), ("Campbelltown", "NSW", -34.07, 150.81, 3), ("Newcastle", "NSW", -32.93, 151.78, 4),
    ("Maitland", "NSW", -32.73, 151.55, 2), ("Wollongong", "NSW", -34.42, 150.89, 3), ("Gosford", "NSW", -33.43, 151.34, 2),
    ("Lismore", "NSW", -28.81, 153.28, 2), ("Grafton", "NSW", -29.69, 152.93, 2), ("Tamworth", "NSW", -31.09, 150.93, 1),
    ("Dubbo", "NSW", -32.25, 148.60, 1), ("Wagga Wagga", "NSW", -35.12, 147.37, 1), ("Goulburn", "NSW", -34.75, 149.72, 1),
    ("Albury", "NSW", -36.08, 146.92, 1), ("Orange", "NSW", -33.28, 149.10, 1), ("Port Macquarie", "NSW", -31.43, 152.91, 1),
    ("Canberra", "ACT", -35.28, 149.13, 3),
    ("Melbourne", "VIC", -37.81, 144.96, 6), ("Sunshine", "VIC", -37.79, 144.83, 3), ("Dandenong", "VIC", -37.99, 145.21, 3),
    ("Geelong", "VIC", -38.15, 144.36, 2), ("Ballarat", "VIC", -37.56, 143.85, 1), ("Bendigo", "VIC", -36.76, 144.28, 1),
    ("Traralgon", "VIC", -38.20, 146.54, 2), ("Sale", "VIC", -38.10, 147.07, 1), ("Bairnsdale", "VIC", -37.82, 147.61, 1),
    ("Shepparton", "VIC", -36.38, 145.40, 1), ("Wodonga", "VIC", -36.12, 146.89, 1), ("Warrnambool", "VIC", -38.38, 142.48, 1),
    ("Brisbane", "QLD", -27.47, 153.03, 6), ("Ipswich", "QLD", -27.61, 152.76, 2), ("Logan", "QLD", -27.64, 153.11, 2),
    ("Gold Coast", "QLD", -28.02, 153.40, 3), ("Sunshine Coast", "QLD", -26.65, 153.07, 2), ("Toowoomba", "QLD", -27.56, 151.95, 1),
    ("Rockhampton", "QLD", -23.38, 150.51, 1), ("Mackay", "QLD", -21.14, 149.19, 1), ("Townsville", "QLD", -19.26, 146.82, 2),
    ("Cairns", "QLD", -16.92, 145.77, 1),
    ("Adelaide", "SA", -34.93, 138.60, 4), ("Salisbury", "SA", -34.77, 138.64, 2), ("Murray Bridge", "SA", -35.12, 139.27, 1),
    ("Port Augusta", "SA", -32.49, 137.77, 1), ("Mount Gambier", "SA", -37.83, 140.78, 1),
    ("Perth", "WA", -31.95, 115.86, 5), ("Joondalup", "WA", -31.74, 115.77, 2), ("Fremantle", "WA", -32.05, 115.75, 2),
    ("Mandurah", "WA", -32.53, 115.72, 1), ("Bunbury", "WA", -33.33, 115.64, 1), ("Kalgoorlie", "WA", -30.75, 121.47, 1),
    ("Hobart", "TAS", -42.88, 147.33, 2), ("Launceston", "TAS", -41.44, 147.14, 1),
    ("Darwin", "NT", -12.46, 130.84, 2), ("Katherine", "NT", -14.47, 132.26, 1), ("Alice Springs", "NT", -23.70, 133.88, 1),
]

# ---------------------------------------------------------------------------
# Transport networks (real public line geometry, fetched at run time - never committed)
# ---------------------------------------------------------------------------
# Department of Infrastructure National Key Freight Routes (CC BY 4.0) for road and rail; Natural
# Earth rivers (public domain) as map context. 01a_fetch_networks downloads them into the landing
# volume and builds a routable graph, so closures can be propagated as detours and isolation.
_KFR = "https://spatial.infrastructure.gov.au/server/rest/services/KeyFreightRoutes/Key_Freight_Routes/MapServer"
NETWORK_SOURCES = {
    "road": {
        "url": f"{_KFR}/5/query",
        "attribution": "National Key Freight Routes (road), Department of Infrastructure, Transport, Regional Development, Communications, Sport and the Arts, CC BY 4.0",
        "licence": "CC BY 4.0",
    },
    "rail": {
        "url": f"{_KFR}/6/query",
        "attribution": "National Key Freight Routes (rail), Department of Infrastructure, Transport, Regional Development, Communications, Sport and the Arts, CC BY 4.0",
        "licence": "CC BY 4.0",
    },
    "river": {
        "url": "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_rivers_australia.geojson",
        "attribution": "Natural Earth rivers (Australia supplement), public domain",
        "licence": "Public domain",
    },
}
NETWORK_GENERALISE_DEG = 0.005   # server-side generalisation (~500 m) when fetching
NODE_SNAP_KM = 1.5               # vertices closer than this become one network node
DISPLAY_TOLERANCE_DEG = 0.01     # map geometry simplification (~1 km)
ASSET_SNAP_MAX_KM = 30.0         # road/rail assets further than this from a key route stay off-network
LOCALITY_SNAP_MAX_KM = 25.0

# Which network each class sits on, and what its failure does to that network.
NETWORK_ASSET_CLASSES = {
    "bridge": ("road", "closure"), "tunnel": ("road", "closure"), "road_corridor": ("road", "closure"),
    "track_section": ("rail", "closure"), "signalling": ("rail", "closure"),
    "overhead_wiring": ("rail", "closure"), "level_crossing": ("rail", "restriction"),
}
# Network consequence of losing the asset (0-1), restrictions counting half:
#   alternative route exists  extra detour km / DETOUR_FULL_KM (detours run along the sparse key
#                             freight network, so they overstate real diversions; hence a long scale)
#   localities cut off        ISOLATION_BASE + ISOLATION_PER_WEIGHT x their combined density weight
#                             (LOCALITIES' relative size - a coarse proxy, not a population figure)
#   no route round, no named locality cut off  NO_ALTERNATIVE_REMOTE
DETOUR_FULL_KM = 600.0
ISOLATION_BASE = 0.5
ISOLATION_PER_WEIGHT = 0.1
NO_ALTERNATIVE_REMOTE = 0.4
RESTRICTION_FACTOR = 0.5


def network_consequence(extra_km, localities_cut_weight, no_alternative, restriction):
    """Network consequence of an asset's failure, as defined above."""
    if no_alternative:
        value = min(1.0, ISOLATION_BASE + ISOLATION_PER_WEIGHT * localities_cut_weight) if localities_cut_weight else NO_ALTERNATIVE_REMOTE
    else:
        value = min(1.0, (extra_km or 0.0) / DETOUR_FULL_KM)
    return round(value * (RESTRICTION_FACTOR if restriction else 1.0), 3)

# ---------------------------------------------------------------------------
# Metrics and engineering limits
# ---------------------------------------------------------------------------
# metric: (label, unit, baseline, noise sd, diurnal amplitude, warn, alarm, direction, kind)
# direction "high": larger is worse; "low": smaller is worse. kind "gauge" or "count" (faults
# per 15 minutes, which are Poisson-like and never negative).
METRICS = {
    "strain_microstrain": ("Deck strain", "µε", 180.0, 12.0, 25.0, 320.0, 400.0, "high", "gauge"),
    "vibration_mm_s": ("Vibration", "mm/s", 2.0, 0.25, 0.6, 5.0, 8.0, "high", "gauge"),
    "co_ppm": ("Carbon monoxide", "ppm", 12.0, 2.5, 8.0, 50.0, 80.0, "high", "gauge"),
    "surface_water_mm": ("Surface water", "mm", 0.0, 0.8, 0.0, 50.0, 150.0, "high", "gauge"),
    "rail_temp_c": ("Rail temperature", "°C", 28.0, 1.5, 10.0, 50.0, 58.0, "high", "gauge"),
    "signal_faults": ("Signal faults", "per 15 min", 0.05, 0.0, 0.0, 3.0, 6.0, "high", "count"),
    "wire_temp_c": ("Contact wire temperature", "°C", 35.0, 1.5, 10.0, 70.0, 85.0, "high", "gauge"),
    "activation_faults": ("Activation faults", "per 15 min", 0.02, 0.0, 0.0, 2.0, 4.0, "high", "count"),
    "level_pct": ("Storage level", "%", 78.0, 0.6, 2.0, 40.0, 25.0, "low", "gauge"),
    "pressure_kpa": ("Line pressure", "kPa", 550.0, 10.0, 35.0, 380.0, 300.0, "low", "gauge"),
    "pump_load_pct": ("Pump load", "%", 55.0, 3.0, 15.0, 90.0, 100.0, "high", "gauge"),
    "turbidity_ntu": ("Treated water turbidity", "NTU", 0.15, 0.02, 0.0, 0.5, 1.0, "high", "gauge"),
    "transformer_temp_c": ("Transformer temperature", "°C", 62.0, 1.5, 12.0, 95.0, 110.0, "high", "gauge"),
    "load_pct": ("Substation load", "% of rating", 58.0, 3.0, 18.0, 90.0, 105.0, "high", "gauge"),
    "line_load_pct": ("Line load", "% of thermal limit", 52.0, 3.0, 15.0, 90.0, 100.0, "high", "gauge"),
    "feeder_faults": ("Feeder faults", "per 15 min", 0.05, 0.0, 0.0, 3.0, 6.0, "high", "count"),
}

READING_INTERVAL_MINUTES = 15

# Incident titles and the first action for an incident triggered by each metric.
METRIC_INCIDENT = {
    "strain_microstrain": ("Bridge strain above design band", "Restrict heavy loading and dispatch a structures inspector"),
    "vibration_mm_s": ("Bridge vibration anomaly", "Inspect for debris strike or scour and consider closure"),
    "co_ppm": ("Tunnel air quality alarm", "Boost ventilation and prepare traffic management for closure"),
    "surface_water_mm": ("Road surface flooding", "Close the corridor and activate the signed detour"),
    "rail_temp_c": ("Rail temperature near buckling threshold", "Impose a heat speed restriction and patrol the track"),
    "signal_faults": ("Signalling fault cluster", "Dispatch a signalling technician and prepare degraded working"),
    "wire_temp_c": ("Overhead wiring heat sag risk", "Reduce traction load and inspect wire tensioning"),
    "activation_faults": ("Level crossing activation faults", "Dispatch a crossing technician and flag for road users"),
    "level_pct": ("Reservoir level below operating band", "Increase transfers and prepare demand restrictions"),
    "pressure_kpa": ("Trunk main pressure drop", "Isolate the suspected burst section and dispatch a crew"),
    "pump_load_pct": ("Pumping station overload", "Bring standby pumps online and check for blockage"),
    "turbidity_ntu": ("Treated water turbidity rising", "Adjust treatment dosing and notify the health regulator"),
    "transformer_temp_c": ("Transformer temperature approaching limit", "Shed or transfer load and dispatch a crew"),
    "load_pct": ("Substation load near rating", "Transfer load to adjacent substations"),
    "line_load_pct": ("Transmission line near thermal limit", "Re-dispatch generation to relieve the line"),
    "feeder_faults": ("Feeder fault cluster", "Dispatch a line crew and patrol the feeder"),
}

# ---------------------------------------------------------------------------
# Hazards (synthetic Bureau-style warnings)
# ---------------------------------------------------------------------------
HAZARD_TYPES = ["heatwave", "flood", "bushfire", "storm"]
HAZARD_LABELS = {"heatwave": "Heatwave", "flood": "Flood", "bushfire": "Bushfire", "storm": "Severe storm"}
SEVERITY_WEIGHT = {"minor": 0.3, "moderate": 0.55, "severe": 0.8, "extreme": 1.0}

# How strongly each hazard type bears on each sector (0-1).
HAZARD_RELEVANCE = {
    "heatwave": {"energy": 1.0, "rail": 1.0, "water": 0.8, "roads": 0.2},
    "flood":    {"roads": 1.0, "water": 0.9, "rail": 0.9, "energy": 0.4},
    "bushfire": {"energy": 1.0, "roads": 0.8, "rail": 0.7, "water": 0.5},
    "storm":    {"energy": 0.9, "rail": 0.8, "roads": 0.6, "water": 0.3},
}

# Physical effect of a hazard at full intensity on each metric (added to the reading). The
# generator scales this by severity, proximity to the warning centre and how long it has run.
HAZARD_EFFECTS = {
    "heatwave": {"rail_temp_c": 22, "wire_temp_c": 38, "transformer_temp_c": 30, "load_pct": 32,
                 "line_load_pct": 32, "pump_load_pct": 30, "level_pct": -22, "pressure_kpa": -90},
    "flood":    {"surface_water_mm": 220, "vibration_mm_s": 5, "turbidity_ntu": 0.9, "signal_faults": 4,
                 "activation_faults": 3, "level_pct": 12},
    "bushfire": {"feeder_faults": 6, "line_load_pct": 30, "wire_temp_c": 30, "signal_faults": 3,
                 "co_ppm": 55, "turbidity_ntu": 0.35},
    "storm":    {"feeder_faults": 6, "signal_faults": 5, "activation_faults": 3, "surface_water_mm": 90,
                 "vibration_mm_s": 2.5},
}

# Active warnings for the demo, relative to the run time: (warning id, title, type, severity,
# centre locality or (lat, lon), radius km, started hours ago, ends hours from now).
HAZARD_WARNINGS = [
    ("HW-NSW-01", "Heatwave warning - Greater Western Sydney and Hunter", "heatwave", "severe", (-33.45, 150.95), 150, 30, 48),
    ("FW-NSW-02", "Flood warning - Northern Rivers", "flood", "severe", (-29.05, 153.05), 95, 18, 36),
    ("BF-VIC-03", "Bushfire emergency warning - Gippsland", "bushfire", "extreme", (-38.05, 146.95), 65, 10, 24),
    ("ST-QLD-04", "Severe thunderstorm warning - South East Queensland", "storm", "moderate", (-27.60, 153.05), 70, 4, 8),
    ("HW-SA-05", "Heatwave warning - Adelaide Plains", "heatwave", "moderate", (-34.80, 138.62), 80, 20, 30),
    # expired: kept so the warnings feed has history and the UI must filter on validity
    ("ST-WA-90", "Severe thunderstorm warning - Perth metropolitan", "storm", "moderate", (-31.95, 115.86), 60, 70, -50),
]

# ---------------------------------------------------------------------------
# Storylines: deterministic asset-specific events layered on top of hazards, so the demo has a
# clear narrative every run. (asset class, nearest locality, metric, target exceedance of the
# alarm band 0-1, ramp hours ending at the run time)
# ---------------------------------------------------------------------------
STORYLINES = [
    ("zone_substation", "Penrith", "transformer_temp_c", 0.95, 10),   # heatwave + cascade to rail and water
    ("trunk_main", "Sunshine", "pressure_kpa", 0.9, 3),               # burst, no hazard involved
    ("reservoir", "Mandurah", "level_pct", 0.8, 96),                  # slow draw-down
    ("bridge", "Rockhampton", "strain_microstrain", 0.85, 48),        # structural deterioration
    ("treatment_plant", "Lismore", "turbidity_ntu", 0.7, 12),         # flood runoff
    ("transmission_line", "Traralgon", "line_load_pct", 0.75, 8),     # bushfire-constrained corridor
    ("signalling", "Brisbane", "signal_faults", 0.6, 4),              # storm-related faults
]

# Storyline assets are anchored at their locality, and these get explicit supply links so the
# cascade narrative holds on every seed: (asset class, locality) -> dependent classes it powers.
STORYLINE_LINKS = {
    ("zone_substation", "Penrith"): ["signalling", "overhead_wiring", "pump_station"],
}

# Background deterioration: a share of assets drift up to this exceedance over the window.
DRIFTING_ASSET_PCT = 5
DRIFT_MAX_EXCEEDANCE = 0.55

# Telemetry quality, handled in silver.
LATE_READING_PCT = 3          # arrive 1-6 hours after the event
DUPLICATE_READING_PCT = 0.5   # delivered twice
UNKNOWN_SENSOR_PCT = 0.2      # sensor id not in the registry -> quarantine
GLITCH_READING_PCT = 0.1      # physically implausible spike -> flagged, excluded from features

# ---------------------------------------------------------------------------
# Risk engine: likelihood x consequence (transparent, human in the loop)
# ---------------------------------------------------------------------------
# Likelihood of a service-affecting failure, as a weighted sum of normalised factors (0-1).
# Direct evidence that an asset is failing now (exceedance, anomaly) outweighs context that makes
# failure more likely (hazard, condition): an asset at its alarm limit is an incident with or
# without a storm nearby.
LIKELIHOOD_WEIGHTS = {
    "limit_exceedance": 0.50,  # how far the worst metric has moved from normal toward its alarm limit
    "anomaly": 0.20,           # deviation from the asset's own recent baseline
    "hazard_exposure": 0.20,   # inside an active warning, weighted by severity and relevance
    "condition": 0.10,         # poor inspection grade (3-5) and overdue inspections
}
# Consequence = the larger of two readings of "what if it fails":
#   people   log10(people relying on the asset and everything downstream), mapped from
#            CONSEQUENCE_LOG_RANGE onto 0-1
#   network  for road and rail assets: detour distance, or 1.0 if localities are cut off
CONSEQUENCE_LOG_RANGE = (3.0, 6.0)  # 1,000 people -> 0, 1,000,000 -> 1
CASCADE_DEPTH = 2
# risk = 100 x likelihood x (CONSEQUENCE_FLOOR + (1 - CONSEQUENCE_FLOOR) x consequence)
CONSEQUENCE_FLOOR = 0.7

# Risk ratings (standard likelihood-consequence vocabulary) and the incident threshold.
RISK_RATINGS = [("extreme", 70), ("high", 57), ("medium", 52)]
INCIDENT_THRESHOLD = 52
DISPOSITIONS = ["dispatch", "notify", "monitor"]

MODEL_VERSION = "ioc-likelihood-consequence-v2"


def haversine_km_expr(lat1: str, lon1: str, lat2: str, lon2: str) -> str:
    """SQL expression: great-circle distance in km between two lat/lon column pairs."""
    return (
        f"2 * 6371 * asin(sqrt(pow(sin(radians({lat2} - {lat1}) / 2), 2) + "
        f"cos(radians({lat1})) * cos(radians({lat2})) * pow(sin(radians({lon2} - {lon1}) / 2), 2)))"
    )


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km (used when building reference data in Python)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def exceedance_expr(metric_col: str, value_col: str) -> str:
    """SQL CASE: normalised exceedance (0-1) of a reading toward its alarm limit."""
    cases = []
    for metric, (_l, _u, base, _sd, _d, _w, alarm, direction, _k) in METRICS.items():
        span = (alarm - base) if direction == "high" else (base - alarm)
        delta = f"({value_col} - {base})" if direction == "high" else f"({base} - {value_col})"
        cases.append(f"WHEN '{metric}' THEN least(1.0, greatest(0.0, {delta} / {span}))")
    return f"CASE {metric_col} " + " ".join(cases) + " END"


# ---------------------------------------------------------------------------
# Synthetic data generation, time and helpers
# ---------------------------------------------------------------------------
# Each generation (data version + as-of date) lands in its own folder and silver resolves only
# the current one, so a rerun on a later day - or after a generator change - produces a clean
# world instead of stacking backfills. Bump this when the generator's behaviour changes.
DATA_VERSION = "ioc-v3"


def generation_tag(as_of: str) -> str:
    """Landing sub-folder name for one synthetic generation."""
    return f"generation={DATA_VERSION}_{as_of}"


# The operations centre runs on Canberra time. "Today", diurnal load and warning validity are
# local-time concepts, so every step that touches clock time sets the Spark session time zone.
# Without it serverless runs in UTC and evening peaks would appear in the morning.
LOCAL_TIMEZONE = "Australia/Sydney"


def get_params(defaults: dict, dbutils) -> dict:
    """Register widgets with defaults, then read job-parameter overrides."""
    for name, default in defaults.items():
        dbutils.widgets.text(name, str(default))
    return {name: dbutils.widgets.get(name) for name in defaults}


def use_local_time(spark) -> None:
    """Interpret and render timestamps in the model's local time zone for this session."""
    spark.conf.set("spark.sql.session.timeZone", LOCAL_TIMEZONE)


def local_now() -> dt.datetime:
    """Current local wall-clock time, second precision (Spark can parse it as a literal)."""
    return dt.datetime.now(ZoneInfo(LOCAL_TIMEZONE)).replace(microsecond=0, tzinfo=None)


def timestamp_sql(ts: dt.datetime) -> str:
    """SQL timestamp literal for a local wall-clock time.

    Use this instead of F.lit(datetime): Spark Connect converts naive Python datetimes
    using the client's zone, not the session zone, which would shift run timestamps.
    """
    return f"timestamp '{ts.strftime('%Y-%m-%d %H:%M:%S')}'"


def resolve_as_of(raw: str) -> str:
    """Normalise the as-of date: blank means today in the model's local time zone."""
    return raw.strip() if raw and raw.strip() else local_now().date().isoformat()


def fq_table(catalog: str, schema: str, name: str) -> str:
    """Fully-qualified Unity Catalog table name."""
    return f"{catalog}.{schema}.{name}"


def volume_dir(catalog: str, schema: str, volume: str, *parts: str) -> str:
    """Path inside this use case's landing volume."""
    return "/".join(["/Volumes", catalog, schema, volume, *filter(None, parts)])


@contextmanager
def ansi_sql_off(spark):
    """Temporarily disable ANSI SQL mode (kept for generators that need non-ANSI arithmetic)."""
    prior = spark.conf.get("spark.sql.ansi.enabled")
    spark.conf.set("spark.sql.ansi.enabled", "false")
    try:
        yield
    finally:
        spark.conf.set("spark.sql.ansi.enabled", prior)
