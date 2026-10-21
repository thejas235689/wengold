"""Typed dependencies and composition contracts."""
from wengold.graph.model import DesignGraph, EdgeKind, Node, NodeKind
from wengold.kernel.composition import (BlockContract, check_pair, check_subsystem,
                                        contracts_from_graph)
from wengold.kernel.contract import Contract, Scope
from wengold.kernel.dependencies import (DependencyType, change_impact,
                                         config_scope_affected, dep_type,
                                         reassessment_rule, typed_ancestors)
from wengold.kernel.validity import Result


def test_dependency_types_are_distinguished():
    g = DesignGraph()
    g.add_edge("a", "b", EdgeKind.INCLUDES)
    g.add_edge("a", "b", EdgeKind.INSTANTIATES)
    g.add_edge("a", "b", EdgeKind.PARAMETERIZES)
    g.add_edge("a", "b", EdgeKind.TRACES_TO)
    g.add_edge("a", "b", EdgeKind.ASSUMES)
    kinds = {dep_type(e) for e in g.edges}
    assert kinds == {DependencyType.COMPILATION, DependencyType.BEHAVIORAL,
                     DependencyType.CONFIGURATION, DependencyType.REQUIREMENT,
                     DependencyType.ASSUMPTION}


def test_each_type_has_a_reassessment_rule():
    for t in DependencyType:
        assert reassessment_rule(t)


def test_typed_ancestors_filters_by_type():
    g = DesignGraph()
    g.add_edge("file", "mod", EdgeKind.DEFINED_IN)      # compilation
    g.add_edge("pkg", "mod", EdgeKind.IMPORTS)          # elaboration
    g.add_edge("leaf", "mod", EdgeKind.INSTANTIATES)    # behavioral
    assert typed_ancestors(g, {"mod"}, {DependencyType.COMPILATION}) == {"file"}
    assert typed_ancestors(g, {"mod"}, {DependencyType.ELABORATION}) == {"pkg"}


def test_config_scope_affected():
    r = Result("t", "sim", contract=Contract(claim="x",
               scope=Scope.make(config={"DEPTH": 16})))
    assert config_scope_affected(r, {"DEPTH"}) is True
    assert config_scope_affected(r, {"WIDTH"}) is False
    # no recorded scope -> assumed affected (conservative)
    assert config_scope_affected(Result("u", "sim"), {"ANY"}) is True


def test_change_impact_reports_rules():
    g = DesignGraph()
    g.add_edge("a", "b", EdgeKind.PARAMETERIZES)
    impact = change_impact(g, {"a"}, changed_config_keys={"DEPTH"})
    assert "configuration" in impact
    assert impact["configuration"]["rule"]


# ---- composition --------------------------------------------------------
def test_composition_reports_unmet_assumptions():
    parent = BlockContract("soc", assumes=("axi_handshake", "clk_stable"),
                           guarantees=())
    child = BlockContract("dma", assumes=(), guarantees=("axi_handshake",))
    issues = check_pair(parent, child)
    assert len(issues) == 1 and "clk_stable" in issues[0]


def test_subsystem_check_from_graph():
    g = DesignGraph()
    g.add_node(Node("soc", NodeKind.RTL))
    g.add_node(Node("dma", NodeKind.RTL))
    g.add_edge("dma", "soc", EdgeKind.INSTANTIATES)     # soc instantiates dma
    g.add_edge("axi_handshake", "soc", EdgeKind.ASSUMES)
    g.add_edge("clk_stable", "soc", EdgeKind.ASSUMES)
    g.add_edge("axi_handshake", "dma", EdgeKind.GUARANTEES)

    contracts = contracts_from_graph(g)
    assert contracts["soc"].assumes == ("axi_handshake", "clk_stable")
    assert contracts["dma"].guarantees == ("axi_handshake",)

    report = check_subsystem(g)
    assert report.ok is False
    assert report.issues[0]["unmet"] == ["clk_stable"]


def test_subsystem_ok_when_covered():
    g = DesignGraph()
    g.add_node(Node("soc", NodeKind.RTL))
    g.add_node(Node("dma", NodeKind.RTL))
    g.add_edge("dma", "soc", EdgeKind.INSTANTIATES)
    g.add_edge("axi_handshake", "soc", EdgeKind.ASSUMES)
    g.add_edge("axi_handshake", "dma", EdgeKind.GUARANTEES)
    assert check_subsystem(g).ok is True
