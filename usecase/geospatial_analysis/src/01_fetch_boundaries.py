# Databricks notebook source
# Step 1 of the geospatial analysis pipeline: real statistical boundaries (spatial ingest).
#
# Fetches ABS ASGS Edition 3 (2021) boundaries at run time - never committed to the repository -
# and conforms them into analysis-ready geometry:
#   SA1             61,845 small areas: where synthetic households are placed (step 4)
#   LGA, RA         full-resolution polygons for point-in-polygon containment (step 5)
#   SA2-SA4, state, LGA, RA
#                   ABS-generalised display polygons for the map (step 7)
#
# Raw GeoJSON pages land in the volume (bronze), are parsed with Spark into one row per feature,
# then conformed to WKB geometry with Databricks SQL spatial functions (silver). If ABS is
# unreachable the last good copy in the volume is reused and the provenance table says so.

# COMMAND ----------

import os
import sys

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir").strip()
_src_dir = next((c for c in [_src, os.path.join(_src, "src"), "."] if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import (  # noqa: E402
    ABS_ASGS, ABS_ATTRIBUTION, BOUNDARY_LEVELS, fq, geojson_features_sql, get_params, land_arcgis,
    record_provenance, volume_dir,
)

params = get_params({"catalog": "", "schema": "", "volume": "landing"}, dbutils)
CATALOG, SCHEMA, VOLUME = params["catalog"], params["schema"], params["volume"]
if not CATALOG or not SCHEMA:
    raise ValueError("catalog and schema parameters are required")
t = lambda name: fq(CATALOG, SCHEMA, name)  # noqa: E731
LANDING = volume_dir(CATALOG, SCHEMA, VOLUME, "boundaries")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Land the raw pages (bronze files)

# COMMAND ----------

provenance = []
for level, (service, analysis_layer, display_layer, code_field, name_field, generalise) in BOUNDARY_LEVELS.items():
    for kind, layer in (("analysis", analysis_layer), ("display", display_layer)):
        if layer is None:
            continue
        url = f"{ABS_ASGS}/{service}/MapServer/{layer}/query"
        fields = {code_field, name_field, "state_code_2021", "area_albers_sqkm"}
        if level == "sa1":
            fields |= {"sa2_code_2021", "sa2_name_2021", "sa3_code_2021", "sa3_name_2021", "sa4_code_2021", "sa4_name_2021"}
        n, cached, err = land_arcgis(
            url, os.path.join(LANDING, kind, level),
            out_fields=",".join(sorted(fields)),
            # generalised server-side: analysis layers per level, display layers to ~100 m (the
            # ABS "_GEN" layers are still far more detailed than a map needs)
            generalise_deg=generalise if kind == "analysis" else 0.001,
        )
        print(f"{kind:8} {level:6} {'cached' if cached else f'{n:,} features'}")
        provenance.append((f"asgs2021_{level}_{kind}", "Australian Bureau of Statistics", url, ABS_ATTRIBUTION,
                           "CC BY 4.0", n if n >= 0 else None, cached, err or None))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parse into one row per feature (bronze table)

# COMMAND ----------

frames = []
for kind in ("analysis", "display"):
    for level in BOUNDARY_LEVELS:
        path = os.path.join(LANDING, kind, level)
        if os.path.isdir(path):
            frames.append(spark.sql(geojson_features_sql(f"{path}/*.geojson")).selectExpr(
                f"'{level}' AS level", f"'{kind}' AS kind", "properties", "geometry_json", "source_file"))
bronze = frames[0]
for f in frames[1:]:
    bronze = bronze.unionByName(f)
bronze.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(t("bronze_boundary"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Conform geometry (silver)
# MAGIC Empty geometries are the ASGS non-spatial codes ("Migratory - Offshore - Shipping",
# MAGIC "No usual address") and are dropped. Invalid rings are repaired with ST_MakeValid.

# COMMAND ----------

def code_expr(level):
    _svc, _a, _d, code_field, name_field, _g = BOUNDARY_LEVELS[level]
    return f"properties['{code_field}']", f"properties['{name_field}']"


conformed = []
for level in BOUNDARY_LEVELS:
    code, name = code_expr(level)
    conformed.append(f"""
      SELECT level, kind, {code} AS code, {name} AS name, properties['state_code_2021'] AS state_code,
             CAST(properties['area_albers_sqkm'] AS DOUBLE) AS area_sqkm, properties,
             ST_MakeValid(ST_GeomFromGeoJSON(geometry_json)) AS geom
      FROM {t('bronze_boundary')}
      WHERE level = '{level}' AND geometry_json IS NOT NULL AND geometry_json <> 'null'
    """)
spark.sql(f"""
CREATE OR REPLACE TABLE {t('silver_boundary')}
COMMENT 'ABS ASGS 2021 boundaries as WKB geometry (SRID 4326). kind = analysis (containment) or display (map).'
AS
SELECT level, kind, code, name, state_code, area_sqkm, properties, ST_AsBinary(geom) AS geom_wkb,
       ST_XMin(geom) AS xmin, ST_XMax(geom) AS xmax, ST_YMin(geom) AS ymin, ST_YMax(geom) AS ymax,
       ST_NPoints(geom) AS n_points
FROM ({' UNION ALL '.join(conformed)})
WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom)
""")

# SA1 is the placement frame for synthetic households: keep its ASGS hierarchy, its bounding box
# and how much of that box it fills (drives how many candidate points rejection sampling needs).
spark.sql(f"""
CREATE OR REPLACE TABLE {t('silver_sa1')}
COMMENT 'ABS SA1 2021 polygons with their ASGS hierarchy - the frame synthetic households are placed in'
AS
SELECT code AS sa1_code,
       properties['sa2_code_2021'] AS sa2_code, properties['sa2_name_2021'] AS sa2_name,
       properties['sa3_code_2021'] AS sa3_code, properties['sa3_name_2021'] AS sa3_name,
       properties['sa4_code_2021'] AS sa4_code, properties['sa4_name_2021'] AS sa4_name,
       state_code, area_sqkm, geom_wkb, xmin, xmax, ymin, ymax,
       greatest(0.02, least(1.0, ST_Area(ST_GeomFromWKB(geom_wkb)) /
         greatest(1e-12, (xmax - xmin) * (ymax - ymin)))) AS fill_ratio
FROM {t('silver_boundary')}
WHERE level = 'sa1' AND kind = 'analysis'
""")

record_provenance(spark, t("ref_source"), "boundaries", provenance)

display(spark.sql(f"""
  SELECT level, kind, count(*) AS features, sum(n_points) AS vertices
  FROM {t('silver_boundary')} GROUP BY level, kind ORDER BY kind, level
"""))
