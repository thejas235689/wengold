"""Singular configurations of a dependency graph.

The load-bearing test is `test_the_direction_is_instantiators_not_instantiated`:
the first version walked the wrong way and named the top-level testbench as the
singular node — the opposite of the truth, and a plausible-looking answer, which is
the worst kind.
"""
import pytest

from wengold.graph.model import DesignGraph, EdgeKind, Node, NodeKind
from wengold.graph.singularity import (blast_radius, conditioning, damping,
                                       singular_nodes)


def _tree(breadth=4, depth=3):
    """A shallow hierarchy: one top, each level instantiating `breadth` below."""
    g = DesignGraph()
    names = []
    for d in range(depth):
        level = [f"L{d}_{i}" for i in range(breadth ** d)]
        names.append(level)
        for n in level:
            g.add_node(Node(id=n, kind=NodeKind.RTL))
    # child -> parent, matching the builder's convention
    for d in range(1, depth):
        for i, parent in enumerate(names[d]):
            for c in range(breadth):
                child = names[d - 1][(i * breadth + c) % len(names[d - 1])]
                g.add_edge(child, parent, EdgeKind.INSTANTIATES)
    g.rebuild_index()
    return g, names


def test_the_direction_is_instantiators_not_instantiated():
    """A change at a leaf must reach upward, not downward.

    The first version used `ancestors()`, which in this edge convention walks *into*
    the block. It reported the top-level testbench as singular on neorv32, because
    the testbench instantiates 76 blocks — exactly backwards. What matters for
    evidence is what instantiates *you*.
    """
    g, names = _tree()
    leaf = names[0][0]
    top = names[-1][0]
    assert blast_radius(g, leaf) > blast_radius(g, top), (
        "a leaf must reach more of the design than the top does")
    assert blast_radius(g, top) == 0, "nothing instantiates the top"


def test_blast_radius_counts_only_rtl_blocks():
    g, names = _tree()
    g.add_node(Node(id="some_pkg", kind=NodeKind.PACKAGE))
    assert blast_radius(g, names[0][0]) <= len(names[0]) + len(names[1]) + len(names[2])


def test_a_missing_node_has_no_blast_radius():
    g, _ = _tree()
    assert blast_radius(g, "does_not_exist") == 0


def test_conditioning_is_well_conditioned_on_a_balanced_tree():
    g, _ = _tree()
    c = conditioning(g)
    assert c["blocks"] == sum(4 ** d for d in range(3))
    assert c["condition_number"] >= 1.0
    assert c["worst"] is not None


def test_conditioning_on_an_empty_graph_does_not_divide_by_zero():
    c = conditioning(DesignGraph())
    assert c["blocks"] == 0 and c["verdict"] == "empty graph"


def test_singular_nodes_respects_the_threshold():
    g, names = _tree()
    loose = singular_nodes(g, threshold=0.0)
    tight = singular_nodes(g, threshold=0.9)
    assert len(loose) >= len(tight)
    assert all(0.0 <= s.fraction <= 1.0 for s in loose)


def test_singular_nodes_are_sorted_worst_first():
    g, _ = _tree()
    radii = [s.blast_radius for s in singular_nodes(g, threshold=0.0)]
    assert radii == sorted(radii, reverse=True)


def test_damping_reports_a_cost_as_well_as_a_saving():
    """Isolating a block must never be presented as free."""
    g, names = _tree()
    d = damping(g, names[0][0])
    assert "before" in d and "after" in d
    assert "no longer verified" in d["cost"]
    assert d["after"] < d["before"], "stubbing must reduce the blast radius"
