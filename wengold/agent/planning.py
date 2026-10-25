"""Planning: what to re-establish, and in what order.

The kernel already tells the agent *which* results need new evidence
(`minimum_new_evidence`). What it does not say is the order, and the order is the
whole cost: a result that ten others rest on unblocks them all when it settles,
while running it last means paying for the queue behind it either way.

Three strategies, and they are compared rather than assumed:

* `cheapest` — the smallest check first. Good when a cheap check settles things.
* `greedy` — sort once by "how much does this unblock, per unit cost". The strong
  baseline, and the one the earlier RL work failed to beat.
* `best_first` — re-score after **every** pick against the results still blocked.
  That is the difference from `greedy`: the ranking is recomputed as the frontier
  shrinks, so a result that only becomes valuable once its blocker is gone is
  picked at the point it becomes valuable, not at the start.

Cost is a model, not a measurement: `COST` prices a formal run above a simulation
because it is, and the planner says so rather than pretending the number is real.
"""
from __future__ import annotations

import heapq

__all__ = ["COST", "cheapest", "greedy", "best_first", "plan", "STRATEGIES"]

COST = {"sim": 1.0, "coverage": 2.0, "lint": 1.0, "cdc": 2.0,
        "formal": 4.0, "synth": 3.0}


def _cost(ctx, rid: str) -> float:
    kind = getattr(ctx.results.get(rid), "kind", None) or "sim"
    return COST.get(kind, 1.0)


def _blocked(ctx, rid: str, remaining: set[str]) -> int:
    """How many still-unsettled results rest on this one."""
    return len(ctx.dependents.get(rid, set()) & remaining)


def cheapest(ctx, todo) -> list[str]:
    return sorted(todo, key=lambda r: (_cost(ctx, r), r))


def greedy(ctx, todo) -> list[str]:
    """One static sort by value per unit cost."""
    remaining = set(todo)
    return sorted(todo, key=lambda r: (-_blocked(ctx, r, remaining) / _cost(ctx, r), r))


def best_first(ctx, todo) -> list[str]:
    """Re-score after every pick against what is still blocked.

    A max-heap keyed on value/cost, rebuilt as the frontier shrinks.
    """
    remaining = set(todo)
    order: list[str] = []
    while remaining:
        heap = [(-(_blocked(ctx, r, remaining) / _cost(ctx, r)), _cost(ctx, r), r)
                for r in remaining]
        heapq.heapify(heap)
        _neg, _c, pick = heapq.heappop(heap)
        order.append(pick)
        remaining.discard(pick)
    return order


STRATEGIES = {"cheapest": cheapest, "greedy": greedy, "best_first": best_first}


def plan(ctx, strategy: str = "best_first") -> list[dict]:
    """An ordered plan: each step names the result, the action and the tool."""
    fn = STRATEGIES.get(strategy, best_first)
    order = fn(ctx, ctx.todo)
    steps = []
    for i, rid in enumerate(order, 1):
        kind = getattr(ctx.results.get(rid), "kind", None) or "sim"
        tool = {"sim": "cocotb", "coverage": "verilator", "formal": "symbiyosys",
                "cdc": "verilator", "lint": "verilator", "synth": "yosys"}.get(kind)
        available = ctx.tools.get(tool, True) if tool else True
        steps.append({"step": i, "result": rid, "action": "run", "kind": kind,
                      "tool": tool, "cost": _cost(ctx, rid),
                      "available": available,
                      "blocked_by_it": _blocked(ctx, rid, set(ctx.todo))})
    return steps
