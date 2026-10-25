"""Adaptation: learn which strategy to plan with, from what actually happened.

This is the honest form of "the system refines future decisions". It is not RLHF —
there is no human and no reward model. It is a bandit over the three planning
strategies, rewarded by what the run cost and how much it settled, which is
self-supervised by definition: the ledger already records both.

The reason to keep it a bandit rather than a network is the same reason the
earlier Q-learning work lost to a two-line heuristic: with three arms and a
handful of runs, a bandit converges and a network overfits. The bandit also
reports its own uncertainty, so a strategy chosen once does not become permanent
on the strength of a single lucky run.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

__all__ = ["Bandit"]


@dataclass
class Arm:
    name: str
    pulls: int = 0
    reward: float = 0.0

    @property
    def mean(self) -> float:
        return self.reward / self.pulls if self.pulls else 0.0

    def ucb(self, total: int) -> float:
        if self.pulls == 0:
            return float("inf")
        return self.mean + math.sqrt(2.0 * math.log(max(total, 1)) / self.pulls)


@dataclass
class Bandit:
    """UCB1 with an epsilon floor, so a stale choice can still be revisited."""

    names: list[str] = field(default_factory=lambda: ["cheapest", "greedy",
                                                      "best_first"])
    epsilon: float = 0.1
    seed: int = 0
    arms: dict = field(init=False)

    def __post_init__(self):
        self.arms = {n: Arm(n) for n in self.names}
        self._rng = random.Random(self.seed)
        self.history: list[dict] = []

    @property
    def total(self) -> int:
        return sum(a.pulls for a in self.arms.values())

    def choose(self) -> str:
        if self._rng.random() < self.epsilon:
            return self._rng.choice(self.names)
        return max(self.arms.values(), key=lambda a: a.ucb(self.total)).name

    def update(self, name: str, settled: int, checks: int) -> float:
        """Reward = the fraction of the open set settled per check spent.

        Zero checks means nothing needed doing — that is a perfect score, not a
        division by zero, so it is rewarded as 1.
        """
        reward = 1.0 if checks == 0 else settled / checks
        arm = self.arms[name]
        arm.pulls += 1
        arm.reward += reward
        self.history.append({"arm": name, "settled": settled, "checks": checks,
                             "reward": reward})
        return reward

    def best(self) -> str:
        return max(self.arms.values(), key=lambda a: (a.mean, a.pulls)).name

    def render(self) -> str:
        lines = [f"  {'strategy':<12}{'pulls':>7}{'mean reward':>14}"]
        lines.append("  " + "-" * 33)
        for a in sorted(self.arms.values(), key=lambda a: -a.mean):
            lines.append(f"  {a.name:<12}{a.pulls:>7}{a.mean:>14.3f}")
        return "\n".join(lines)
