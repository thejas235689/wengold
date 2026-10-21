"""The kernel must never return VALID when the evidence is insufficient."""
from wengold.graph.model import DesignGraph, EdgeKind, Node, NodeKind
from wengold.kernel.validity import Result, Verdict, classify, completeness_report


def _graph_with_dep():
    g = DesignGraph()
    g.add_node(Node("a", NodeKind.RTL))
    g.add_node(Node("b", NodeKind.RTL))
    g.add_edge("a", "b", EdgeKind.VERIFIES)      # a is upstream of b
    return g


def test_empty_dependencies_is_unknown():
    g = _graph_with_dep()
    r = Result("t", "sim", depends_on=set())
    c = classify(g, r, {"a"})
    assert c.verdict is Verdict.UNKNOWN
    assert "no recorded dependencies" in c.reason


def test_unresolved_dependency_is_unknown():
    g = _graph_with_dep()
    g.mark_unresolved("a", "module a never parsed")
    r = Result("t", "sim", depends_on={"b"})
    c = classify(g, r, {"unrelated"})
    assert c.verdict is Verdict.UNKNOWN
    assert "unresolved" in c.reason


def test_approximate_graph_cannot_be_valid():
    g = _graph_with_dep()
    g.approximate = True
    r = Result("t", "sim", depends_on={"b"})
    c = classify(g, r, {"unrelated"})
    assert c.verdict is Verdict.UNKNOWN
    assert "approximate" in c.reason


def test_valid_when_clean_and_unrelated():
    g = _graph_with_dep()
    r = Result("t", "sim", depends_on={"b"})
    c = classify(g, r, {"unrelated"})
    assert c.verdict is Verdict.VALID


def test_direct_change_still_invalidates_even_if_unresolved():
    g = _graph_with_dep()
    g.mark_unresolved("b", "partial")
    r = Result("t", "sim", depends_on={"b"})
    c = classify(g, r, {"b"})
    assert c.verdict is Verdict.INVALIDATED


def test_completeness_report_shape():
    g = _graph_with_dep()
    g.mark_unresolved("a", "why")
    rep = completeness_report(g)
    assert rep["complete"] is False
    assert "a" in rep["unresolved"]
