"""Shared model contract for the geospatial analysis use case.

Spatial Service Planner: how far do Australians live from the essential services they rely on,
and where would a new site close the gap? Every pipeline step imports this module so the public
data fetchers (01-03), the synthetic household generator (04), the containment and proximity
analysis (05, 06) and the gold aggregates (07) agree on the same sources, geographies, service
types and constants. If a definition changes it changes here.

No environment-specific value lives in this file: catalog, schema and volume names arrive as job
parameters, never as literals.

Data provenance
  real, public   ABS ASGS 2021 boundaries (CC BY 4.0), ABS estimated resident population by SA2
                 (CC BY 4.0), service locations from the Digital Atlas of Australia and Geoscience
                 Australia (CC BY 4.0). Fetched at run time, never committed.
  synthetic      household locations and attributes. Seeded and deterministic; distributed in
                 proportion to the real population, but no record describes a real household.
"""

import json
import math
import os
import time
import urllib.parse
import urllib.request

USER_AGENT = "nba-geospatial-analysis/1.0"

# ---------------------------------------------------------------------------
# States and territories (ASGS 2021 state codes)
# ---------------------------------------------------------------------------
STATES = {
    "1": ("NSW", "New South Wales"),
    "2": ("VIC", "Victoria"),
    "3": ("QLD", "Queensland"),
    "4": ("SA", "South Australia"),
    "5": ("WA", "Western Australia"),
    "6": ("TAS", "Tasmania"),
    "7": ("NT", "Northern Territory"),
    "8": ("ACT", "Australian Capital Territory"),
    # 9 = Other Territories (Jervis Bay, Christmas and Cocos Islands, Norfolk Island). Kept in the
    # analysis; small populations, so most of its aggregates are suppressed.
    "9": ("OT", "Other Territories"),
}
STATE_ABBR_TO_CODE = {abbr: code for code, (abbr, _name) in STATES.items()}

# Remoteness Area class is the last digit of the ASGS 2021 RA code (e.g. 13 = NSW, Remote).
REMOTENESS = {
    "0": "Major Cities",
    "1": "Inner Regional",
    "2": "Outer Regional",
    "3": "Remote",
    "4": "Very Remote",
}

# ---------------------------------------------------------------------------
# Boundaries - ABS Australian Statistical Geography Standard (ASGS) Edition 3, 2021
# ---------------------------------------------------------------------------
ABS_ASGS = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021"
ABS_ATTRIBUTION = (
    "Australian Bureau of Statistics, Australian Statistical Geography Standard (ASGS) Edition 3, "
    "CC BY 4.0"
)

# level: (ArcGIS service, analysis layer, display layer, code field, name field, generalise deg)
#   analysis layer   full-resolution polygons used for containment (generalised lightly on fetch)
#   display layer    the ABS-generalised "_GEN" layer used for map display
BOUNDARY_LEVELS = {
    "sa1": ("SA1", 0, None, "sa1_code_2021", "sa1_code_2021", 0.0003),
    "sa2": ("SA2", None, 1, "sa2_code_2021", "sa2_name_2021", 0.0005),
    "sa3": ("SA3", None, 1, "sa3_code_2021", "sa3_name_2021", 0.0005),
    "sa4": ("SA4", None, 1, "sa4_code_2021", "sa4_name_2021", 0.0005),
    "state": ("STE", None, 1, "state_code_2021", "state_name_2021", 0.0005),
    "lga": ("LGA", 0, 1, "lga_code_2021", "lga_name_2021", 0.0005),
    "ra": ("RA", 0, 1, "ra_code_2021", "ra_name_2021", 0.001),
}

# Geographies the app can analyse and map. Each household is assigned to exactly one region at
# every level: SA2-SA4 and state by nesting (ASGS hierarchy), LGA and RA by point-in-polygon.
GEO_LEVELS = {
    "sa4": "Planning regions (SA4)",
    "sa3": "Service districts (SA3)",
    "sa2": "Statistical areas (SA2)",
    "lga": "Local government areas",
    "ra": "Remoteness areas",
    "state": "States and territories",
}

