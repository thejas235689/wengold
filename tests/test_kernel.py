"""The validity kernel: valid / invalidated / unknown, and minimisation."""
from wengold.demo import build_graph
from wengold.kernel.validity import Result, Verdict, classify_all
from wengold.kernel.minimize import minimum_new_evidence


def _run(changed):
    graph = build_graph()
    prior = [
        Result("soc_smoke", "sim", depends_on={"soc_top"}),
        Result("sec_acl_test", "sim", depends_on={"sec_firewall"}),
        Result("dma_key_test", "sim", depends_on={"dma", "sec_firewall"}),
        Result("npu_conv_test", "sim", depends_on={"npu"}),
    ]
    return graph, classify_all(graph, prior, changed)


def test_change_invalidates_only_what_it_touches():
    _, classes = _run({"sec_firewall"})
    got = {c.result.id: c.verdict for c in classes}
    assert got["sec_acl_test"] is Verdict.INVALIDATED       # verifies sec_firewall
    assert got["dma_key_test"] is Verdict.INVALIDATED       # depends on sec_firewall
    assert got["soc_smoke"] is Verdict.INVALIDATED          # sec_firewall is a child of soc_top
    assert got["npu_conv_test"] is Verdict.VALID            # npu is untouched


def test_min_new_evidence_is_the_invalidated_set():
    graph, classes = _run({"sec_firewall"})
    assert minimum_new_evidence(graph, classes) == ["dma_key_test", "sec_acl_test", "soc_smoke"]


def test_uncertain_dependency_returns_unknown():
    graph = build_graph()
    graph.add_edge("mystery_ip", "sec_firewall", __import__("wengold.graph.model",
                   fromlist=["EdgeKind"]).EdgeKind.UNKNOWN)
    prior = [Result("sec_acl_test", "sim", depends_on={"sec_firewall"})]
    classes = classify_all(graph, prior, {"mystery_ip"})
    assert classes[0].verdict is Verdict.UNKNOWN
