# Databricks notebook source
# Step 1a of the critical infrastructure monitoring pipeline: real transport network geometry.
#
# Fetches public line data at run time (never committed to the repository) and builds a routable
# graph, so an asset failure can be propagated along the network as a detour or as localities cut
# off:
#   road, rail  National Key Freight Routes, Department of Infrastructure (CC BY 4.0)
#   rivers      Natural Earth rivers, Australia supplement (public domain) - map context only
#
# Writes ref_network_source (provenance), ref_network_segment (named routes with display
# geometry), ref_network_node / ref_network_edge (the routing graph), ref_locality_node (where each
# locality joins each network) and ref_river.
#
# If a source is unreachable the step falls back to the last good copy in the landing volume, so a
# demo never depends on a third-party service being up; with no copy at all it fails loudly.

# COMMAND ----------

import datetime as dt
import json
import math
import os
import sys
import urllib.parse
import urllib.request

dbutils.widgets.text("src_dir", "")
_src = dbutils.widgets.get("src_dir")
_candidates = [_src, os.path.dirname(_src) if _src.endswith(".py") else None, "src", "."]
_src_dir = next((c for c in _candidates if c and os.path.isfile(os.path.join(c, "common.py"))), None)
if _src_dir is None:
    raise FileNotFoundError("common.py not found - pass src_dir pointing at the use case's src folder")
sys.path.insert(0, _src_dir)

from common import (
    DISPLAY_TOLERANCE_DEG, LOCALITIES, LOCALITY_SNAP_MAX_KM, NETWORK_GENERALISE_DEG,
    NETWORK_SOURCES, NODE_SNAP_KM, get_params, haversine_km, local_now, volume_dir,
)

params = get_params({"catalog": "", "schema": "", "volume": "landing"}, dbutils)
if not params["catalog"] or not params["schema"]:
    raise ValueError("catalog and schema parameters are required")
CATALOG, SCHEMA, VOLUME = params["catalog"], params["schema"], params["volume"]
CACHE_DIR = volume_dir(CATALOG, SCHEMA, VOLUME, "reference", "networks")
os.makedirs(CACHE_DIR, exist_ok=True)


def table(name: str) -> str:
    return f"{CATALOG}.{SCHEMA}.{name}"


# COMMAND ----------

# MAGIC %md
# MAGIC ## Fetch, with a last-good-copy fallback

# COMMAND ----------

def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "nba-critical-infrastructure-monitoring/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def fetch_arcgis(url: str) -> dict:
    """Page through an ArcGIS MapServer query as GeoJSON in WGS84, generalised server-side."""
    features, offset = [], 0
    while True:
        query = urllib.parse.urlencode({
            "where": "1=1", "outFields": "*", "returnGeometry": "true", "outSR": "4326",
            "maxAllowableOffset": NETWORK_GENERALISE_DEG, "geometryPrecision": 5,
            "resultOffset": offset, "resultRecordCount": 2000, "f": "geojson",
        })
        page = http_json(f"{url}?{query}")
        batch = page.get("features", [])
        features += batch
        if not page.get("exceededTransferLimit") and not (page.get("properties") or {}).get("exceededTransferLimit"):
            break
        offset += len(batch)
        if not batch:
            break
    return {"type": "FeatureCollection", "features": features}


provenance, collections = [], {}
for mode, source in NETWORK_SOURCES.items():
    cache = os.path.join(CACHE_DIR, f"{mode}.geojson")
    from_cache = False
    try:
        data = fetch_arcgis(source["url"]) if "MapServer" in source["url"] else http_json(source["url"])
        if not data.get("features"):
            raise ValueError("source returned no features")
        with open(cache, "w") as fh:
            json.dump(data, fh)
    except Exception as exc:  # network, HTTP or payload problem
        if not os.path.exists(cache):
            raise RuntimeError(f"Could not fetch {mode} network from {source['url']} and no cached copy exists: {exc}")
        print(f"WARNING: {mode} fetch failed ({exc}); using the last good copy in {cache}")
        with open(cache) as fh:
            data = json.load(fh)
        from_cache = True
    collections[mode] = data
    provenance.append((mode, source["url"], source["attribution"], source["licence"], len(data["features"]), from_cache))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Segments and display geometry

# COMMAND ----------

def parts(geom):
    if not geom:
        return []
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return geom["coordinates"]
    return []


def simplify(points, tol):
    """Douglas-Peucker in degrees (display only - the routing graph keeps the fetched vertices)."""
    if len(points) < 3:
        return points
    (x1, y1), (x2, y2) = points[0][:2], points[-1][:2]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1e-12
    idx, dmax = 0, 0.0
    for i in range(1, len(points) - 1):
        x0, y0 = points[i][:2]
        d = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / norm
        if d > dmax:
            idx, dmax = i, d
    if dmax <= tol:
        return [points[0], points[-1]]
    return simplify(points[: idx + 1], tol)[:-1] + simplify(points[idx:], tol)


def line_km(line):
    return sum(haversine_km(a[1], a[0], b[1], b[0]) for a, b in zip(line, line[1:]))


segments = []   # (segment_id, mode, name, route_no, manager, state, length_km, display_coords)
lines_by_mode = {"road": [], "rail": []}
for mode in ("road", "rail"):
    for i, f in enumerate(collections[mode]["features"]):
        props = f.get("properties") or {}
        ls = [l for l in parts(f.get("geometry")) if len(l) > 1]
        if not ls:
            continue
        seg_id = f"{mode[:2].upper()}{i:04d}"
        name = (props.get("name") or "").strip() or None
        state = (props.get("state") or "").strip().upper() or None
        display = [[[round(x, 3), round(y, 3)] for x, y, *_ in simplify(l, DISPLAY_TOLERANCE_DEG)] for l in ls]
        segments.append((seg_id, mode, name, (props.get("RouteNumbe") or "").strip() or None,
                         (props.get("Manager") or "").strip() or None, state,
                         round(sum(line_km(l) for l in ls), 2), json.dumps(display, separators=(",", ":"))))
        for l in ls:
            lines_by_mode[mode].append((seg_id, name, l))

