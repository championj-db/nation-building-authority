# Databricks notebook source
# Step 3 of the geospatial analysis pipeline: real essential-service locations.
#
# Fetches four national point layers at run time (all CC BY 4.0):
#   public_hospital        Declared Public Hospitals             Digital Atlas of Australia
#   urgent_care            Medicare Urgent Care Clinics          Digital Atlas of Australia
#   residential_aged_care  Australian Aged Care Services         Digital Atlas of Australia
#   ambulance_station      Emergency Management Facilities       Geoscience Australia
#
# Conforms them to one schema, drops points outside Australia, removes duplicates (the same
# service listed twice at the same place) and H3-indexes every site.

# COMMAND ----------

import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import AU_BBOX, SERVICE_TYPES, STATE_ABBR_TO_CODE, STATES, fq, geojson_features_sql, get_params, land_arcgis, record_provenance, volume_dir  # noqa: E402

params = get_params({"catalog": "", "schema": "", "volume": "landing", "h3_resolution": "8"}, dbutils)
CATALOG, SCHEMA, VOLUME = params["catalog"], params["schema"], params["volume"]
H3_RES = int(params["h3_resolution"])
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731
LANDING = volume_dir(CATALOG, SCHEMA, VOLUME, "services")

# COMMAND ----------

provenance = []
for key, svc in SERVICE_TYPES.items():
    n, cached, err = land_arcgis(svc["url"], os.path.join(LANDING, key), where=svc["where"], page_size=1000)
    print(f"{key:24} {'cached' if cached else f'{n:,} features'}")
    provenance.append((f"service_{key}", svc["publisher"], svc["url"], svc["attribution"], "CC BY 4.0",
                       n if n >= 0 else None, cached, err or None))

# COMMAND ----------

def field(name):
    return f"properties['{name}']" if name else "CAST(NULL AS STRING)"


parts = []
for key, svc in SERVICE_TYPES.items():
    name_f, addr_f, suburb_f, state_f, pc_f = svc["fields"]
    parts.append(f"""
      SELECT '{key}' AS service_type, properties, geometry_json,
             trim({field(name_f)}) AS name, trim({field(addr_f)}) AS address, initcap(trim({field(suburb_f)})) AS suburb,
             upper(trim({field(state_f)})) AS state_abbr, trim({field(pc_f)}) AS postcode
      FROM ({geojson_features_sql(os.path.join(LANDING, key) + '/*.geojson')})
    """)
spark.sql(" UNION ALL ".join(parts)).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(t("bronze_service_site"))

# COMMAND ----------

# State by point-in-polygon against the ABS state boundaries (step 1); the source's own state text
# (an abbreviation in some layers, a full name in others) is the fallback for points that fall
# just outside the coastline.
state_map = " ".join(f"WHEN '{abbr}' THEN '{code}'" for abbr, code in STATE_ABBR_TO_CODE.items())
state_map += " " + " ".join(f"WHEN '{name.upper()}' THEN '{code}'" for code, (_a, name) in STATES.items())
xmin, ymin, xmax, ymax = AU_BBOX
spark.sql(f"""
CREATE OR REPLACE TABLE {t('silver_service_site')}
COMMENT 'Essential-service sites from public sources, conformed, de-duplicated and H3-indexed'
AS
WITH pts AS (
  SELECT service_type, name, address, suburb, state_abbr, postcode,
         ST_X(ST_GeomFromGeoJSON(geometry_json)) AS longitude,
         ST_Y(ST_GeomFromGeoJSON(geometry_json)) AS latitude,
         properties
  FROM {t('bronze_service_site')}
  WHERE geometry_json IS NOT NULL AND geometry_json <> 'null'
),
valid AS (
  SELECT * FROM pts
  WHERE longitude BETWEEN {xmin} AND {xmax} AND latitude BETWEEN {ymin} AND {ymax} AND name IS NOT NULL
),
states AS (
  SELECT code AS state_code, ST_GeomFromWKB(geom_wkb, 4326) AS geom
  FROM {t('silver_boundary')} WHERE level = 'state' AND kind = 'display'
),
located AS (
  SELECT v.*, s.state_code AS state_code_spatial
  FROM valid v LEFT JOIN states s ON ST_Contains(s.geom, ST_Point(v.longitude, v.latitude, 4326))
),
dedup AS (
  SELECT *, row_number() OVER (
    PARTITION BY service_type, lower(name), round(longitude, 3), round(latitude, 3) ORDER BY address) AS rn
  FROM located
)
SELECT
  concat(service_type, ':', substr(sha2(concat_ws('|', service_type, lower(name), round(longitude, 4), round(latitude, 4)), 256), 1, 12)) AS site_id,
  service_type, initcap(name) AS name, address, suburb,
  coalesce(state_code_spatial, CASE state_abbr {state_map} END) AS state_code, postcode, longitude, latitude,
  h3_longlatash3(longitude, latitude, {H3_RES}) AS h3_cell,
  CASE WHEN service_type = 'residential_aged_care' THEN CAST(properties['Residential_Places'] AS INT) END AS capacity_places
FROM dedup WHERE rn = 1
""")

record_provenance(spark, t("ref_source"), "services", provenance)
display(spark.sql(f"SELECT service_type, count(*) AS sites, count_if(state_code IS NULL) AS no_state FROM {t('silver_service_site')} GROUP BY 1 ORDER BY 1"))
