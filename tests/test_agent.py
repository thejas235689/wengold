"""The agent layer: six stages, and the honest limits of each.

The tests that matter here are the ones that pin *negative* results, because those
are the easy things to quietly lose: that planning order changes nothing on this
structure, that reflection stops instead of looping, and that the bandit reports a
tie rather than inventing a preference.
"""
import pytest

from wengold.agent import Agent, Bandit
from wengold.agent.loop import SimulatedRunner
from wengold.agent.perception import perceive
from wengold.agent.planning import best_first, cheapest, greedy, plan
from wengold.agent.reasoning import explain
from wengold.graph.model import DesignGraph, EdgeKind, Node, NodeKind
from wengold.kernel.validity import Result, Verdict


def _layered(layers=4, per=3):
    """A layered design plus results whose coverage summarises the layer below."""
    g = DesignGraph()
    names = [[f"L{l}_{i}" for i in range(per)] for l in range(layers)]
    for l in range(layers):
        for n in names[l]:
            g.add_node(Node(id=n, kind=NodeKind.RTL))
    for l in range(1, layers):
        for i, n in enumerate(names[l]):
            for j in (i, (i + 1) % per):
                g.add_edge(n, names[l - 1][j], EdgeKind.INSTANTIATES)
    g.rebuild_index()
    results = [Result(f"{n}_sim", "sim", depends_on={n}) for n in names[0]]
    prev = {f"{n}_sim" for n in names[0]}
    for l in range(1, layers):
        cur = set()
        for i, n in enumerate(names[l]):
            results.append(Result(f"{n}_sim", "sim", depends_on={n}))
            cov = Result(f"{n}_cov", "coverage", depends_on={n},
                         depends_on_results={f"{n}_sim"} | prev)
            results.append(cov)
            cur.add(cov.id)
        prev = cur
    return g, results, names


class Failing(SimulatedRunner):
    def __init__(self, fail):
        self.fail = set(fail)
        super().__init__()

    def __call__(self, rid, kind):
        self.calls.append(rid)
        ok = rid not in self.fail
        return {"result": rid, "tool": "simulated",
                "outcome": "pass" if ok else "fail",
                "rc": 0 if ok else 1, "kind": kind}


# ---- perception ------------------------------------------------------------
def test_perception_reads_the_graph_and_the_tools():
    g, results, names = _layered()
    ctx = perceive(g, results, {names[0][0]})
    assert ctx.complete and ctx.unresolved_count == 0
    assert ctx.todo, "a change must put something in doubt"
    assert set(ctx.tools) == {"cocotb", "symbiyosys"}
    # the tool probe must answer, not assume
    assert all(isinstance(v, bool) for v in ctx.tools.values())


def test_perception_separates_unknown_from_invalidated():
    """A result with no recorded dependencies is UNKNOWN, not invalidated."""
    g, results, _names = _layered()
    results.append(Result("no_deps", "sim", depends_on=set()))
    ctx = perceive(g, results, {"L0_0"})
    assert ctx.verdicts["no_deps"] is Verdict.UNKNOWN
    assert "no dependencies were recorded" in explain(ctx, "no_deps").render()


# ---- reasoning -------------------------------------------------------------
def test_the_trace_cites_the_nodes_it_rests_on():
    g, results, names = _layered()
    changed = {names[0][0]}
    ctx = perceive(g, results, changed)
    trace = explain(ctx, f"{names[0][0]}_sim")
    assert trace.verdict == "invalidated"
    text = trace.render()
    assert names[0][0] in text, "the changed node must be named"
    assert any(t.because for t in trace.thoughts), "steps must carry evidence"


def test_the_trace_is_a_prompt_an_llm_could_use():
    g, results, names = _layered()
    ctx = perceive(g, results, {names[0][0]})
    prompt = explain(ctx, f"{names[0][0]}_sim").as_prompt()
    assert "evidence:" in prompt and "\n" in prompt


# ---- planning --------------------------------------------------------------
def test_every_strategy_returns_the_same_set():
    g, results, names = _layered()
    ctx = perceive(g, results, {names[0][0]})
    orders = [set(cheapest(ctx, ctx.todo)), set(greedy(ctx, ctx.todo)),
              set(best_first(ctx, ctx.todo))]
    assert orders[0] == orders[1] == orders[2] == set(ctx.todo)


def test_the_plan_names_a_tool_and_its_availability():
    g, results, names = _layered()
    ctx = perceive(g, results, {names[0][0]})
    steps = plan(ctx, "best_first")
    assert steps and all(s["tool"] for s in steps)
    assert all("available" in s for s in steps)


# ---- the loop, and its honest limits ---------------------------------------
def test_one_check_at_the_base_settles_the_cascade():
    g, results, names = _layered()
    run = Agent(g, results, bandit=Bandit(seed=0)).run(
        {names[0][0]}, SimulatedRunner(), strategy="best_first", adaptive=False)
    assert run.runs == 1
    assert run.settled > 1, "settling the base must settle what rests on it"


def test_ordering_does_not_change_how_much_is_settled():
    """The finding, pinned: the kernel's minimum evidence is already minimal, so
    the order of the plan buys nothing here. If that ever stops being true, this
    test should fail and someone should look."""
    g, results, names = _layered()
    settled = []
    for name in ("cheapest", "greedy", "best_first"):
        run = Agent(g, results, bandit=Bandit(seed=0)).run(
            {names[0][0]}, SimulatedRunner(), strategy=name, adaptive=False)
        settled.append((run.runs, run.settled))
    assert len(set(settled)) == 1, f"strategies now differ: {settled}"


def test_reflection_stops_when_a_check_fails_instead_of_looping():
    g, results, names = _layered()
    run = Agent(g, results, bandit=Bandit(seed=0)).run(
        {names[0][0]}, Failing({f"{names[0][0]}_sim"}),
        strategy="best_first", adaptive=False)
    assert run.iterations == 1, "it must not retry a plan that changed nothing"
    assert any("stopping rather than retrying" in r for r in run.reflections)


def test_the_budget_caps_the_checks():
    g, results, names = _layered()
    run = Agent(g, results, bandit=Bandit(seed=0)).run(
        {names[0][0], names[0][1]}, SimulatedRunner(), strategy="best_first",
        adaptive=False, budget=1)
    assert run.runs <= 1


# ---- adaptation ------------------------------------------------------------
def test_the_bandit_reports_a_tie_rather_than_inventing_a_preference():
    """All three strategies reward identically here, so the honest output is a
    tie. A bandit that reported a confident winner on identical rewards would be
    lying about what it knows."""
    g, results, names = _layered()
    b = Bandit(seed=0)
    a = Agent(g, results, bandit=b, seed=0)
    for _ in range(12):
        a.run({names[0][0]}, SimulatedRunner(), adaptive=True)
    means = {arm.name: round(arm.mean, 6) for arm in b.arms.values()}
    assert len(set(means.values())) == 1, f"rewards differ: {means}"
    assert b.total == 12


def test_the_bandit_explores_every_arm():
    b = Bandit(seed=0, epsilon=0.2)
    for _ in range(30):
        b.update(b.choose(), settled=3, checks=2)
    assert all(a.pulls > 0 for a in b.arms.values())
