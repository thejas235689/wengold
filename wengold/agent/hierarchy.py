"""Hierarchical decomposition: goals, milestones, local executors.

The flat planner in `planning.py` orders every open result at once. That is the
wrong shape for a real design, where the open results cluster: eleven simulations
feed three coverage results, and finishing *one* coverage result is a milestone a
person can act on, while advancing eleven simulations by a tenth is not.

So: build a goal tree from the result graph — each coverage result is a milestone,
and the simulations it summarises are its sub-goals — order the milestones, and run
each one's sub-goals as a local executor. The difference from a flat plan is what
you get to report when the budget runs out: complete milestones, not scattered
progress.

Two shapes from the literature, both implemented because they differ in what they
optimise:

* **GoalAct** — a global milestone order, local execution inside each. Finishes
  one subsystem before touching the next.
* **ReAcTree** — recurses: a milestone that cannot be settled is itself decomposed
  again, so a stuck group is broken into smaller pieces rather than abandoned.

Measured on *milestones completed* under a budget, because that is the thing the
hierarchy is supposed to improve and raw "results settled" is not.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .planning import _cost, greedy

__all__ = ["Goal", "build_goals", "goalact", "reactree", "milestones_done"]


@dataclass
class Goal:
    name: str
    members: list[str] = field(default_factory=list)     # sub-goals to run
    children: list["Goal"] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return float(len(self.members))


def build_goals(ctx) -> list[Goal]:
    """One goal per coverage-style result, holding the sims it summarises."""
    goals: dict[str, Goal] = {}
    claimed: set[str] = set()
    for rid in ctx.todo:
        deps = set(getattr(ctx.results.get(rid), "depends_on_results", set()) or set())
        subs = [d for d in deps if d in set(ctx.todo)]
        if subs:
            goals[rid] = Goal(name=rid, members=sorted(subs))
            claimed.update(subs)
    # anything open that no goal claims becomes its own leaf goal
    for rid in ctx.todo:
        if rid not in goals and rid not in claimed:
            goals[rid] = Goal(name=rid, members=[rid])
    return list(goals.values())


def goalact(ctx, failure_p: float = 0.15, seed: int = 0) -> list[str]:
    """Global milestone order; each milestone's sub-goals run before the next.

    Milestones are ordered by how much they unblock, then by cost — the same
    signal the flat planner uses, applied one level up.
    """
    goals = build_goals(ctx)
    goals.sort(key=lambda g: (-len(g.members) / max(g.cost, 1e-9), g.name))
    order: list[str] = []
    for g in goals:
        order.extend(g.members)
        order.append(g.name)          # the milestone itself is checked last
    # anything the goals did not cover, in the flat planner's order
    rest = [r for r in greedy(ctx, ctx.todo) if r not in order]
    return order + rest


def reactree(ctx, failure_p: float = 0.15, seed: int = 0,
             min_group: int = 2) -> list[str]:
    """Recursive: a goal too big to finish cheaply is split again.

    Where GoalAct commits to a milestone order up front, ReAcTree re-derives it,
    so a goal whose sub-goals are themselves grouped becomes a tree rather than a
    flat list. The recursion stops when a group is small enough to run whole.
    """
    def order_goal(g: Goal, depth: int = 0, milestone: str | None = None) -> list[str]:
        """Members first, then the milestone they feed.

        `milestone` is carried down rather than using `g.name`: a synthetic
        sub-goal is named `cov_56/a`, which is not a result, and emitting it put
        names into the plan that nothing could ever settle — reactree scored 0.00
        milestones because of it.
        """
        milestone = milestone or g.name
        if len(g.members) <= min_group or depth > 4:
            return g.members
        half = len(g.members) // 2
        left = Goal(f"{g.name}/a", g.members[:half])
        right = Goal(f"{g.name}/b", g.members[half:])
        # the milestone is emitted by the caller, once, after every member —
        # emitting it at each level put it after the left half only, where it can
        # never settle because the right half has not run
        return order_goal(left, depth + 1, milestone) + order_goal(right, depth + 1, milestone)

    goals = build_goals(ctx)
    goals.sort(key=lambda g: (-len(g.members), g.name))
    order: list[str] = []
    for g in goals:
        order.extend(order_goal(g))
        order.append(g.name)          # once, after every member of this goal
    seen, uniq = set(), []
    for r in order:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    rest = [r for r in greedy(ctx, ctx.todo) if r not in seen]
    return uniq + rest


def milestones_done(ctx, settled: set[str]) -> int:
    """How many milestone (coverage-style) results are settled."""
    out = 0
    for rid in ctx.todo:
        deps = set(getattr(ctx.results.get(rid), "depends_on_results", set()) or set())
        if deps and rid in settled:
            out += 1
    return out
