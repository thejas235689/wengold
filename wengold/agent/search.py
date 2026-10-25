"""Test-time scaling: spend more compute choosing an order, and measure what it buys.

The question this answers is narrow and honest. Last release showed that when every
check passes, **order does not matter** — the kernel's minimum evidence is already
minimal and one check at the base cascades. So there is nothing for a search to
find in that world.

There is something to find in this one: **checks can fail.** A failure stops the
run, so the order decides how much gets settled before the money runs out. That is
a real search problem, and it is the only one here.

Three allocations of compute:

* `single` — one ordering (greedy). The baseline.
* `sample` — draw K orderings at random, roll each out under a failure model, keep
  the best. Plain best-of-K, the simplest form of test-time scaling.
* `beam` — greedy beam search over partial orders, scored by rollout.

All three are compared **at equal compute** (the same number of rollouts), because
comparing a search against a single guess and calling the difference "scaling"
would be measuring the compute, not the search.

**The failure model is a model.** No simulator is installed, so "a check fails" is
drawn from a fixed probability. What is real is the dependency structure and the
rollout arithmetic on top of it. The result says something about *ordering under
failure*, not about any particular design.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from ..kernel.validity import Verdict
from .planning import _cost, greedy

__all__ = ["score_order", "sample_orders", "single", "best_of_k", "beam",
           "scaling_curve"]


def score_order(ctx, order, failure_p: float = 0.2, trials: int = 64,
                seed: int = 0) -> float:
    """Expected number of results settled before a failure stops the run.

    Rolled out `trials` times against the failure model; the mean is the score.
    """
    rng = random.Random(seed)
    valid = set(ctx.by_verdict(Verdict.VALID))
    total = 0.0
    for _ in range(trials):
        settled = set(valid)
        for rid in order:
            if rng.random() < failure_p:
                break
            settled.add(rid)
            changed = True
            while changed:
                changed = False
                for other in ctx.todo:
                    if other in settled:
                        continue
                    deps = set(getattr(ctx.results.get(other),
                                       "depends_on_results", set()) or set())
                    if deps and deps <= settled:
                        settled.add(other)
                        changed = True
        total += len(settled)
    return total / max(trials, 1)


def sample_orders(ctx, k: int, seed: int = 0) -> list[list[str]]:
    rng = random.Random(seed)
    base = list(ctx.todo)
    out = [list(base)]
    for _ in range(max(0, k - 1)):
        order = list(base)
        rng.shuffle(order)
        out.append(order)
    return out


def single(ctx, **kw) -> list[str]:
    return greedy(ctx, ctx.todo)


def best_of_k(ctx, k: int = 8, failure_p: float = 0.2, trials: int = 64,
              seed: int = 0) -> list[str]:
    """Best-of-K: the simplest test-time scaling there is."""
    scored = [(score_order(ctx, o, failure_p, trials, seed + i), o)
              for i, o in enumerate(sample_orders(ctx, k, seed))]
    return max(scored, key=lambda t: t[0])[1]


def beam(ctx, width: int = 4, failure_p: float = 0.2, trials: int = 32,
         seed: int = 0) -> list[str]:
    """Greedy beam over partial orders, scored by rollout on what is left."""
    remaining = list(ctx.todo)
    order: list[str] = []
    while remaining:
        scored = []
        for r in remaining:
            trial = order + [r]
            rest = [x for x in remaining if x != r]
            scored.append((score_order(ctx, trial + rest, failure_p, trials, seed),
                           -_cost(ctx, r), r))
        scored.sort(reverse=True)
        pick = scored[0][2]
        order.append(pick)
        remaining.remove(pick)
    return order


def scaling_curve(ctx, ks=(1, 2, 4, 8, 16, 32), failure_p: float = 0.2,
                  trials: int = 64, seed: int = 0) -> list[dict]:
    """Settled count as a function of compute — the point of test-time scaling."""
    rows = []
    for k in ks:
        order = single(ctx) if k == 1 else best_of_k(ctx, k, failure_p, trials, seed)
        rows.append({"k": k, "settled": score_order(ctx, order, failure_p, trials,
                                                    seed),
                     "order": order})
    return rows
