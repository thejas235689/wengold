"""Self-verification: the invariants, the fuzz, and the reference cross-check."""
from wengold.graph.model import DesignGraph, EdgeKind, Node, NodeKind
from wengold.kernel import invariants, reference
from wengold.kernel.gengraph import (clone_graph, random_changed, random_graph,
                                     random_results)
from wengold.kernel.validity import Result, classify


# ---- the invariants hold on generated graphs ---------------------------
def test_fuzz_finds_no_violations():
    violations = invariants.fuzz(range(120), n_nodes=9, n_edges=16)
    assert violations == [], "\n".join(str(v) for v in violations)


def test_kernel_matches_reference_on_generated_graphs():
    for seed in range(80):
        g = random_graph(seed)
        rs = random_results(g, seed)
        ch = random_changed(g, seed)
        assert reference.cross_check(g, rs, ch) == []


# ---- each invariant, with a hand-built case ----------------------------
def _dep_graph():
    g = DesignGraph()
    for n in ("a", "b", "c"):
        g.add_node(Node(n, NodeKind.RTL))
    g.add_edge("a", "b", EdgeKind.INSTANTIATES)     # a is upstream of b
    return g


def test_inv1_adding_uncertainty_never_upgrades():
    g = _dep_graph()
    r = Result("t", "sim", depends_on={"b"})
    assert classify(g, r, {"other"}).verdict.value == "valid"
    g2 = clone_graph(g)
    g2.add_edge("other", "b", EdgeKind.UNKNOWN)
    assert classify(g2, r, {"other"}).verdict.value == "unknown"
    assert invariants.check_adding_uncertainty(g, [r], {"other"}) == []


def test_inv2_known_change_invalidates_consumers():
    g = _dep_graph()
    r = Result("t", "sim", depends_on={"b"})
    assert invariants.check_known_change_invalidates(g, [r]) == []
    # a result that consumed "a" is invalidated when "a" changes
    r2 = Result("u", "sim", depends_on={"a"})
    assert classify(g, r2, {"a"}).verdict.value == "invalidated"


def test_inv3_removing_information_never_increases_confidence():
    g = _dep_graph()
    r = Result("t", "sim", depends_on={"b"})
    assert invariants.check_removing_information(g, [r], {"other"}) == []
    # and the missing-dependency case is caught
    g2 = clone_graph(g)
    g2.nodes.pop("b")
    assert classify(g2, r, {"other"}).verdict.value == "unknown"


def test_inv4_deterministic():
    g = random_graph(7)
    rs = random_results(g, 7)
    assert invariants.check_deterministic(g, rs, random_changed(g, 7)) == []


def test_inv5_withdrawal_propagates():
    g = _dep_graph()
    a = Result("a_res", "sim", depends_on={"a"})
    b = Result("b_res", "coverage", depends_on={"b"}, depends_on_results={"a_res"})
    assert invariants.check_withdrawal_propagates(g, [a, b], {"other"}) == []


# ---- the edge-removal hazard is detectable -----------------------------
def test_edge_removal_hazard_is_flagged():
    g = _dep_graph()
    r = Result("t", "sim", depends_on={"b"})
    # changing "a" invalidates r only because of the a->b edge
    assert classify(g, r, {"a"}).verdict.value == "invalidated"
    hazards = invariants.edge_removal_hazard(g, [r], {"a"})
    assert hazards, "removing the dependency edge should be flagged as a hazard"
    assert hazards[0].invariant == "edge_removal_must_be_flagged"
