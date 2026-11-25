"""Unit tests for src/network.py on small graphs with known answers.

Run: python3 -m pytest tests/  (or: python3 tests/test_network.py)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from network import Graph, closure_impact, section  # noqa: E402


def graph(edges):
    """edges: (a, b, segment, km). Node coordinates are irrelevant to the topology tests."""
    nodes = sorted({n for a, b, *_ in edges for n in (a, b)})
    return Graph.build([(n, 0.0, 0.0) for n in nodes], [(f"e{i}", a, b, s, km) for i, (a, b, s, km) in enumerate(edges)])


def test_ring_gives_detour_around_the_closed_section():
    # J1 -a- X -a- J2 is route "A" (10 km); the way round J1 -b- J2 is route "B" (25 km)
    g = graph([("J1", "X", "A", 4), ("X", "J2", "A", 6), ("J1", "J2", "B", 25), ("J1", "Z", "C", 1), ("J2", "Y", "C", 1)])
    imp = closure_impact(g, "X", "A", g.main_component())
    assert {imp.end_a, imp.end_b} == {"J1", "J2"}
    assert imp.section_km == 10
    assert imp.detour_km == 25 and imp.extra_km == 15
    assert imp.detour_segments == {"B": 25}
    assert not imp.isolated_nodes


def test_spur_cuts_off_only_what_lies_beyond_the_break():
    # hub H on a ring, spur H - P1 - P2 - END on route "S"; failure at P1
    g = graph([("H", "R1", "R", 5), ("R1", "R2", "R", 5), ("R2", "H", "R", 5),
               ("H", "P1", "S", 10), ("P1", "P2", "S", 10), ("P2", "END", "S", 10)])
    imp = closure_impact(g, "P1", "S", g.main_component())
    assert imp.extra_km is None                      # no way round on a spur
    assert imp.isolated_nodes == {"P1", "P2", "END"}  # beyond the break, plus the failure point
    assert "H" not in imp.isolated_nodes and "R1" not in imp.isolated_nodes


def test_bridge_between_two_halves_isolates_the_smaller_half():
    # big half (4 nodes) - bridge B (route "BR") - small half (2 nodes)
    g = graph([("A1", "A2", "A", 1), ("A2", "A3", "A", 1), ("A3", "A4", "A", 1), ("A4", "A1", "A", 1),
               ("A1", "B", "BR", 5), ("B", "C1", "BR", 5), ("C1", "C2", "C", 1)])
    imp = closure_impact(g, "B", "BR", g.main_component())
    assert imp.extra_km is None
    assert imp.isolated_nodes == {"B", "C1", "C2"}


def test_section_returns_ordered_path_between_junctions():
    g = graph([("J1", "a", "A", 1), ("a", "b", "A", 1), ("b", "J2", "A", 1), ("J1", "x", "X", 1), ("J1", "y", "Y", 1),
               ("J2", "p", "P", 1), ("J2", "q", "Q", 1)])
    edges, end_a, end_b, path = section(g, "a", "A")
    assert {end_a, end_b} == {"J1", "J2"} and len(edges) == 3
    assert path[0] in ("J1", "J2") and path[-1] in ("J1", "J2") and "a" in path and "b" in path


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
