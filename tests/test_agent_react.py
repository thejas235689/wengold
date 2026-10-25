"""ReAct, test-time search, and multi-agent orchestration.

Two of these carry an honest, measured result worth pinning: that structured search
(beam) beats a structural heuristic by a modest margin while brute-force sampling
does not, and that a reviewer catches plans a planner would happily execute.
"""
import random

import pytest

from wengold.agent.orchestra import Executor, Orchestra, Planner, Reviewer
from wengold.agent.perception import perceive
from wengold.agent.planning import plan as make_plan
from wengold.agent.react import react
from wengold.agent.search import (beam, best_of_k, sample_orders, score_order,
                                  single)
from wengold.graph.model import DesignGraph, Node, NodeKind
from wengold.kernel.validity import Result, Verdict


class Runner:
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.calls = []

    def __call__(self, rid, kind):
        self.calls.append(rid)
        ok = rid not in self.fail
        return {"result": rid, "tool": "simulated",
                "outcome": "pass" if ok else "fail",
                "rc": 0 if ok else 1, "kind": kind}


def _groups(trial=0, groups=3, per=3):
    """Groups of sims, each with a coverage result that needs ALL of its sims.

    This is the structure where ordering can matter: a partial group is worth
    nothing, so concentrating beats spreading.
    """
    rng = random.Random(trial)
    ids = [f"z{rng.randrange(10 ** 6):06d}" for _ in range(groups * per)]
    g = DesignGraph()
    for n in ids:
        g.add_node(Node(id=n, kind=NodeKind.RTL))
    g.rebuild_index()
    results = [Result(f"{n}_sim", "sim", depends_on={n}) for n in ids]
    for gi in range(groups):
        grp = [f"{ids[gi * per + k]}_sim" for k in range(per)]
        results.append(Result(f"cov{gi}", "coverage", depends_on={ids[gi * per]},
                              depends_on_results=set(grp)))
    return g, results, ids


# ---- ReAct -----------------------------------------------------------------
def test_react_interleaves_and_the_observation_drives_the_next_action():
    g, results, ids = _groups()
    ctx = perceive(g, results, set(ids))
    # fail every check, so whichever result ReAct picks first must fail
    run = react(ctx, Runner(set(ctx.todo)),
                diagnose=lambda o: "the check itself is suspect")
    actions = [s.action for s in run.steps]
    assert actions[0] == "run"
    assert "diagnose" in actions, "a failure must change the next action"
    assert run.steps[1].observation.startswith("the check itself is suspect")


def test_react_takes_what_a_pass_unblocked():
    g, results, ids = _groups()
    ctx = perceive(g, results, set(ids))
    run = react(ctx, Runner())
    assert run.checks >= 1
    assert len(run.settled) > run.checks, "a pass must settle what rested on it"


def test_react_stops_instead_of_inventing_a_move():
    g, results, ids = _groups()
    ctx = perceive(g, results, set(ids))
    run = react(ctx, Runner(set(ctx.todo)))
    assert run.steps[-1].action == "stop"


# ---- test-time scaling -----------------------------------------------------
def test_score_order_is_deterministic_for_a_seed():
    g, results, ids = _groups()
    ctx = perceive(g, results, set(ids))
    order = single(ctx)
    a = score_order(ctx, order, 0.2, 32, seed=5)
    b = score_order(ctx, order, 0.2, 32, seed=5)
    assert a == b


def test_a_certain_failure_settles_nothing_extra():
    g, results, ids = _groups()
    ctx = perceive(g, results, set(ids))
    order = single(ctx)
    # failure_p=1.0 means the very first check fails
    assert score_order(ctx, order, failure_p=1.0, trials=8) == len(ctx.by_verdict(Verdict.VALID))


def test_the_strategies_return_permutations_of_the_todo():
    g, results, ids = _groups()
    ctx = perceive(g, results, set(ids))
    for order in (single(ctx), best_of_k(ctx, 4), beam(ctx)):
        assert sorted(order) == sorted(ctx.todo)


def test_sampling_more_orders_gives_more_distinct_orders():
    g, results, ids = _groups()
    ctx = perceive(g, results, set(ids))
    assert len(sample_orders(ctx, 8, seed=1)) == 8


def test_beam_beats_greedy_on_all_or_nothing_groups():
    """The measured result, pinned on the structure where it holds.

    Coverage results that need *all* of their sims mean spreading across groups is
    worth nothing; concentrating is everything. Beam search finds that, and random
    best-of-K does not. Averaged over several namings so the result is not an
    artefact of alphabetical order.
    """
    gains = []
    for trial in range(6):
        g, results, ids = _groups(trial)
        ctx = perceive(g, results, set(ids))
        sc = lambda o: score_order(ctx, o[:6], 0.15, 100)  # noqa: E731
        greedy_score, beam_score = sc(single(ctx)), sc(beam(ctx, failure_p=0.15))
        gains.append(beam_score - greedy_score)
    assert sum(gains) / len(gains) > 0, f"beam no longer helps: {gains}"


# ---- multi-agent orchestration --------------------------------------------
def _ctx_with_tools(available=True):
    g, results, ids = _groups()
    ctx = perceive(g, results, set(ids))
    ctx.tools = {k: available for k in ctx.tools}
    return ctx


def test_the_reviewer_accepts_a_sound_plan():
    ctx = _ctx_with_tools(True)
    review = Reviewer().review(ctx, make_plan(ctx, "best_first"))
    assert review.accepted, review.problems


def test_the_reviewer_catches_a_missing_result():
    ctx = _ctx_with_tools(True)
    steps = make_plan(ctx, "best_first")[1:]
    review = Reviewer().review(ctx, steps)
    assert not review.accepted
    assert any("not in the plan" in p for p in review.problems)


def test_the_reviewer_catches_an_unavailable_tool():
    ctx = _ctx_with_tools(False)
    review = Reviewer().review(ctx, make_plan(ctx, "best_first"))
    assert not review.accepted
    assert any("not installed" in p for p in review.problems)


def test_the_reviewer_catches_a_dependency_out_of_order():
    ctx = _ctx_with_tools(True)
    steps = list(reversed(make_plan(ctx, "best_first")))
    for i, s in enumerate(steps, 1):
        s["step"] = i
    review = Reviewer().review(ctx, steps)
    assert not review.accepted
    assert any("depends on" in p for p in review.problems)


def test_the_orchestra_refuses_to_execute_a_rejected_plan():
    ctx = _ctx_with_tools(False)          # nothing installed: every plan is rejected
    result = Orchestra().run(ctx, Runner())
    assert result["executed"] is False
    assert result["outcomes"] == []
    assert any("refusing" in h.what for h in result["handoffs"])


def test_the_orchestra_executes_an_accepted_plan():
    ctx = _ctx_with_tools(True)
    runner = Runner()
    result = Orchestra().run(ctx, runner)
    assert result["executed"] is True
    assert result["outcomes"]
    assert any(h.frm == "reviewer" and h.to == "executor" for h in result["handoffs"])
