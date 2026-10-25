"""The swarm: decentralised, local, and survivable.

Two of these tests pin things I got wrong first, because both mistakes were
instructive:

* The swarm looked much better than the central planner until I ran the control —
  a central planner that simply does not halt on the first failure matches it. The
  gain was the failure policy, not decentralisation.
* Killing workers changed nothing until I measured in *rounds*. Under a check
  budget one survivor spends the whole budget itself, so fault tolerance is
  invisible. A swarm's resilience is a statement about time, not about work.
"""
import random

import pytest

from wengold.agent.belief import Belief
from wengold.agent.memory import Memory
from wengold.agent.perception import perceive
from wengold.agent.swarm import Swarm, partition, potential
from wengold.graph.model import DesignGraph, Node, NodeKind
from wengold.kernel.validity import Result, Verdict


class Runner:
    def __init__(self, truth=None, seed=0):
        self.truth = truth or {}
        self.rng = random.Random(seed)
        self.calls = []

    def __call__(self, rid, kind):
        self.calls.append(rid)
        ok = self.rng.random() <= self.truth.get(rid, 0.9)
        return {"result": rid, "tool": "simulated",
                "outcome": "pass" if ok else "fail", "rc": 0 if ok else 1,
                "kind": kind}


def _design(ips=4, per=3, seed=0):
    """Several IPs, each with its own modules — the natural neighbourhood."""
    g = DesignGraph()
    ids = []
    for i in range(ips):
        for j in range(per):
            n = f"ip{i}_mod{j}"
            ids.append(n)
            g.add_node(Node(id=n, kind=NodeKind.RTL))
    g.rebuild_index()
    results = [Result(f"{n}_sim", "sim", depends_on={n}) for n in ids]
    for i in range(ips):
        grp = [f"ip{i}_mod{j}_sim" for j in range(per)]
        results.append(Result(f"cov{i}", "coverage", depends_on={f"ip{i}_mod0"},
                              depends_on_results=set(grp)))
    # change EVERY module, so the whole design is in doubt and the swarm has
    # real work to partition. Changing one block opened 2 results and the
    # partition collapsed to a single slice.
    return perceive(g, results, set(ids))


def _belief(ctx, seed=0):
    rng = random.Random(seed)
    mem = Memory()
    truth = {r: 0.92 for r in ctx.todo}
    for r in rng.sample(sorted(ctx.todo), max(1, len(ctx.todo) // 4)):
        truth[r] = 0.35
    for _ in range(6):
        mem.record([ctx.todo[0]], list(ctx.todo),
                   {r: ("pass" if rng.random() < truth[r] else "fail")
                    for r in ctx.todo}, 0, 0)
    return Belief.from_memory(ctx, mem), truth


# ---- the three properties --------------------------------------------------
def test_partition_gives_each_worker_its_own_slice():
    ctx = _design()
    slices = partition(ctx, 4)
    assert slices, "the open set must be partitioned"
    owned = [r for s in slices.values() for r in s]
    assert len(owned) == len(set(owned)), "a result may not belong to two workers"
    assert set(owned) <= set(ctx.todo)


def test_a_worker_only_acts_on_its_own_slice():
    ctx = _design()
    sw = Swarm(ctx, 2)
    for w in sw.workers:
        assert w.owns <= set(ctx.todo)


def test_the_swarm_needs_no_central_scheduler():
    """Killing a worker must not stop the others — the defining claim."""
    ctx = _design(ips=5, per=4)
    sw = Swarm(ctx, 4)
    sw.kill("w0")
    run = sw.run(Runner(), max_checks=20, max_rounds=6)
    assert run.per_worker.get("w0", 0) == 0, "a dead worker must do nothing"
    assert sum(v for k, v in run.per_worker.items() if k != "w0") > 0, (
        "the survivors must keep working")


# ---- fault tolerance, measured in rounds -----------------------------------
def test_fault_tolerance_is_a_statement_about_time_not_work():
    """The mistake, pinned.

    Under a *check* budget, killing workers changes nothing: one survivor spends
    the whole budget. Under a *round* budget the loss is visible. If this ever
    stops being true, the round accounting in `Swarm.run` has broken.
    """
    ctx = _design(ips=8, per=6)
    b, truth = _belief(ctx)
    full = Swarm(ctx, 4, b).run(Runner(truth, 1), max_checks=80, max_rounds=12)
    killed = Swarm(ctx, 4, b).run(Runner(truth, 1), max_checks=80, max_rounds=12,
                                  kill_after=2, kill=("w0", "w1", "w2"))
    assert len(full.settled) > len(killed.settled), (
        "with one worker left the swarm must settle less in the same number of rounds")


def test_the_swarm_degrades_rather_than_collapsing():
    """Losing half the workers must not cost half the output."""
    ctx = _design(ips=8, per=6)
    b, truth = _belief(ctx)
    full = Swarm(ctx, 4, b).run(Runner(truth, 2), max_checks=120, max_rounds=20)
    half = Swarm(ctx, 4, b).run(Runner(truth, 2), max_checks=120, max_rounds=20,
                                kill_after=10, kill=("w0", "w1"))
    assert len(half.settled) > 0, "the survivors must keep working"
    assert len(half.settled) >= 0.5 * len(full.settled), (
        f"degradation worse than proportional: {len(half.settled)} vs {len(full.settled)}")


# ---- the potential-field rule ---------------------------------------------
def test_potential_is_attracted_by_dependents_and_repelled_by_risk():
    ctx = _design()
    b, _ = _belief(ctx)
    sim = next(r for r in ctx.todo if "_sim" in r)
    certain = Belief({r: 1.0 for r in ctx.todo})
    risky = Belief({r: 0.1 for r in ctx.todo})
    assert potential(ctx, sim, certain) > potential(ctx, sim, risky), (
        "a check likely to fail must be repelled")
    assert potential(ctx, sim, None) != 0