# ---------------------------------------------------------------------------
# Population - ABS estimated resident population (ERP) by SA2, age and sex
# ---------------------------------------------------------------------------
ABS_ERP_URL = "https://data.api.abs.gov.au/rest/data/ABS,ERP_ASGS2021,1.0.0/ERP.3..SA2..A"
ABS_ERP_ATTRIBUTION = (
    "Australian Bureau of Statistics, Regional population by age and sex (ERP_ASGS2021), CC BY 4.0"
)
AGE_65_PLUS = ["A65", "A70", "A75", "A80", "8599"]

# ---------------------------------------------------------------------------
# Essential services - real public locations
# ---------------------------------------------------------------------------
_DIGITAL_ATLAS = "https://services5.arcgis.com/OvOcYIrJnM97ABBA/ArcGIS/rest/services"
_GA_EMF = "https://services.ga.gov.au/gis/rest/services/Emergency_Management_Facilities/MapServer"

# key: label, description, url, where, field map (name, address, suburb, state, postcode),
#      default access threshold (km), publisher, attribution
SERVICE_TYPES = {
    "public_hospital": {
        "label": "Public hospitals",
        "description": "Hospitals declared as public hospitals for health insurance purposes.",
        "url": f"{_DIGITAL_ATLAS}/Declared_Public_Hospitals/FeatureServer/0/query",
        "where": "1=1",
        "fields": ("DRVD_HSPTL_NM", "DRVD_HSPTL_STREET", "DRVD_HSPTL_SUBRB_NM", "HSPTL_ST", "HSPTL_PCDE_CD"),
        "default_threshold_km": 45,
        "publisher": "Department of Health, Disability and Ageing via the Digital Atlas of Australia",
        "attribution": "Declared Public Hospitals, Department of Health, Disability and Ageing, CC BY 4.0",
    },
    "urgent_care": {
        "label": "Medicare Urgent Care Clinics",
        "description": "Clinics treating urgent but not life-threatening conditions, bulk billed.",
        "url": f"{_DIGITAL_ATLAS}/Medicare_Urgent_Care_Clinics/FeatureServer/0/query",
        "where": "1=1",
        "fields": ("Clinic_Name", "Address", None, "State", None),
        "default_threshold_km": 30,
        "publisher": "Department of Health, Disability and Ageing via the Digital Atlas of Australia",
        "attribution": "Medicare Urgent Care Clinics, Department of Health, Disability and Ageing, CC BY 4.0",
    },
    "residential_aged_care": {
        "label": "Residential aged care",
        "description": "Australian Government subsidised residential aged care services.",
        "url": f"{_DIGITAL_ATLAS}/Australian_Aged_Care_Services/FeatureServer/0/query",
        "where": "Care_Type = 'Residential'",
        "fields": ("Service_Name", "Physical_Address", "Physical_Suburb", "Physical_State", "Physical_Post_Code"),
        "default_threshold_km": 30,
        "publisher": "Department of Health, Disability and Ageing via the Digital Atlas of Australia",
        "attribution": "Australian Aged Care Services, Department of Health, Disability and Ageing, based on AIHW material, CC BY 4.0",
    },
    "ambulance_station": {
        "label": "Ambulance stations",
        "description": "Known ambulance station locations.",
        "url": f"{_GA_EMF}/0/query",
        "where": "1=1",
        "fields": ("facility_name", "facility_address", "abs_suburb", "facility_state", "abs_postcode"),
        "default_threshold_km": 25,
        "publisher": "Geoscience Australia",
        "attribution": "Emergency Management Facilities, Geoscience Australia, CC BY 4.0",
    },
}

# Mainland plus Tasmania and the near islands; anything outside is a geocoding error.
AU_BBOX = (112.0, -44.5, 154.5, -9.0)

