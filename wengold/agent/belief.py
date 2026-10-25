"""The agent's belief about what is actually broken, and what a check is worth.

A POMDP framing is only useful if the belief state carries information the agent
would otherwise ignore. Here it does: **not every open result is equally likely to
be broken.** A block that has failed the last three runs is a better use of a
check than one that has passed every time, and the flat heuristics in `planning.py`
cannot see that because they rank on graph shape alone.

Two things live here:

* **`Belief`** — a probability per open result that its check passes, plus the
  entropy of that belief.
* **value of information** — for a perfect binary observation the expected entropy
  reduction is simply `H(p)`, so ranking by `H(p) / cost` is the principled order.
  That is a *different* signal from "how much does this unblock", and it is the one
  that breaks the symmetry which made every ordering tie in the last two releases.

Priors come from `memory.py` when there is history and default to a flat 0.5 when
there is not — and the code says which it used, because a VOI ordering built on
invented priors is worse than a plain greedy one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..kernel.validity import Verdict
from .planning import _cost

__all__ = ["Belief", "entropy", "voi", "voi_order", "safest_first",
           "cheapest_safest"]


def entropy(p: float) -> float:
    """Binary entropy in bits."""
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


@dataclass
class Belief:
    """P(result passes | everything known so far), per open result."""

    priors: dict[str, float] = field(default_factory=dict)
    source: str = "flat 0.5 (no history)"

    @classmethod
    def flat(cls, ctx, p: float = 0.5) -> "Belief":
        return cls({rid: p for rid in ctx.todo}, "flat 0.5 (no history)")

    @classmethod
    def from_memory(cls, ctx, memory) -> "Belief":
        """Use recorded pass rates where there is history, flat elsewhere."""
        priors, known = {}, 0
        for rid in ctx.todo:
            p = memory.pass_rate(rid)
            if p is None:
                priors[rid] = 0.5
            else:
                priors[rid] = p
                known += 1
        src = (f"{known}/{len(ctx.todo)} from memory, rest flat 0.5"
               if known else "flat 0.5 (no history)")
        return cls(priors, src)

    def p(self, rid: str) -> float:
        return self.priors.get(rid, 0.5)

    def entropy(self) -> float:
        """Total uncertainty over the open set, in bits."""
        return sum(entropy(self.p(rid)) for rid in self.priors)

    def spread(self) -> float:
        """How far the priors are from flat — 0 means the belief adds nothing."""
        if not self.priors:
            return 0.0
        return sum(abs(self.p(r) - 0.5) for r in self.priors) / len(self.priors)

    def update(self, rid: str, passed: bool) -> None:
        """A perfect observation: the result is now known."""
        self.priors[rid] = 1.0 if passed else 0.0


def voi(belief: Belief, rid: str, cost: float = 1.0) -> float:
    """Expected entropy reduction per unit cost from running this check.

    For a perfect binary observation the posterior is certain either way, so the
    expected reduction is exactly `H(p)` — divided by what the check costs.
    """
    return entropy(belief.p(rid)) / max(cost, 1e-9)


def voi_order(ctx, belief: Belief, todo=None) -> list[str]:
    """Order the open results by value of information, highest first.

    **This is the wrong objective for this domain, and it is kept as the
    counterexample.** VOI assumes a negative observation is information you can
    act on and keep going. Here a failed check *halts the run*, so a high-entropy
    (flaky) result first is the worst possible order: it spends the budget on
    discovering the thing most likely to stop you. Measured: VOI ordering lost to
    plain greedy by 4% on neorv32 and 8% on picorv32, while `safest_first` — the
    same belief, inverted — beat greedy by up to 36%.
    """
    items = list(todo if todo is not None else ctx.todo)
    return sorted(items, key=lambda r: (-voi(belief, r, _cost(ctx, r)), r))


def safest_first(ctx, belief: Belief, todo=None) -> list[str]:
    """Order by probability of passing, highest first.

    The right objective when a failure stops the run: maximise expected progress
    before the halt. A graph-shape heuristic cannot see this — two results with
    identical dependency structure can differ tenfold in how likely they are to
    pass, and only history knows which.
    """
    items = list(todo if todo is not None else ctx.todo)
    return sorted(items, key=lambda r: (-belief.p(r), _cost(ctx, r), r))


def cheapest_safest(ctx, belief: Belief, todo=None) -> list[str]:
    """Probability per unit cost — the same idea with the cost term made explicit."""
    items = list(todo if todo is not None else ctx.todo)
    return sorted(items, key=lambda r: (-belief.p(r) / max(_cost(ctx, r), 1e-9), r))
