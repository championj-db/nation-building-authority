"""Shared model definitions for the critical infrastructure monitoring use case.

Every pipeline step imports this module so that the synthetic generators
(01, 02), the identity resolver (04) and the risk engine (05, 06) all agree on
the same registration plate alphabet, OCR confusion classes, site catalogue,
risk factor weights and alert copy. If a definition changes, it changes here
and every step picks it up on the next run.

No environment-specific value lives in this file: catalog, schema and volume
names arrive as job parameters, never as literals.
"""

import datetime as dt
from contextlib import contextmanager

# ---------------------------------------------------------------------------
# Registration plates
# ---------------------------------------------------------------------------
# Synthetic Australian heavy-vehicle format XX99XX (two letters, two digits,
# two letters). The expression below bijectively encodes a numeric seed into
# that alphabet, so plates are deterministic and collision-free without any
# lookup table.
PLATE_REGEX = r"^[A-Z]{2}[0-9]{2}[A-Z]{2}$"


def plate_expr(seed_col: str = "id") -> str:
    """SQL expression mapping a numeric seed column to a unique XX99XX plate."""
    return (
        "concat("
        f"char(65 + floor({seed_col} / 1757600) % 26), "
        f"char(65 + floor({seed_col} / 67600) % 26), "
        f"cast(floor({seed_col} / 2600) % 10 as string), "
        f"cast(floor({seed_col} / 260) % 10 as string), "
        f"char(65 + floor({seed_col} / 10) % 26), "
        f"char(65 + {seed_col} % 26))"
    )


# ---------------------------------------------------------------------------
# OCR confusion classes
# ---------------------------------------------------------------------------
# The telemetry generator (02) injects camera read errors by substituting a
# single character through this map; the resolver (04) canonicalises the same
# classes back to a single representative character per class. The two sides
# must change together or resolution breaks.
OCR_CONFUSION_SRC = "OB8SIZ2G6DQ"
OCR_CONFUSION_DST = "08B512Z6G00"


def canonical_plate_expr(col: str) -> str:
    """SQL expression collapsing each OCR confusion class to one representative."""
    return f"translate({col}, '0OQD8BS15IZ26G', 'OOOB8BSIIIZZGG')"


# ---------------------------------------------------------------------------
# Synthetic reference data vocabularies (public Australian geography)
# ---------------------------------------------------------------------------
OPERATOR_NAME_REGIONS = [
    "Southern", "Eastline", "North Coast", "Metro", "Western", "Central",
    "Murray", "Sunrise", "Outback", "Coastal", "Northern", "Regional",
]
OPERATOR_NAME_DOMAINS = [
    "Freight", "Civil", "Produce", "Aggregate", "Livestock", "Fuel",
    "Grain", "Steel", "Timber", "Waste",
]
OPERATOR_NAME_SUFFIXES = [
    "Logistics", "Haulage", "Transport", "Cartage", "Carriers", "Freightlines",
]

OPERATOR_TYPES = ["general", "freight", "construction", "agriculture", "bulk"]
OPERATOR_STATES = ["NSW", "VIC", "QLD", "WA", "SA", "TAS", "NT", "ACT"]

# Sighting sites: road, locality, state, latitude, longitude. Real public
# geography, fictional traffic. The design mock-up places alerts on the Hume
# Hwy at Marulan, the New England Hwy at Hexham and the Pacific Hwy at Grafton.
SITE_CATALOGUE = [
    ("Hume Hwy", "Marulan", "NSW", -34.71, 150.38),
    ("New England Hwy", "Hexham", "NSW", -32.83, 151.64),
    ("Pacific Hwy", "Grafton", "NSW", -29.69, 152.93),
    ("Hume Hwy", "Tarcutta", "NSW", -35.30, 147.90),
    ("Princes Hwy", "Nowra", "NSW", -34.88, 150.60),
    ("Great Western Hwy", "Katoomba", "NSW", -33.71, 150.31),
    ("Federal Hwy", "Goulburn", "NSW", -34.98, 149.73),
    ("Oxley Hwy", "Wauchope", "NSW", -31.57, 152.58),
    ("Bruce Hwy", "Caboolture", "QLD", -27.08, 152.95),
    ("Bruce Hwy", "Gympie", "QLD", -26.19, 152.67),
    ("Cunningham Hwy", "Warwick", "QLD", -28.21, 152.10),
    ("Pacific Motorway", "Tugun", "QLD", -28.16, 153.50),
    ("Warrego Hwy", "Toowoomba", "QLD", -27.56, 151.95),
    ("Monash Fwy", "Warragul", "VIC", -38.16, 145.93),
    ("Hume Hwy", "Wodonga", "VIC", -36.12, 146.88),
    ("Western Hwy", "Ballarat", "VIC", -37.56, 143.86),
    ("Princes Hwy", "Traralgon", "VIC", -38.20, 146.54),
    ("Sturt Hwy", "Mildura", "VIC", -34.19, 142.13),
    ("Great Eastern Hwy", "Kalgoorlie", "WA", -30.75, 121.47),
    ("Mitchell Fwy", "Joondalup", "WA", -31.74, 115.77),
    ("Stuart Hwy", "Katherine", "NT", -14.46, 132.26),
    ("Barkly Hwy", "Tennant Creek", "NT", -19.65, 134.19),
    ("Dukes Hwy", "Bordertown", "SA", -36.31, 140.78),
    ("Augusta Hwy", "Port Pirie", "SA", -33.19, 138.01),
]
SITE_TYPES = ["anpr_camera", "weigh_in_motion", "gps_gateway"]

