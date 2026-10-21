"""Minimum new evidence must propagate downstream through the result graph."""
from wengold.graph.model import DesignGraph
from wengold.kernel.minimize import minimum_new_evidence, propagate_results
from wengold.kernel.validity import Result, classify_all

GRAPH = DesignGraph()


def _results():
    return [
        Result("sim_a", "sim", depends_on={"x"}),
        Result("cov_b", "coverage", depends_on={"y"}, depends_on_results={"sim_a"}),
        Result("sim_c", "sim", depends_on={"y"}),
    ]


def test_downstream_result_is_rerun_too():
    results = _results()
    classes = classify_all(GRAPH, results, {"x"})
    verdicts = {c.result.id: c.verdict.value for c in classes}
    assert verdicts["sim_a"] == "invalidated"
    assert verdicts["cov_b"] == "valid"          # its own deps are untouched
    # ... but it derives from sim_a, so it must be re-established anyway
    assert minimum_new_evidence(GRAPH, classes) == ["cov_b", "sim_a"]
    assert "sim_c" not in minimum_new_evidence(GRAPH, classes)


def test_explicit_result_dependency_map():
    results = _results()
    classes = classify_all(GRAPH, results, {"x"})
    todo = minimum_new_evidence(GRAPH, classes, {"cov_b": {"sim_a"}})
    assert todo == ["cov_b", "sim_a"]


def test_propagate_results_transitive():
    results = [
        Result("a", "sim", depends_on={"x"}),
        Result("b", "coverage", depends_on={"x"}, depends_on_results={"a"}),
        Result("c", "coverage", depends_on={"x"}, depends_on_results={"b"}),
    ]
    assert propagate_results(results, {"a"}) == {"a", "b", "c"}


def test_no_propagation_when_nothing_changed():
    results = _results()
    classes = classify_all(GRAPH, results, {"unrelated"})
    assert minimum_new_evidence(GRAPH, classes) == []
