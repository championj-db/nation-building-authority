"""Outage propagation over a transport network graph (pure Python, no Spark).

Given the routing graph built by 01a_fetch_networks, answer "if this asset fails, what happens to
the network?" for a road or rail asset sitting on a node of a route:

1. Section - walk the asset's route from its node to the nearest junction (degree >= 3) or dead end
   in each direction. That stretch is what a closure takes out.
2. Detour  - shortest path between the section's two ends with the section removed (Dijkstra).
             Extra distance = detour length - section length.
3. Isolation - if there is no path round, the nodes no longer connected to the main network, and
             the localities that join the network there, are cut off.

Kept free of Spark so it can be unit-tested locally and imported by the gold step.
"""

from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Graph:
    adj: dict = field(default_factory=lambda: defaultdict(list))  # node -> [(other, edge_id)]
    edges: dict = field(default_factory=dict)                     # edge_id -> (a, b, segment_id, km)
    xy: dict = field(default_factory=dict)                         # node -> (lon, lat)

    @classmethod
    def build(cls, nodes, edges):
        g = cls()
        for node_id, lon, lat in nodes:
            g.xy[node_id] = (lon, lat)
        for edge_id, a, b, segment_id, km in edges:
            g.edges[edge_id] = (a, b, segment_id, float(km))
            g.adj[a].append((b, edge_id))
            g.adj[b].append((a, edge_id))
        return g

    def degree(self, node):
        return len(self.adj.get(node, ()))

    def main_component(self):
        """Nodes of the largest connected component (the 'national network')."""
        seen, best = set(), set()
        for start in self.adj:
            if start in seen:
                continue
            comp, stack = {start}, [start]
            while stack:
                n = stack.pop()
                for m, _e in self.adj[n]:
                    if m not in comp:
                        comp.add(m)
                        stack.append(m)
            seen |= comp
            if len(comp) > len(best):
                best = comp
        return best


@dataclass
class Impact:
    section_edges: list
    section_nodes: list              # ordered node path of the closed section, for drawing
    section_km: float
    end_a: str
    end_b: str
    detour_km: float | None          # total length of the way round; None when there is none
    extra_km: float | None           # detour minus the closed section
    detour_nodes: list               # node path of the detour, for drawing
    detour_segments: dict            # segment_id -> km travelled on it along the detour
    isolated_nodes: set              # nodes cut off from the main network (no alternative only)


def section(g: Graph, node: str, segment_id: str) -> tuple[list, str, str, list]:
    """Edges of `segment_id` from `node` out to the nearest junction or dead end on each side.

    Returns (edges, end_a, end_b, ordered node path from end_a through node to end_b).
    """
    own = [(m, e) for m, e in g.adj.get(node, ()) if g.edges[e][2] == segment_id]
    if not own:  # the node is a junction between other routes: take its shortest incident edges
        own = sorted(g.adj.get(node, ()), key=lambda me: g.edges[me[1]][3])[:2]
    ends, used, arms = [], set(), []
    for start, first_edge in own[:2]:
        arm = [start]
        cur, edge = start, first_edge
        used.add(edge)
        # follow the route while the node is a simple pass-through
        while g.degree(cur) == 2:
            nxt = [(m, e) for m, e in g.adj[cur] if e != edge]
            if not nxt or nxt[0][1] in used:
                break
            cur, edge = nxt[0]
            used.add(edge)
            arm.append(cur)
        ends.append(cur)
        arms.append(arm)
    if len(ends) == 1:  # the asset sits on a dead end
        ends.append(node)
        arms.append([])
    path = list(reversed(arms[0])) + [node] + arms[1]
    return sorted(used), ends[0], ends[1], path


def coords(g: Graph, nodes: list, max_points: int = 400) -> list:
    """[lon, lat] pairs for a node path, thinned to at most max_points for the map."""
    step = max(1, len(nodes) // max_points)
    picked = nodes[::step] + ([nodes[-1]] if nodes and (len(nodes) - 1) % step else [])
    return [[round(g.xy[n][0], 3), round(g.xy[n][1], 3)] for n in picked]


def shortest_path(g: Graph, a: str, b: str, blocked: set, limit_km: float = 2500.0):
    """Dijkstra from a to b avoiding `blocked` edges. Returns (km, node path, edge path) or None."""
    dist, prev = {a: 0.0}, {}
    heap = [(0.0, a)]
    while heap:
        d, n = heapq.heappop(heap)
        if n == b:
            nodes, edges, cur = [b], [], b
            while cur != a:
                p, e = prev[cur]
                nodes.append(p)
                edges.append(e)
                cur = p
            return d, nodes[::-1], edges[::-1]
        if d > dist.get(n, float("inf")) or d > limit_km:
            continue
        for m, e in g.adj[n]:
            if e in blocked:
                continue
            nd = d + g.edges[e][3]
            if nd < dist.get(m, float("inf")):
                dist[m] = nd
                prev[m] = (n, e)
                heapq.heappush(heap, (nd, m))
    return None


def reachable(g: Graph, start: str, blocked: set) -> set:
    seen, stack = {start}, [start]
    while stack:
        n = stack.pop()
        for m, e in g.adj[n]:
            if e not in blocked and m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def closure_impact(g: Graph, node: str, segment_id: str, main: set) -> Impact:
    """Close the route at `node` (the asset's location) and propagate.

    Only the route's edges at the failure point are blocked: on a spur, what lies beyond the break
    is cut off and what lies before it stays connected. Traffic still has to divert at the junctions
    either side, so the detour is measured junction to junction, around the whole section.
    """
    sec_edges, a, b, sec_path = section(g, node, segment_id)
    section_km = sum(g.edges[e][3] for e in sec_edges)
    blocked = {e for _m, e in g.adj.get(node, ()) if g.edges[e][2] == segment_id} or set(sec_edges[:1])
    path = shortest_path(g, a, b, set(sec_edges)) if a != b and a != node and b != node else None
    if path:
        km, nodes, path_edges = path
        segs = defaultdict(float)
        for e in path_edges:
            segs[g.edges[e][2]] += g.edges[e][3]
        return Impact(sec_edges, sec_path, section_km, a, b, km, max(0.0, km - section_km), nodes, dict(segs), set())
    # no way round: the break splits the network; everything except the side holding most of the
    # national network is cut off (including the failure point itself)
    sides = [reachable(g, m, blocked) for m, e in g.adj.get(node, ()) if e in blocked]
    sides = [sd for sd in sides if node not in sd] or sides
    if not sides:
        return Impact(sec_edges, sec_path, section_km, a, b, None, None, [], {}, {node} & main)
    keep = max(sides, key=lambda sd: len(sd & main))
    cut = (set().union(*sides) - keep) | {node}
    return Impact(sec_edges, sec_path, section_km, a, b, None, None, [], {}, {n for n in cut if n in main})
