# Databricks notebook source
# Step 1 of the critical infrastructure monitoring pipeline: synthetic reference data for a
# national, cross-sector infrastructure network.
#
# Writes the asset registry the operations centre monitors:
#   dim_operator    fictional operators per sector
#   dim_asset       ~600 roads, rail, water and energy assets at real Australian localities
#   dim_sensor      one sensor per asset metric, with its engineering limits
#   dim_dependency  cross-sector supply links (a substation powers signalling, pumps, tunnels...)
#   dim_inspection  two years of condition inspections
#
# Reference data is small, so it is built in seeded Python (deterministic for a given seed),
# where nearest-neighbour dependency wiring is simplest to read.

# COMMAND ----------

import math
import os
import random
import sys

from pyspark.sql import types as T

# The shared model contract (common.py) lives in this use case's src/ folder.
dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir")
_candidates = [_src, os.path.dirname(_src) if _src.endswith(".py") else None, "src", "."]
_src_dir = next((c for c in _candidates if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import (
    ASSET_CLASSES, ASSET_SNAP_MAX_KM, LOCALITIES, METRICS, NETWORK_ASSET_CLASSES, OPERATORS, SECTORS,
    STORYLINE_LINKS, STORYLINES, get_params, haversine_km, local_now, resolve_as_of,
)
from network import Graph

params = get_params({"catalog": "", "schema": "", "seed": 42, "asset_scale": 6.25, "as_of": ""}, dbutils)
if not params["catalog"] or not params["schema"]:
    raise ValueError("catalog and schema parameters are required")

CATALOG, SCHEMA = params["catalog"], params["schema"]
SEED = int(params["seed"])
ASSET_SCALE = float(params["asset_scale"])  # assets per unit of class weight (6.25 -> ~600)
AS_OF = resolve_as_of(params["as_of"])
rng = random.Random(SEED)


def table(name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{name}"


# COMMAND ----------

# MAGIC %md
# MAGIC ## Operators

# COMMAND ----------

operators = []
for sector in SECTORS:
    for i, name in enumerate(OPERATORS[sector]):
        operators.append((f"OP-{sector[:2].upper()}{i + 1}", name, sector))
operator_ids = {sector: [o for o in operators if o[2] == sector] for sector in SECTORS}

spark.createDataFrame(operators, "operator_id string, operator_name string, sector string") \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("dim_operator"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Assets
# MAGIC Assets are placed at real localities, weighted by locality density, and jittered a few
# MAGIC kilometres so co-located assets do not overlap on the map. Each state's assets in a sector
# MAGIC belong to one operator, as real networks are typically run state by state.

# COMMAND ----------

STATE_ORDER = ["NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"]


def operator_for(sector: str, state: str) -> str:
    ops = operator_ids[sector]
    return ops[STATE_ORDER.index(state) % len(ops)][0]


assets = []
asset_id = 1000
for cls, (sector, label, prefix, weight, metrics, (p_lo, p_hi), needs_power, states) in ASSET_CLASSES.items():
    pool = [loc for loc in LOCALITIES if states is None or loc[1] in states]
    weights = [loc[4] for loc in pool]
    count = max(3, round(weight * ASSET_SCALE))
    for n in range(count):
        name, state, lat, lon, _w = rng.choices(pool, weights=weights, k=1)[0]
        asset_id += 1
        jlat, jlon = lat + rng.uniform(-0.06, 0.06), lon + rng.uniform(-0.07, 0.07)
        install_year = rng.randint(1955, 2022)
        # people served: log-uniform within the class range, rounded to the nearest hundred
        people = int(round(math.exp(rng.uniform(math.log(p_lo), math.log(p_hi))), -2))
        people = max(p_lo, min(p_hi, people))
        criticality = 1 + min(4, int((people - p_lo) / max(1, (p_hi - p_lo)) * 5))
        assets.append(dict(
            asset_id=asset_id,
            asset_code=f"{prefix}-{state}-{n + 1:03d}",
            asset_name=f"{name} {label.title()}",
            asset_class=cls, asset_class_label=label, sector=sector,
            operator_id=operator_for(sector, state),
            locality=name, state=state, latitude=round(jlat, 5), longitude=round(jlon, 5),
            install_year=install_year, people_served=people, criticality=criticality,
            needs_power=needs_power,
        ))

# Anchor each storyline asset at its locality: move the nearest asset of that class there, so
# "the Gippsland transmission line" really is in Gippsland whatever the random placement did.
loc_by_name = {loc[0]: loc for loc in LOCALITIES}
anchored = {}
for cls, locality, *_ in STORYLINES:
    name, state, lat, lon, _w = loc_by_name[locality]
    a = min((x for x in assets if x["asset_class"] == cls and x["asset_id"] not in anchored.values()),
            key=lambda x: haversine_km(lat, lon, x["latitude"], x["longitude"]))
    label = ASSET_CLASSES[cls][1]
    a.update(locality=name, state=state, latitude=round(lat + 0.02, 5), longitude=round(lon + 0.02, 5),
             operator_id=operator_for(a["sector"], state),
             asset_name=f"{name} {label.title()}")
    anchored[(cls, locality)] = a["asset_id"]

# Make names unique within a locality ("Penrith zone substation 2").
# Anchored storyline assets keep the plain name; any namesake gets a numeric suffix.
seen = {}
anchored_ids = set(anchored.values())
for a in sorted(assets, key=lambda x: x["asset_id"] not in anchored_ids):
    key = a["asset_name"]
    seen[key] = seen.get(key, 0) + 1
    if seen[key] > 1:
        a["asset_name"] = f"{key} {seen[key]}"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Put road and rail assets on the network
# MAGIC Road and rail assets snap onto the nearest node of the national key-route network (from
# MAGIC 01a_fetch_networks), so a bridge sits on its highway and an interlocking on its line. Assets
# MAGIC further than ASSET_SNAP_MAX_KM from a key route stay where they are, off-network.

# COMMAND ----------

graphs, mains, node_segment = {}, {}, {}
net_nodes = spark.table(table("ref_network_node")).select("node_id", "mode", "longitude", "latitude").collect()
net_edges = spark.table(table("ref_network_edge")).select("edge_id", "mode", "from_node", "to_node", "segment_id", "length_km").collect()
named = {r["segment_id"] for r in spark.table(table("ref_network_segment")).filter("name IS NOT NULL").select("segment_id").collect()}
for mode in ("road", "rail"):
    g = Graph.build([(r[0], r[2], r[3]) for r in net_nodes if r[1] == mode],
                    [(r[0], r[2], r[3], r[4], r[5]) for r in net_edges if r[1] == mode])
    graphs[mode], mains[mode] = g, g.main_component()
    for n in mains[mode]:
        segs = sorted({g.edges[e][2] for _m, e in g.adj[n]}, key=lambda sg: (sg not in named, sg))
        node_segment[(mode, n)] = segs[0]

for a in assets:
    a.update(network_mode=None, network_node_id=None, network_segment_id=None, network_snap_km=None)
    rule = NETWORK_ASSET_CLASSES.get(a["asset_class"])
    if not rule:
        continue
    mode = rule[0]
    g, main = graphs[mode], mains[mode]
    nearest = min(main, key=lambda n: haversine_km(a["latitude"], a["longitude"], g.xy[n][1], g.xy[n][0]))
    km = haversine_km(a["latitude"], a["longitude"], g.xy[nearest][1], g.xy[nearest][0])
    if km <= ASSET_SNAP_MAX_KM:
        a.update(network_mode=mode, network_node_id=nearest, network_segment_id=node_segment[(mode, nearest)],
                 network_snap_km=round(km, 2), longitude=round(g.xy[nearest][0], 5), latitude=round(g.xy[nearest][1], 5))

on_network = sum(1 for a in assets if a["network_mode"])
print(f"{on_network} of {sum(1 for a in assets if a['asset_class'] in NETWORK_ASSET_CLASSES)} road and rail assets placed on the key-route network")

asset_schema = T.StructType([
    T.StructField("asset_id", T.LongType()), T.StructField("asset_code", T.StringType()),
    T.StructField("asset_name", T.StringType()), T.StructField("asset_class", T.StringType()),
    T.StructField("asset_class_label", T.StringType()), T.StructField("sector", T.StringType()),
    T.StructField("operator_id", T.StringType()), T.StructField("locality", T.StringType()),
    T.StructField("state", T.StringType()), T.StructField("latitude", T.DoubleType()),
    T.StructField("longitude", T.DoubleType()), T.StructField("install_year", T.IntegerType()),
    T.StructField("people_served", T.LongType()), T.StructField("criticality", T.IntegerType()),
    T.StructField("needs_power", T.BooleanType()),
    T.StructField("network_mode", T.StringType()), T.StructField("network_node_id", T.StringType()),
    T.StructField("network_segment_id", T.StringType()), T.StructField("network_snap_km", T.DoubleType()),
])
spark.createDataFrame([tuple(a[f.name] for f in asset_schema.fields) for a in assets], asset_schema) \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("dim_asset"))
print(f"dim_asset: {len(assets)} assets across {len(ASSET_CLASSES)} classes")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sensors
# MAGIC One sensor per asset metric, carrying its engineering limits so silver and gold read the
# MAGIC thresholds from the registry, as an operator's asset system would provide them.

# COMMAND ----------

sensors = []
for a in assets:
    for metric in ASSET_CLASSES[a["asset_class"]][4]:
        label, unit, base, _sd, _d, warn, alarm, direction, kind = METRICS[metric]
        sensors.append((f"{a['asset_code']}-{metric}", a["asset_id"], metric, label, unit,
                        float(base), float(warn), float(alarm), direction, kind))
spark.createDataFrame(
    sensors,
    "sensor_id string, asset_id long, metric string, metric_label string, unit string, "
    "baseline double, warn_limit double, alarm_limit double, direction string, kind string",
).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("dim_sensor"))
print(f"dim_sensor: {len(sensors)} sensors")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cross-sector dependencies
# MAGIC The links that make this an operations centre rather than four monitoring screens:
# MAGIC * every asset that needs power is supplied by its nearest zone substation
# MAGIC * every zone substation is supplied by its nearest transmission line
# MAGIC * every reservoir is supplied by its nearest treatment plant (water supply)

# COMMAND ----------

def nearest(asset, candidates):
    return min(candidates, key=lambda c: haversine_km(asset["latitude"], asset["longitude"], c["latitude"], c["longitude"]))


by_class = {cls: [a for a in assets if a["asset_class"] == cls] for cls in ASSET_CLASSES}
deps = []
for a in assets:
    if a["needs_power"] and by_class["zone_substation"]:
        s = nearest(a, by_class["zone_substation"])
        deps.append((s["asset_id"], a["asset_id"], "power supply"))
# Storyline wiring: the hero substation also supplies the nearest dependants of these classes.
for (cls, locality), dependent_classes in STORYLINE_LINKS.items():
    hero = next(x for x in assets if x["asset_id"] == anchored[(cls, locality)])
    for dep_cls in dependent_classes:
        target = nearest(hero, by_class[dep_cls])
        deps = [d for d in deps if d[1] != target["asset_id"] or d[2] != "power supply"]
        deps.append((hero["asset_id"], target["asset_id"], "power supply"))
for s in by_class["zone_substation"]:
    t = nearest(s, by_class["transmission_line"])
    deps.append((t["asset_id"], s["asset_id"], "bulk power supply"))
for r in by_class["reservoir"]:
    p = nearest(r, by_class["treatment_plant"])
    deps.append((p["asset_id"], r["asset_id"], "water supply"))

spark.createDataFrame(deps, "upstream_asset_id long, downstream_asset_id long, dependency_type string") \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("dim_dependency"))
print(f"dim_dependency: {len(deps)} supply links")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Condition inspections
# MAGIC Older assets trend to worse condition grades (1 = as new, 5 = very poor). Some assets are
# MAGIC overdue: their last inspection is older than the 12-month interval.

# COMMAND ----------

import datetime as dt

today = dt.date.fromisoformat(AS_OF)
inspections = []
insp_id = 0
for a in assets:
    age = today.year - a["install_year"]
    base_grade = 1 + min(3.6, age / 18.0)
    overdue = rng.random() < 0.08
    last = today - dt.timedelta(days=rng.randint(400, 700) if overdue else rng.randint(10, 330))
    for k in range(rng.randint(2, 3)):
        insp_id += 1
        when = last - dt.timedelta(days=365 * k + rng.randint(0, 30))
        grade = max(1, min(5, round(base_grade + rng.uniform(-0.8, 0.9) - 0.3 * k)))
        defects = max(0, round((grade - 2) * rng.uniform(0.5, 1.6)))
        inspections.append((insp_id, a["asset_id"], when, int(grade), int(defects)))
spark.createDataFrame(
    inspections, "inspection_id long, asset_id long, inspection_date date, condition_grade int, defect_count int"
).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("dim_inspection"))
print(f"dim_inspection: {len(inspections)} inspections; generated at {local_now()}")
