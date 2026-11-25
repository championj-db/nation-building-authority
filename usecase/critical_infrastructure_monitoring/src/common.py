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
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Registration plates
# ---------------------------------------------------------------------------
# Synthetic Australian heavy-vehicle format XX99XX (two letters, two digits,
# two letters). The expression below bijectively encodes a numeric seed into
# that alphabet, so plates are deterministic and collision-free without any
# lookup table.
PLATE_REGEX = r"^[A-Z]{2}[0-9]{2}[A-Z]{2}$"


PLATE_SPACE = 26 * 26 * 10 * 10 * 26 * 26  # every XX99XX plate
# Affine scramble seed -> seed * A + B (mod PLATE_SPACE). A (~space / golden ratio) is coprime with it
# (no factor of 2, 5 or 13), so the map is a bijection: plates stay unique, but sequential
# ids no longer all start with "AA0", which reads as test data in a demo.
PLATE_SCRAMBLE_A = 28243009  # ~PLATE_SPACE / golden ratio, coprime with it
PLATE_SCRAMBLE_B = 1234567


def plate_expr(seed_col: str = "id") -> str:
    """SQL expression mapping a numeric seed column to a unique XX99XX plate."""
    s = f"pmod(cast({seed_col} as bigint) * {PLATE_SCRAMBLE_A} + {PLATE_SCRAMBLE_B}, {PLATE_SPACE})"
    return (
        "concat("
        f"char(65 + floor({s} / 1757600) % 26), "
        f"char(65 + floor({s} / 67600) % 26), "
        f"cast(floor({s} / 2600) % 10 as string), "
        f"cast(floor({s} / 260) % 10 as string), "
        f"char(65 + floor({s} / 10) % 26), "
        f"char(65 + {s} % 26))"
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

# Per-asset intensity: real fleets have a spread of offenders, not a cohort of identical
# ones. Each risk asset draws a propensity in [lo, hi] percent, skewed so most offenders
# are moderate and a few are severe. Without this every cohort member scores the same.
COHORT_INTENSITY_PCT = {
    "fatigue": (25, 85),          # share of movements pushed into night hours
    "route": (30, 90),            # share of movements on the unusual corridor
    "mass": (20, 85),             # share of movements loaded over registered mass
    "roadworthiness": (30, 90),   # chance an inspection records a defect
}
INTENSITY_SKEW = 1.6

# Escalation storyline: a share of risk assets intensify activity in the last few days,
# which the recent_pattern factor detects. ESCALATION_DAYS matches the feature step's
# recent_days default.
ESCALATING_ASSET_PCT = 35
ESCALATION_SHARE_PCT = (25, 60)
ESCALATION_DAYS = 3


def intensity_pct_expr(cohort: str, key_col: str) -> str:
    """SQL expression: the asset's deterministic propensity (percent) for its cohort."""
    lo, hi = COHORT_INTENSITY_PCT[cohort]
    u = f"(pmod(hash('intensity_{cohort}', {key_col}), 1000) / 1000.0)"
    return f"({lo} + ({hi} - {lo}) * pow({u}, {INTENSITY_SKEW}))"

# ---------------------------------------------------------------------------
# Risk scoring engine (illustrative, transparent, human-in-the-loop)
# ---------------------------------------------------------------------------
# Per-entity scores are a weighted sum of normalised factors. This is a rules
# engine, not a trained model: every score resolves to contributing factors an
# officer can read, which is the design intent (decision support, not
# automated enforcement).
RISK_TYPES = ["fatigue", "roadworthiness", "mass", "route"]

FACTOR_WEIGHTS = {
    # Each risk type: ~70% primary evidence, 15-20% escalation (recent_pattern), the rest
    # corroborating. A fully evidenced offender scores ~70 (alerts); escalation lifts it
    # into the critical band, so priority 1 means "strong evidence and getting worse".
    "fatigue": {
        "rest_window_anomaly": 0.40,
        "night_movement": 0.30,
        "recent_pattern": 0.20,
        "route_variance": 0.10,
    },
    "roadworthiness": {
        "defect_history": 0.70,
        "recent_pattern": 0.15,
        "night_movement": 0.05,
        "rest_window_anomaly": 0.05,
        "route_variance": 0.05,
    },
    "mass": {
        "mass_variance": 0.70,
        "recent_pattern": 0.15,
        "route_variance": 0.10,
        "night_movement": 0.05,
    },
    "route": {
        "route_variance": 0.70,
        "recent_pattern": 0.15,
        "night_movement": 0.10,
        "rest_window_anomaly": 0.05,
    },
}

# Factor normalisation bands: score = clip((raw - baseline) / (full - baseline), 0, 1).
# baseline is what a normal vehicle shows; full is unambiguous evidence. Stating both ends
# keeps every factor value readable as "share of the way from normal to clear evidence".
FACTOR_BANDS = {
    "rest_window_anomaly": ("rest_window_ratio", 0.05, 0.40),     # share of sightings 00:00-05:59
    "night_movement": ("night_sightings_ratio", 0.10, 0.65),      # share of sightings 20:00-05:59
    "recent_pattern": ("recent_surge_ratio", 1.30, 3.30),         # recent vs prior daily rate
    "route_variance": ("max_site_share", 0.08, 0.30),             # share at the single busiest site
    "mass_variance": ("over_mass_ratio", 0.03, 0.58),             # share of sightings over mass
    "defect_history": ("defect_points", 1.0, 8.0),                # defects + 2 x critical, 365 days
}


def factor_score_expr(factor: str) -> str:
    """SQL expression normalising a raw feature column into its 0-1 factor score."""
    column, baseline, full = FACTOR_BANDS[factor]
    return f"least(1.0, greatest(0.0, ({column} - {baseline}) / {full - baseline}))"


# Severity bands for the alert queue. Priority 1 rows are the design
# mock-up's "Open - priority 1" critical alerts.
SEVERITY_BANDS = {"critical": 85, "high": 75}
MODEL_VERSION = "transparent-rules-v2"

# Synthetic data generation. Each generation (data version + as-of date) lands in its own
# folder and silver resolves only the current one, so a rerun on a later day - or after a
# generator change - produces a clean world instead of stacking backfills. Bump this
# when the generator's behaviour changes.
DATA_VERSION = "synthetic-v3"


def generation_tag(as_of: str) -> str:
    """Landing sub-folder name for one synthetic generation."""
    return f"generation={DATA_VERSION}_{as_of}"

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


# The synthetic world runs on local Australian time. Hour-of-day semantics (night
# movement, rest window) and "today" are local-time concepts for a regulator, so every
# step that touches clock time sets the Spark session time zone to this value. Without
# it serverless runs in UTC and a "night movement" alert would show daytime sightings.
LOCAL_TIMEZONE = "Australia/Sydney"


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
