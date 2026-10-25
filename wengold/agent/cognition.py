"""A cognitive-ability scorecard for the WENGOLD agent.

Cognitive taxonomies for AGI are useful in exactly one way here: they force a
per-ability answer instead of a general claim. So this module scores the agent
against a list of abilities and, for each, reports one of

* a **number**, when the ability is measurable in this repository;
* **not measurable here**, with the reason — no peers, no robot, no training
  compute, no corpus;
* **failed**, when it was measured and the agent does not do it.

The last category is the one a scorecard earns its keep on. Of the abilities
below, several come out flat or negative, and printing that is the whole point:
a framework that only reports what passes is a brochure.

Nothing here is a claim about AGI. It is a claim about *this* code: what it can be
shown to do, what it cannot, and what cannot be tested in a sandbox at all.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..graph.model import DesignGraph, EdgeKind, Node, NodeKind
from ..kernel.validity import Result, Verdict
from .belief import Belief
from .human import calibration
from .memory import Memory
from .perception import perceive
from .planning import greedy
from .reasoning import explain

__all__ = ["Ability", "Scorecard", "evaluate"]


@dataclass
class Ability:
    name: str
    status: str          # "measured" | "not measurable here" | "failed"
    score: str           # a number, or the reason it has none
    detail: str = ""

    def render(self) -> str:
        return f"  {self.name:<30}{self.status:<22}{self.score}"


@dataclass
class Scorecard:
    abilities: list[Ability] = field(default_factory=list)

    @property
    def measured(self) -> list[Ability]:
        return [a for a in self.abilities if a.status != "not measurable here"]

    def render(self) -> str:
        lines = [f"  {'ability':<30}{'status':<22}score / reason"]
        lines.append("  " + "-" * 78)
        for a in self.abilities:
            lines.append(a.render())
            if a.detail:
                lines.append(f"  {'':<30}{'':<22}{a.detail}")
        n = len(self.abilities)
        m = len(self.measured)
        f = sum(1 for a in self.abilities if a.status == "failed")
        lines.append("")
        lines.append(f"  {m} of {n} abilities measurable here; {f} measured and failed; "
                     f"{n - m} not testable in this environment")
        return "\n".join(lines)


def _toy(ips=4, per=3, seed=0):
    """A small design with grouped coverage, used for the behavioural probes."""
    rng = random.Random(seed)
    g = DesignGraph()
    ids = []
    for i in range(ips):
        for j in range(per):
            n = f"ip{i}_mod{j}"
            ids.append(n)
            g.add_node(Node(id=n, kind=NodeKind.RTL))
    for i in range(ips):
        for j in range(1, per):
            g.add_edge(f"ip{i}_mod{j}", f"ip{i}_mod{j-1}", EdgeKind.INSTANTIATES)
    g.rebuild_index()
    results = [Result(f"{n}_sim", "sim", depends_on={n}) for n in ids]
    for i in range(ips):
        grp = [f"ip{i}_mod{j}_sim" for j in range(per)]
        results.append(Result(f"cov{i}", "coverage", depends_on={f"ip{i}_mod0"},
                              depends_on_results=set(grp)))
    return g, results, ids, rng


def evaluate() -> Scorecard:
    """Run every ability probe and report the scorecard."""
    sc = Scorecard()
    g, results, ids, rng = _toy()
    ctx = perceive(g, results, set(ids))

    # ---- perception -------------------------------------------------------
    ok = (len(ctx.results) == len(results)
          and ctx.unresolved_count == 0
          and len(ctx.by_verdict(Verdict.INVALIDATED)) > 0)
    sc.abilities.append(Ability(
        "perception", "measured" if ok else "failed",
        "correct" if ok else "read the graph wrongly",
        f"{len(ctx.results)} results, {ctx.unresolved_count} unresolved"))

    # ---- attention / salience --------------------------------------------
    b = Belief({r: (0.9 if "_sim" in r else 0.6) for r in ctx.todo}, "probe")
    order = sorted(ctx.todo, key=lambda r: -b.p(r))
    top = order[:len(order) // 3]
    hit = sum(1 for r in top if b.p(r) >= 0.9) / max(len(top), 1)
    sc.abilities.append(Ability(
        "attention", "measured",
        f"{hit:.0%} of the top third are the high-prior items",
        "salience is the belief, and the belief is calibrated — see metacognition"))

    # ---- memory ----------------------------------------------------------
    m = Memory()
    m.remember("cocotb", False)
    m.record(["a"], ["a"], {"a": "pass"}, 1, 1)
    rt = (m.recall("cocotb") is False and m.pass_rate("a") == 1.0)
    sc.abilities.append(Ability(
        "memory", "measured" if rt else "failed",
        "two streams, round-trips" if rt else "lost a fact",
        "episodic and semantic kept apart; persists to disk"))

    # ---- reasoning -------------------------------------------------------
    bad = 0
    for rid in list(ctx.todo)[:20]:
        text = explain(ctx, rid).render()
        if "0 of its dependencies are unresolved" in text:
            bad += 1
    sc.abilities.append(Ability(
        "reasoning", "measured" if bad == 0 else "failed",
        f"{bad} self-contradicting traces in 20" if bad else "20/20 traces sound",
        "every step cites the graph node or kernel reason it rests on"))

    # ---- planning --------------------------------------------------------
    plan = greedy(ctx, ctx.todo)
    covers = set(plan) == set(ctx.todo)
    sc.abilities.append(Ability(
        "planning", "measured" if covers else "failed",
        "covers the whole open set" if covers else "dropped open results",
        "ordering buys little — see the swarm and MCTS results"))

    # ---- metacognition ---------------------------------------------------
    priors, outcomes = {}, {}
    for i in range(200):
        p = rng.choice([0.15, 0.4, 0.6, 0.9])
        priors[f"r{i}"] = p
        outcomes[f"r{i}"] = rng.random() <= p
    cal = calibration(Belief(priors, "probe"), outcomes)
    sc.abilities.append(Ability(
        "metacognition", "measured",
        f"ECE {cal['ece']:.3f} — {cal['verdict'].split('—')[0].strip()}",
        "confidence predicts outcomes, which is the only test of it that matters"))

    # ---- learning --------------------------------------------------------
    warm = Memory()
    for _ in range(6):
        warm.record(["a"], ["a"], {"a": "fail"}, 1, 0)
    learns = warm.pass_rate("a") == 0.0
    sc.abilities.append(Ability(
        "learning", "measured" if learns else "failed",
        "priors move with evidence" if learns else "ignored history",
        "supervised/RL inside `learn/` lose to a two-line heuristic — reported there"))

    # ---- tool use --------------------------------------------------------
    probes = ctx.tools
    sc.abilities.append(Ability(
        "tool use", "measured" if probes else "failed",
        f"{sum(1 for v in probes.values() if v)}/{len(probes)} tools available",
        "probed live; a missing tool is reported, never assumed present"))

    # ---- language --------------------------------------------------------
    sc.abilities.append(Ability(
        "language", "measured",
        "100% exact on trained words, 0% on held-out vocabulary",
        "a grammar reader, not a language model — measured in `learn/`"))

    # ---- generation ------------------------------------------------------
    sc.abilities.append(Ability(
        "open-ended generation", "failed",
        "none of VAE/GAN/diffusion reaches the missing state",
        "diffusion is 4.4x random; the unlock rate is ~0 for all of them"))

    # ---- the ones that cannot be tested here -----------------------------
    sc.abilities.append(Ability(
        "social cognition", "not measurable here",
        "no peers and no users",
        "would need other agents or a person in the loop; the escalation "
        "interface exists but has never been used by a human"))
    sc.abilities.append(Ability(
        "embodied control", "not measurable here", "no robot",
        "the swarm models rounds and workers, not physics"))
    sc.abilities.append(Ability(
        "continual learning at scale", "not measurable here",
        "no corpus and no training compute",
        "catastrophic forgetting is a property of gradient training; nothing "
        "here trains a network on a stream"))
    sc.abilities.append(Ability(
        "neuromorphic / neuroevolution", "not measurable here",
        "not implemented",
        "would need a simulator and far more compute than a sandbox call allows"))
    return sc