spark.createDataFrame(
    segments, "segment_id string, mode string, name string, route_no string, manager string, state string, "
              "length_km double, display_coords string",
).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("ref_network_segment"))

rivers = []
for i, f in enumerate(collections["river"]["features"]):
    props = f.get("properties") or {}
    # the Australia supplement ranks 10-13: keep every perennial river, and only the more prominent
    # intermittent ones so inland channels do not clutter the map
    cla, rank = props.get("featurecla"), props.get("scalerank") or 99
    if not (cla == "River" or (cla == "River (Intermittent)" and rank <= 11)):
        continue
    ls = [l for l in parts(f.get("geometry")) if len(l) > 1]
    display = [[[round(x, 3), round(y, 3)] for x, y, *_ in simplify(l, DISPLAY_TOLERANCE_DEG * 2)] for l in ls]
    if display:
        rivers.append((f"RV{i:04d}", props.get("name") or None, props.get("featurecla") == "River (Intermittent)",
                       json.dumps(display, separators=(",", ":"))))
spark.createDataFrame(rivers, "river_id string, name string, intermittent boolean, display_coords string") \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("ref_river"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Routing graph
# MAGIC Vertices within NODE_SNAP_KM merge into one node (grid + neighbour-cell union-find), so
# MAGIC routes that meet or cross become connected. Consecutive vertices along a route become edges
# MAGIC carrying that route's identity, which lets a closure be described by route name.

# COMMAND ----------

cell = NODE_SNAP_KM / 111.32
nodes_out, edges_out = [], []
for mode, lines in lines_by_mode.items():
    verts = [(x, y) for _seg, _name, l in lines for x, y, *_ in l]
    parent = list(range(len(verts)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    grid = {}
    for idx, (x, y) in enumerate(verts):
        grid.setdefault((int(x // cell), int(y // cell)), []).append(idx)
    for (gx, gy), members in grid.items():
        for nx in (gx - 1, gx, gx + 1):
            for ny in (gy - 1, gy, gy + 1):
                for j in grid.get((nx, ny), []):
                    for i in members:
                        if i < j and haversine_km(verts[i][1], verts[i][0], verts[j][1], verts[j][0]) <= NODE_SNAP_KM:
                            ra, rb = find(i), find(j)
                            if ra != rb:
                                parent[ra] = rb
    roots, node_xy = {}, {}
    for idx, (x, y) in enumerate(verts):
        r = find(idx)
        nid = roots.setdefault(r, f"{mode[:2].upper()}N{len(roots):05d}")
        sx, sy, n = node_xy.get(nid, (0.0, 0.0, 0))
        node_xy[nid] = (sx + x, sy + y, n + 1)

    best = {}
    k = 0
    for seg, name, l in lines:
        prev = None
        for x, y, *_ in l:
            nid = roots[find(k)]
            k += 1
            if prev and prev[0] != nid:
                key = tuple(sorted((prev[0], nid))) + (seg,)
                length = haversine_km(prev[2], prev[1], y, x)
                if key not in best or length < best[key]:
                    best[key] = length
            prev = (nid, x, y)
    degree = {}
    for (a, b, seg), length in best.items():
        edges_out.append((f"{mode[:2].upper()}E{len(edges_out):06d}", mode, a, b, seg, round(length, 3)))
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    for nid, (sx, sy, n) in node_xy.items():
        if nid in degree:
            nodes_out.append((nid, mode, round(sx / n, 5), round(sy / n, 5), degree[nid]))

spark.createDataFrame(nodes_out, "node_id string, mode string, longitude double, latitude double, degree int") \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("ref_network_node"))
spark.createDataFrame(edges_out, "edge_id string, mode string, from_node string, to_node string, segment_id string, length_km double") \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("ref_network_edge"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Where each locality joins each network

# COMMAND ----------

loc_rows = []
for mode in ("road", "rail"):
    mode_nodes = [n for n in nodes_out if n[1] == mode]
    for name, state, lat, lon, _w in LOCALITIES:
        nearest = min(mode_nodes, key=lambda n: haversine_km(lat, lon, n[3], n[2]))
        km = haversine_km(lat, lon, nearest[3], nearest[2])
        if km <= LOCALITY_SNAP_MAX_KM:
            loc_rows.append((name, state, mode, nearest[0], round(km, 2)))
spark.createDataFrame(loc_rows, "locality string, state string, mode string, node_id string, snap_km double") \
    .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("ref_locality_node"))

fetched = local_now()
spark.createDataFrame(
    [(m, u, a, l, n, c, fetched.strftime("%Y-%m-%d %H:%M:%S")) for m, u, a, l, n, c in provenance],
    "mode string, source_url string, attribution string, licence string, features long, from_cache boolean, fetched_at string",
).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table("ref_network_source"))

for mode in ("road", "rail"):
    n_nodes = sum(1 for n in nodes_out if n[1] == mode)
    n_edges = sum(1 for e in edges_out if e[1] == mode)
    km = sum(s[6] for s in segments if s[1] == mode)
    print(f"{mode}: {sum(1 for s in segments if s[1] == mode)} segments, {km:,.0f} km, {n_nodes} nodes, {n_edges} edges, "
          f"{sum(1 for r in loc_rows if r[2] == mode)} localities joined")
print(f"rivers: {len(rivers)}; sources: {[(p[0], 'cache' if p[5] else 'live') for p in provenance]}")
