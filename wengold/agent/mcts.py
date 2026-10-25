"""MCTS over plan orderings, with UCB1 for selection.

The tree is over *prefixes* of the plan: the root is the empty order, each edge
adds one result, a node is complete when every result has been placed. Selection
uses UCB1, expansion adds one untried child, simulation completes the order
randomly and rolls it out under the failure model, and the score is backed up the
path.

Why a tree at all, when `search.beam` already exists: beam keeps `width` partial
orders and scores each by one rollout, so it spends its budget broadly and shallowly.
MCTS spends it where the tree is still uncertain — a prefix that has looked good
but has been tried only twice keeps getting attention, while one that has looked
bad and been tried twenty times does not. That is the difference the UCB1 term
buys, and whether it pays is measured, not assumed.

`c` controls exploration. At c = 0 this degenerates to greedy replay of the best
child, which is the honest way to show what the exploration term contributes.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .planning import _cost
from .search import score_order

__all__ = ["Node", "mcts", "MCTSResult"]


@dataclass
class Node:
    prefix: list[str]
    parent: "Node | None" = None
    children: list["Node"] = field(default_factory=list)
    untried: list[str] = field(default_factory=list)
    visits: int = 0
    value: float = 0.0

    def ucb(self, c: float) -> float:
        if self.visits == 0:
            return float("inf")
        exploit = self.value / self.visits
        explore = c * math.sqrt(math.log(max(self.parent.visits, 1)) / self.visits) \
            if self.parent else 0.0
        return exploit + explore


@dataclass
class MCTSResult:
    order: list[str]
    score: float
    nodes: int
    rollouts: int

    def render(self) -> str:
        return (f"  mcts: {self.rollouts} rollout(s), {self.nodes} node(s), "
                f"score {self.score:.2f}")


def _expand(node: Node, remaining: list[str]) -> Node:
    """Add one untried child."""
    pick = node.untried.pop(0)
    child = Node(prefix=node.prefix + [pick], parent=node,
                 untried=[r for r in remaining if r != pick])
    node.children.append(child)
    return child


def mcts(ctx, rollouts: int = 200, c: float = 1.4, failure_p: float = 0.15,
         trials: int = 32, seed: int = 0, budget: int | None = None) -> MCTSResult:
    """Search the space of orderings, scoring by rollout under the failure model."""
    rng = random.Random(seed)
    todo = list(ctx.todo)
    if budget:
        todo_for_score = todo
    root = Node(prefix=[], untried=list(todo))
    nodes = 1

    def rollout_score(order: list[str]) -> float:
        seq = order[:budget] if budget else order
        return score_order(ctx, seq, failure_p, trials, rng.randrange(10 ** 6))

    for _ in range(rollouts):
        # --- selection
        node = root
        while not node.untried and node.children:
            node = max(node.children, key=lambda n: n.ucb(c))

        # --- expansion
        if node.untried:
            node = _expand(node, todo)
            nodes += 1

        # --- simulation: complete the order at random from here
        remaining = [r for r in todo if r not in node.prefix]
        rng.shuffle(remaining)
        score = rollout_score(node.prefix + remaining)

        # --- backpropagation
        walk = node
        while walk is not None:
            walk.visits += 1
            walk.value += score
            walk = walk.parent

    # the answer is the greediest full path through the tree
    best, node = list(root.prefix), root
    while node.children:
        node = max(node.children, key=lambda n: (n.visits, n.ucb(c)))
        best = node.prefix
    remaining = [r for r in todo if r not in best]
    order = best + remaining
    return MCTSResult(order=order,
                      score=score_order(ctx, order[:budget] if budget else order,
                                        failure_p, trials, seed),
                      nodes=nodes, rollouts=rollouts)