# ---------------------------------------------------------------------------
# Synthetic households (ABS 2021 Census-shaped distributions)
# ---------------------------------------------------------------------------
# Persons per household, ABS 2021 Census (household composition by number of persons usually
# resident). 6 stands for "6 or more".
HOUSEHOLD_SIZE_WEIGHTS = {1: 25.6, 2: 34.2, 3: 15.6, 4: 14.8, 5: 6.5, 6: 3.3}
MEAN_HOUSEHOLD_SIZE = sum(k * w for k, w in HOUSEHOLD_SIZE_WEIGHTS.items()) / sum(HOUSEHOLD_SIZE_WEIGHTS.values())

# Tenure, ABS 2021 Census (occupied private dwellings).
TENURE_WEIGHTS = {"owned_outright": 31.0, "owned_with_mortgage": 35.0, "rented": 30.6, "other": 3.4}

# Share of households with no registered motor vehicle, by remoteness class. Shaped on the ABS
# 2021 Census pattern (higher in inner cities and very remote communities); applied per household
# with a seeded hash, so it is a modelled attribute, not a measured one.
NO_VEHICLE_RATE = {"0": 0.085, "1": 0.050, "2": 0.058, "3": 0.075, "4": 0.160}

# ---------------------------------------------------------------------------
# Spatial analysis constants
# ---------------------------------------------------------------------------
# Nearest-service search prunes with two H3 levels before measuring exact distances. For a
# point inside a cell whose centre is c, if the nearest site to c is d_min away, the point's true
# nearest site is within d_min + 2r of c, where r bounds the cell's centre-to-vertex distance.
# Using a generous r keeps the search exact while cutting all-pairs work by orders of magnitude.
PRUNE_LEVELS = [(5, 12.0), (8, 0.8)]   # (H3 resolution, r in km - above the max circumradius)
CONTAIN_H3_RES = 6                     # tessellation resolution for LGA / RA containment
DISTANCE_BAND_CAP_KM = 300             # distances are aggregated in 1 km bands; 300 = 300 km or more
EARTH_RADIUS_KM = 6371.0088


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_params(defaults: dict, dbutils) -> dict:
    """Read notebook widgets, creating each with its default first."""
    out = {}
    for key, default in defaults.items():
        dbutils.widgets.text(key, str(default))
        out[key] = dbutils.widgets.get(key).strip()
    return out


def fq(catalog: str, schema: str, name: str) -> str:
    return f"{catalog}.{schema}.{name}"


def volume_dir(catalog: str, schema: str, volume: str, *parts: str) -> str:
    return os.path.join(f"/Volumes/{catalog}/{schema}/{volume}", *parts)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def haversine_km_expr(lat1: str, lon1: str, lat2: str, lon2: str) -> str:
    """Spark SQL great-circle distance in km (cheap pruning; exact distances use ST_DistanceSphere)."""
    return (
        f"2 * {EARTH_RADIUS_KM} * asin(least(1.0, sqrt("
        f"pow(sin(radians({lat2} - {lat1}) / 2), 2) + "
        f"cos(radians({lat1})) * cos(radians({lat2})) * pow(sin(radians({lon2} - {lon1}) / 2), 2))))"
    )


def hash_uniform_expr(*parts: str) -> str:
    """A deterministic uniform [0, 1) from the given SQL expressions - a seeded, reproducible rand()."""
    return f"(pmod(xxhash64({', '.join(parts)}), 1000000007) / 1000000007.0)"


def weighted_choice_expr(u: str, weights: dict) -> str:
    """CASE expression picking a key of `weights` from a uniform `u` (keys rendered as SQL literals)."""
    total = sum(weights.values())
    acc, branches = 0.0, []
    items = list(weights.items())
    for key, w in items[:-1]:
        acc += w / total
        lit = key if isinstance(key, (int, float)) else f"'{key}'"
        branches.append(f"WHEN {u} < {acc:.6f} THEN {lit}")
    last = items[-1][0]
    last_lit = last if isinstance(last, (int, float)) else f"'{last}'"
    return f"CASE {' '.join(branches)} ELSE {last_lit} END"


def http_get(url: str, accept: str | None = None, retries: int = 3, timeout: int = 120) -> bytes:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # network, HTTP or timeout
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last}")


