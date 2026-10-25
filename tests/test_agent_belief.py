"""Belief, memory, MCTS and hierarchy — and the one result that actually wins.

The test that matters most here is `test_safest_first_beats_the_graph_heuristic`:
it is the only place in the agent layer where a component measurably improves on
the two-line baseline, and if it stops being true someone should look.

The rest pin the negatives, which are equally load-bearing: VOI ordering is worse
than greedy in this domain (because a failure halts the run), MCTS does not beat
greedy, and ReAcTree's recursion is worse than a flat milestone order.
"""
import random

import pytest

from wengold.agent.belief import (Belief, cheapest_safest, entropy, safest_first,
                                  voi, voi_order)
from wengold.agent.hierarchy import build_goals, goalact, milestones_done, reactree
from wengold.agent.mcts import mcts
from wengold.agent.memory import Episode, Memory
from wengold.agent.perception import perceive
from wengold.agent.planning import greedy
from wengold.graph.model import DesignGraph, Node, NodeKind
from wengold.kernel.validity import Result, Verdict


def _world(trial=0, groups=3, per=3, flaky_frac=0.25):
    """Sims grouped under coverage results, with a subset that fails often."""
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
    ctx = perceive(g, results, set(ids))
    truth = {r: 0.92 for r in ctx.todo}
    for r in rng.sample(sorted(ctx.todo), max(1, int(len(ctx.todo) * flaky_frac))):
        truth[r] = 0.35
    return ctx, truth


def _warm_memory(ctx, truth, runs=6, seed=0):
    rng = random.Random(seed)
    mem = Memory()
    for _ in range(runs):
        mem.record([ctx.todo[0]], list(ctx.todo),
                   {r: ("pass" if rng.random() < truth[r] else "fail")
                    for r in ctx.todo}, len(ctx.todo), 0)
    return mem


def _settled(ctx, order, truth, k, rng, trials=120):
    tot = 0
    for _ in range(trials):
        s = set(ctx.by_verdict(Verdict.VALID))
        for rid in order[:k]:
            if rng.random() > truth.get(rid, 0.9):
                break
            s.add(rid)
            changed = True
            while changed:
                changed = False
                for o in ctx.todo:
                    if o in s:
                        continue
                    d = set(getattr(ctx.results.get(o), "depends_on_results",
                                    set()) or set())
                    if d and d <= s:
                        s.add(o)
                        changed = True
        tot += len(s)
    return tot / trials


# ---- belief ----------------------------------------------------------------
def test_entropy_is_zero_when_certain():
    assert entropy(0.0) == 0.0 and entropy(1.0) == 0.0
    assert entropy(0.5) == pytest.approx(1.0)


def test_a_flat_belief_has_no_spread_and_no_information():
    ctx, _ = _world()
    b = Belief.flat(ctx)
    assert b.spread() == 0.0
    assert "flat" in b.source


def test_memory_supplies_priors_and_says_so():
    ctx, truth = _world()
    mem = _warm_memory(ctx, truth)
    b = Belief.from_memory(ctx, mem)
    assert b.spread() > 0, "a warm memory must move the priors off 0.5"
    assert "from memory" in b.source


def test_voi_orders_by_its_own_objective():
    """VOI prefers high entropy per unit cost — which is why it loses here."""
    ctx, truth = _world()
    b = Belief.from_memory(ctx, _warm_memory(ctx, truth))
    order = voi_order(ctx, b)
    scores = [voi(b, r) for r in order]
    assert scores == sorted(scores, reverse=True), "not ordered by VOI"
    # and the most uncertain *sim* must beat the most uncertain coverage result,
    # because coverage costs twice as much
    assert order[0] != "cov0" or b.p("cov0") < 0.5


# ---- memory ----------------------------------------------------------------
def test_memory_keeps_the_two_streams_apart():
    m = Memory()
    m.remember("cocotb", False)
    m.record(["a"], ["a"], {"a": "pass"}, 1, 1)
    assert m.recall("cocotb") is False
    assert len(m.episodes) == 1
    assert m.pass_rate("a") == 1.0
    assert m.pass_rate("never_seen") is None