ASSET_TYPES = [
    "prime mover", "prime mover + trailer", "b-double", "tipper", "tanker",
]
INSPECTION_TYPES = ["routine", "roadside", "annual"]
DEFECT_CODES = [
    "brakes", "tyres", "suspension", "lighting", "load restraint",
]

# ---------------------------------------------------------------------------
# Telemetry model constants
# ---------------------------------------------------------------------------
# Hour-of-day buckets used by the generator and the feature builder. The
# fatigue engines care about rest-window movement (00:00-05:59) and night
# movement (20:00-05:59).
NIGHT_HOURS = [20, 21, 22, 23, 0, 1, 2, 3, 4, 5]
DAY_HOURS = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
REST_WINDOW_END_HOUR = 6  # exclusive: rest window is [00:00, 06:00)

# Mass model: normal sightings sit below the registered mass; over-mass
# cohorts overload above it. The over-mass feature uses the threshold below.
OVER_MASS_RATIO_THRESHOLD = 1.05
NORMAL_MASS_MULTIPLIERS = (0.82, 1.02)
OVERLOAD_MASS_MULTIPLIERS = (1.06, 1.24)

SIGHTING_SOURCES = ["anpr_camera", "weigh_in_motion", "gps_gateway"]

# ---------------------------------------------------------------------------
# Risk scoring engine (illustrative, transparent, human-in-the-loop)
# ---------------------------------------------------------------------------
# Per-entity scores are a weighted sum of normalised factors. This is a rules
# engine, not a trained model: every score resolves to contributing factors an
# officer can read, which is the design intent (decision support, not
# automated enforcement).
RISK_TYPES = ["fatigue", "roadworthiness", "mass", "route"]

FACTOR_WEIGHTS = {
    "fatigue": {
        "rest_window_anomaly": 0.40,
        "night_movement": 0.30,
        "recent_pattern": 0.20,
        "route_variance": 0.10,
    },
    "roadworthiness": {
        "defect_history": 0.50,
        "recent_pattern": 0.15,
        "night_movement": 0.15,
        "rest_window_anomaly": 0.10,
        "route_variance": 0.10,
    },
    "mass": {
        "mass_variance": 0.55,
        "route_variance": 0.15,
        "recent_pattern": 0.15,
        "night_movement": 0.15,
    },
    "route": {
        "route_variance": 0.50,
        "recent_pattern": 0.20,
        "night_movement": 0.15,
        "rest_window_anomaly": 0.15,
    },
}

# Severity bands for the alert queue. Priority 1 rows are the design
# mock-up's "Open - priority 1" critical alerts.
SEVERITY_BANDS = {"critical": 85, "high": 75}
MODEL_VERSION = "transparent-rules-v1"

# Alert copy mirrors the operations-centre design mock-up so the dashboard
# reads exactly like the mock-up: title, machine-readable summary pattern and
# the two dispositions an officer can record.
ALERT_COPY = {
    "fatigue": ("Fatigue pattern detected", "Repeated night movement - rest-window anomaly"),
    "roadworthiness": ("Roadworthiness risk elevated", "Inspection history - repeated defect pattern"),
    "mass": ("Potential over-mass event", "Axle estimate - route and load variance"),
    "route": ("Route variance detected", "Unusual corridor concentration - pattern shift"),
}
DISPOSITIONS = ["route", "monitor"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_params(defaults: dict, dbutils) -> dict:
    """Register widgets with defaults, then read job-parameter overrides.

    Job tasks pass parameters through base_parameters, which arrive as widget
    values; interactive runs fall back to the defaults registered here.
    """
    for name, default in defaults.items():
        dbutils.widgets.text(name, str(default))
    return {name: dbutils.widgets.get(name) for name in defaults}


def resolve_as_of(raw: str) -> str:
    """Normalise the as-of date: blank means today."""
    return raw.strip() if raw and raw.strip() else dt.date.today().isoformat()


def fq_table(catalog: str, schema: str, name: str) -> str:
    """Fully-qualified Unity Catalog table name."""
    return f"{catalog}.{schema}.{name}"


def volume_dir(catalog: str, schema: str, volume: str, *parts: str) -> str:
    """Path inside this use case's landing volume."""
    return "/".join(["/Volumes", catalog, schema, volume, *filter(None, parts)])


@contextmanager
def ansi_sql_off(spark):
    """Temporarily disable ANSI SQL mode around dbldatagen builds.

    dbldatagen emits integer modulo arithmetic that can divide by zero under
    ANSI mode (the serverless default). The classic parser tolerates it, so we
    switch it off for the build and restore the prior value afterwards.
    """
    prior = spark.conf.get("spark.sql.ansi.enabled")
    spark.conf.set("spark.sql.ansi.enabled", "false")
    try:
        yield
    finally:
        spark.conf.set("spark.sql.ansi.enabled", prior)
