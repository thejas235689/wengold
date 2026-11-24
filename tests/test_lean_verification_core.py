"""Tests for Lean Verification core composition with the existing kernel."""
import pytest

from wengold.graph.model import DesignGraph, EdgeKind, Node, NodeKind
from wengold.kernel.validity import Result, Verdict
from wengold.verification.models import RunManifest
from wengold.verification.planner import LeanPlanner, PlanAction


def _graph():
    graph = DesignGraph()
    for name, kind in (
        ("rtl_a", NodeKind.RTL), ("rtl_b", NodeKind.RTL),
        ("test_a", NodeKind.TEST), ("coverage_a", NodeKind.COVERAGE),
    ):
        graph.add_node(Node(name, kind))
    graph.add_edge("rtl_a", "test_a", EdgeKind.VERIFIES)
    graph.add_edge("test_a", "coverage_a", EdgeKind.COVERS)
    return graph


def test_lean_planner_invalidates_impacted_result_and_keeps_unrelated():
    graph = _graph()
    results = [
        Result("sim_a", "sim", depends_on={"test_a"}),
        Result("sim_b", "sim", depends_on={"rtl_b"}),
    ]
    plan = LeanPlanner().plan(graph, results, {"rtl_a"})
    assert plan.reestablish == ["sim_a"]
    assert plan.retained_current == ["sim_b"]
    assert plan.as_dict()["claim"] == "planning_only_not_execution_or_signoff"


def test_lean_planner_propagates_rerun_to_dependent_results():
    graph = _graph()
    results = [
        Result("sim_a", "sim", depends_on={"test_a"}),
        Result("coverage_a", "coverage", depends_on={"coverage_a"},
               depends_on_results={"sim_a"}),
    ]
    plan = LeanPlanner().plan(graph, results, {"rtl_a"})
    assert plan.reestablish == ["coverage_a", "sim_a"]


def test_lean_planner_reestablishes_unknown_empty_dependency():
    graph = _graph()
    results = [Result("unmapped", "sim")]
    plan = LeanPlanner().plan(graph, results, set())
    assert plan.reestablish == ["unmapped"]
    assert plan.items[0].verdict is Verdict.UNKNOWN


def test_lean_planner_rejects_duplicate_result_ids():
    with pytest.raises(ValueError, match="unique"):
        LeanPlanner().plan(_graph(), [
            Result("same", "sim", depends_on={"rtl_a"}),
            Result("same", "formal", depends_on={"rtl_b"}),
        ], set())


def test_run_manifest_digest_is_order_independent_and_content_sensitive():
    a = RunManifest(
        tool="verilator", argv=("--lint-only", "top.sv"),
        source_digests=(("b.sv", "sha256:b"), ("a.sv", "sha256:a")),
        tool_version="5.044", seed=17,
    )
    b = RunManifest(
        tool="verilator", argv=("--lint-only", "top.sv"),
        source_digests=(("a.sv", "sha256:a"), ("b.sv", "sha256:b")),
        tool_version="5.044", seed=17,
    )
    c = RunManifest(
        tool="verilator", argv=("--lint-only", "top.sv"),
        source_digests=(("a.sv", "sha256:changed"), ("b.sv", "sha256:b")),
        tool_version="5.044", seed=17,
    )
    assert a.digest == b.digest
    assert a.digest != c.digest


def test_run_manifest_rejects_invalid_timeout_and_duplicate_input():
    with pytest.raises(ValueError, match="positive"):
        RunManifest(tool="yosys", argv=(), timeout_seconds=0)
    with pytest.raises(ValueError, match="duplicate"):
        RunManifest(tool="yosys", argv=(),
                    source_digests=(("top.sv", "a"), ("top.sv", "b")))