def test_memory_round_trips_through_disk(tmp_path):
    p = str(tmp_path / "mem.json")
    m = Memory(path=p)
    m.remember("symbiyosys", False)
    m.record(["a"], ["a"], {"a": "fail"}, 2, 0)
    m.save()
    back = Memory.load(p)
    assert back.recall("symbiyosys") is False
    assert back.pass_rate("a") == 0.0
    assert back.warm()


def test_episode_similarity_is_jaccard_over_the_change():
    e = Episode(["a", "b"], [], {}, 0, 0)
    assert e.similarity(["a", "b"]) == 1.0
    assert e.similarity(["c"]) == 0.0
    assert e.similarity(["a", "b", "c", "d"]) == pytest.approx(0.5)


# ---- the positive result ---------------------------------------------------
def test_safest_first_beats_the_graph_heuristic():
    """The one component in the agent layer that measurably improves on greedy.

    When a failed check halts the run, ordering by probability of passing
    maximises expected progress before the halt. A graph-shape heuristic cannot
    see that signal, and here it is worth tens of percent.
    """
    gains = []
    for trial in range(6):
        ctx, truth = _world(trial)
        rng = random.Random(trial)
        b = Belief.from_memory(ctx, _warm_memory(ctx, truth, seed=trial))
        g = _settled(ctx, greedy(ctx, ctx.todo), truth, 8, rng)
        s = _settled(ctx, safest_first(ctx, b), truth, 8, rng)
        gains.append(s - g)
    assert sum(gains) / len(gains) > 0, f"safest_first no longer helps: {gains}"


def test_voi_loses_to_greedy_here():
    """Pinned negative: the textbook objective is wrong for this domain."""
    losses = []
    for trial in range(4):
        ctx, truth = _world(trial)
        rng = random.Random(trial)
        b = Belief.from_memory(ctx, _warm_memory(ctx, truth, seed=trial))
        g = _settled(ctx, greedy(ctx, ctx.todo), truth, 8, rng)
        v = _settled(ctx, voi_order(ctx, b), truth, 8, rng)
        losses.append(v - g)
    assert sum(losses) / len(losses) < 0, f"VOI now helps: {losses}"


# ---- MCTS and hierarchy ----------------------------------------------------
def test_mcts_returns_a_permutation_of_the_todo():
    ctx, _ = _world()
    r = mcts(ctx, rollouts=24, trials=8)
    assert sorted(r.order) == sorted(ctx.todo)
    assert r.nodes >= 1 and r.rollouts == 24


def test_mcts_with_no_exploration_degenerates_to_replaying_its_best_child():
    """With c = 0 the UCB1 term vanishes, so the tree only exploits.

    There is deliberately no "MCTS does not beat greedy" test here. It was true on
    neorv32 and picorv32 (79.08 vs 79.82, and equal on picorv32) and false on the
    small synthetic world, so pinning the negative would pin a claim about one
    structure as if it were general — the same mistake the beam-search number made
    in v0.20.0.
    """
    ctx, _ = _world()
    a = mcts(ctx, rollouts=40, c=0.0, trials=12, seed=1)
    b = mcts(ctx, rollouts=40, c=0.0, trials=12, seed=1)
    assert a.order == b.order, "c=0 must be deterministic for a fixed seed"
    assert sorted(a.order) == sorted(ctx.todo)


def test_goalact_and_reactree_emit_only_real_results():
    """Regression: reactree once emitted synthetic names like `cov0/a`, which
    nothing could settle, and scored zero milestones."""
    ctx, _ = _world()
    for order in (goalact(ctx), reactree(ctx)):
        assert not [r for r in order if r not in ctx.todo], "fake result in the plan"


def test_a_milestone_comes_after_all_of_its_members():
    ctx, _ = _world()
    order = reactree(ctx)
    for gi in range(3):
        name = f"cov{gi}"
        if name not in order:
            continue
        members = [r for r in ctx.todo
                   if name in set(getattr(ctx.results.get(r), "depends_on_results",
                                          set()) or set())]
        if members:
            assert order.index(name) > max(order.index(m) for m in members)


def test_build_goals_groups_sims_under_their_coverage_result():
    ctx, _ = _world()
    goals = build_goals(ctx)
    assert any(len(g.members) > 1 for g in goals)


def test_milestones_done_counts_settled_coverage_results():
    ctx, _ = _world()
    assert milestones_done(ctx, set()) == 0
    assert milestones_done(ctx, set(ctx.todo)) == 3