def arcgis_pages(url: str, where: str = "1=1", out_fields: str = "*", generalise_deg: float | None = None,
                 page_size: int = 2000):
    """Yield GeoJSON pages (bytes) from an ArcGIS query endpoint, in WGS84."""
    offset = 0
    while True:
        params = {
            "where": where, "outFields": out_fields, "returnGeometry": "true", "outSR": "4326",
            "geometryPrecision": 6, "resultOffset": offset, "resultRecordCount": page_size,
            "orderByFields": "objectid", "f": "geojson",
        }
        if generalise_deg:
            params["maxAllowableOffset"] = generalise_deg
        raw = http_get(f"{url}?{urllib.parse.urlencode(params)}")
        page = json.loads(raw)
        if "error" in page:
            raise RuntimeError(f"ArcGIS error from {url}: {page['error']}")
        features = page.get("features", [])
        yield raw, len(features)
        more = page.get("exceededTransferLimit") or (page.get("properties") or {}).get("exceededTransferLimit")
        if not more or not features:
            break
        offset += len(features)


def land_arcgis(url: str, target_dir: str, **kwargs) -> tuple[int, bool, str]:
    """Fetch an ArcGIS layer into target_dir as page-NNNN.geojson files.

    Pages are written to a staging folder and swapped in only when the whole layer arrived, so a
    failed fetch never leaves a half-written layer. If the source is unreachable and a previous
    copy exists, that copy is kept (returns from_cache=True), so a demo never depends on a
    third-party service being up; with no copy at all it fails loudly.
    """
    staging = target_dir.rstrip("/") + "._staging"
    try:
        _clear_dir(staging)
        os.makedirs(staging, exist_ok=True)
        total = 0
        for i, (raw, n) in enumerate(arcgis_pages(url, **kwargs)):
            with open(os.path.join(staging, f"page-{i:04d}.geojson"), "wb") as fh:
                fh.write(raw)
            total += n
        if total == 0:
            raise RuntimeError("source returned no features")
        _clear_dir(target_dir)
        os.rename(staging, target_dir)
        return total, False, ""
    except Exception as exc:
        _clear_dir(staging)
        if os.path.isdir(target_dir) and any(f.endswith(".geojson") for f in os.listdir(target_dir)):
            print(f"WARNING: fetch failed ({exc}); keeping the last good copy in {target_dir}")
            return -1, True, str(exc)[:500]
        raise RuntimeError(f"Could not fetch {url} and no cached copy exists: {exc}") from exc


def _clear_dir(path: str) -> None:
    if os.path.isdir(path):
        for name in os.listdir(path):
            os.remove(os.path.join(path, name))
        os.rmdir(path)


PROVENANCE_SCHEMA = (
    "dataset string, step string, publisher string, source_url string, attribution string, "
    "licence string, features long, from_cache boolean, fetch_error string, fetched_at timestamp"
)


def record_provenance(spark, table: str, step: str, rows: list[tuple]) -> None:
    """Replace this step's rows in the provenance table (dataset, publisher, url, attribution,
    licence, features, from_cache, fetch_error). fetched_at is stamped here."""
    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    spark.sql(f"CREATE TABLE IF NOT EXISTS {table} ({PROVENANCE_SCHEMA}) "
              "COMMENT 'Where every public input came from, and whether the last fetch used a cached copy'")
    spark.sql(f"DELETE FROM {table} WHERE step = '{step}'")
    full = [(r[0], step, *r[1:], now) for r in rows]
    spark.createDataFrame(full, PROVENANCE_SCHEMA).write.mode("append").saveAsTable(table)


def geojson_features_sql(path_glob: str) -> str:
    """SQL reading landed GeoJSON pages into one row per feature, geometry kept as raw JSON text."""
    return f"""
        SELECT f.properties AS properties, f.geometry AS geometry_json, _metadata.file_path AS source_file
        FROM (
          SELECT explode(from_json(value,
            'struct<features: array<struct<properties: map<string, string>, geometry: string>>>').features) AS f,
            _metadata
          FROM read_files('{path_glob}', format => 'text', wholeText => true)
        )
    """
