"""Reinforcement learning: the order to run checks in, under a budget.

The kernel computes the *minimum set* of checks that restores a clear answer. It
says nothing about the order, and order matters the moment the budget does not
cover the whole set: run the check that settles the most first and you can stop
early with most of the picture; run a cheap one that settles nothing and the
budget is gone.

That is a sequential decision problem with a measurable cost, so it is a
reinforcement learning problem rather than a modelling exercise:

* **state** — what is still in doubt, and what is still available to run.
* **action** — which check to run next.
* **reward** — minus its cost, plus a bonus for settling the set, minus a penalty
  for what is left unsettled when the budget runs out.

The settle structure is real: it comes from the graph, where running a check that
covers a block also settles every result whose dependency closure sits inside it.
The *costs* are synthetic, and that is the honest limit — with a real regression
farm they would come from measured run times.

The agent is linear Q-learning with function approximation, because the action
space is a variable-length set of candidates and a table cannot hold it. It is
scored against a greedy baseline, a random policy and a cheapest-first policy.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

__all__ = ["Instance", "instance_from_graph", "OrderingEnv", "LinearQ",
           "evaluate", "greedy_ratio", "cheapest_first", "random_policy"]

# features of (state, candidate)
Q_KEYS = ["settles", "cost", "ratio", "remaining_after", "is_cheapest",
          "is_biggest", "frac_settled", "remaining"]

# Fixed divisors so no single feature dominates the linear value. Without this
# the weights diverge: `remaining` runs to thirty while `is_cheapest` is 0 or 1,
# and the update blows up.
Q_SCALE = [10.0, 10.0, 10.0, 50.0, 1.0, 1.0, 1.0, 50.0]


@dataclass
class Instance:
    """A pending set: each check has a cost and settles a set of results."""
    name: str
    costs: list[float]
    settles: list[set[int]]          # settles[i] = results check i resolves
    budget: float = 0.0
    all_results: int = 0
    note: str = ""


def instance_from_graph(graph, results, changed: set[str], seed: int = 0,
                        cost_lo: float = 1.0, cost_hi: float = 8.0,
                        max_results: int | None = None) -> Instance:
    """Build a real settle structure from the graph.

    Check `i` settles check `j` when `j`'s dependency closure is contained in
    `i`'s — running the broader check answers the narrower question too.

    `max_results` samples the pending set down to a workable size. One change to
    OpenTitan puts ~390 results in doubt, and learning over a 390-action problem
    is 300M operations; a bounded sub-problem is the honest thing to learn on.
    """
    from ..kernel.validity import classify_all

    rng = random.Random(seed)
    verdicts = classify_all(graph, results, changed)
    pending = [c.result for c in verdicts
               if c.verdict.value in ("invalidated", "unknown")]
    if not pending:
        return Instance("empty", [], [], 0.0, 0, "nothing pending")
    sampled = False
    if max_results and len(pending) > max_results:
        pending = sorted(random.Random(seed + 7).sample(pending, max_results),
                         key=lambda r: r.id)
        sampled = True

    closures = []
    for r in pending:
        deps = set(getattr(r, "depends_on", []) or [])
        closure = set(deps)
        for d in deps:
            closure |= graph.ancestors(d)
        closures.append(closure)

    n = len(pending)
    settles = []
    for i in range(n):
        s = {j for j in range(n) if closures[j] and closures[j] <= closures[i]}
        settles.append(s or {i})
    costs = [round(rng.uniform(cost_lo, cost_hi), 2) for _ in range(n)]
    total = sum(costs)
    note = "settle structure from the graph; costs synthetic"
    if sampled:
        note += f"; sampled to {n} of the pending set"
    return Instance(
        name=f"{n} pending checks", costs=costs, settles=settles,
        budget=total * 0.5, all_results=n, note=note)


class OrderingEnv:
    """Pick a check, pay its cost, settle what it settles."""

    def __init__(self, inst: Instance, penalty: float = 1.0):
        self.inst = inst
        self.penalty = penalty
        self.reset()

    def reset(self):
        self.done: set[int] = set()
        self.available = list(range(len(self.inst.costs)))
        self.spent = 0.0
        return self.state()

    def state(self) -> dict:
        return {"done": len(self.done),
                "remaining": len(self.available),
                "total": self.inst.all_results,
                "spent": self.spent,
                "budget": self.inst.budget}

    def candidates(self) -> list[int]:
        return list(self.available)

    def features(self, action: int) -> list[float]:
        inst = self.inst
        st = self.state()
        settles = len(inst.settles[action] - self.done) or 1
        cost = inst.costs[action]
        cheapest = min((inst.costs[a] for a in self.available), default=cost)
        biggest = max((len(inst.settles[a]) for a in self.available), default=1)
        remaining = len(self.available)
        return [
            float(settles),
            cost,
            settles / cost,
            float(remaining - 1),
            1.0 if cost <= cheapest else 0.0,
            1.0 if len(inst.settles[action]) >= biggest else 0.0,
            st["done"] / max(inst.all_results, 1),
            float(remaining),
        ]

    def step(self, action: int):
        inst = self.inst
        if action not in self.available:
            return self.state(), -self.penalty, True
        newly = inst.settles[action] - self.done
        self.done |= inst.settles[action]
        self.spent += inst.costs[action]
        self.available.remove(action)
        reward = -inst.costs[action]
        over_budget = self.spent > inst.budget
        if over_budget:
            reward -= self.penalty * 2
        # the episode ends when nothing is left in doubt — not when every
        # candidate has been run. A check that settles the whole set ends it.
        all_settled = len(self.done) >= inst.all_results
        done = all_settled or over_budget or not self.available
        if done:
            left = inst.all_results - len(self.done)
            reward -= self.penalty * left
        return self.state(), reward, done


class LinearQ:
    """Linear action-value: Q(s, a) = w . phi(s, a), learned by Q-learning."""

    def __init__(self, n_features: int, lr: float = 0.05, gamma: float = 0.98,
                 epsilon: float = 0.15, seed: int = 0):
        self.w = [0.0] * n_features
        self.lr, self.gamma, self.epsilon = lr, gamma, epsilon
        self.rng = random.Random(seed)

    @staticmethod
    def _norm(feats: list[float]) -> list[float]:
        return [f / s for f, s in zip(feats, Q_SCALE)]

    def q(self, feats: list[float]) -> float:
        return sum(w * f for w, f in zip(self.w, self._norm(feats)))

    def act(self, env: OrderingEnv, greedy: bool = False) -> int:
        cands = env.candidates()
        if not cands:
            return -1
        if not greedy and self.rng.random() < self.epsilon:
            return self.rng.choice(cands)
        return max(cands, key=lambda a: self.q(env.features(a)))

    def update(self, feats: list[float], reward: float,
               next_feats: list[list[float]] | None, done: bool) -> None:
        # next_feats are the *candidates'* feature vectors, so the bootstrap is
        # the best action-value among them, not the largest vector
        best_next = max((self.q(f) for f in next_feats), default=0.0) \
            if next_feats else 0.0
        target = reward + (0.0 if done else self.gamma * best_next)
        err = target - self.q(feats)
        scaled = self._norm(feats)
        for j in range(len(self.w)):
            step = self.lr * err * scaled[j]
            if step != step or abs(step) > 1e6:        # non-finite: refuse it
                return
            self.w[j] = max(-20.0, min(20.0, self.w[j] + step))


def _run(env: OrderingEnv, choose, learn: LinearQ | None = None) -> float:
    """One episode; returns the total cost paid."""
    env.reset()
    total = 0.0
    # an episode cannot need more steps than there are candidates
    for _step in range(len(env.inst.costs) + 1):
        cands = env.candidates()
        if not cands:
            break
        action = choose(env, cands)
        before = env.features(action) if learn else None
        _, reward, done = env.step(action)
        total += env.inst.costs[action]
        if learn:
            nxt = [env.features(a) for a in env.candidates()] or None
            learn.update(before, reward, nxt, done)
        if done:
            break
    return total


def train(instances: list[Instance], episodes: int = 600, seed: int = 0,
          lr: float = 0.05) -> LinearQ:
    """Q-learning over a set of instances, so the weights generalise across them."""
    agent = LinearQ(len(Q_KEYS), lr=lr, seed=seed)
    rng = random.Random(seed)
    for ep in range(episodes):
        inst = instances[ep % len(instances)] if instances else None
        if inst is None:
            break
        env = OrderingEnv(inst)
        if agent.epsilon > 0.05 and ep > episodes // 2:
            agent.epsilon *= 0.999
        _run(env, lambda e, c: agent.act(e), learn=agent)
    return agent


# ---- baselines -------------------------------------------------------------
def greedy_ratio(env: OrderingEnv, cands: list[int]) -> int:
    """Settle the most per unit cost — the obvious thing to do."""
    return max(cands, key=lambda a: (len(env.inst.settles[a] - env.done)
                                     / max(env.inst.costs[a], 1e-9)))


def cheapest_first(env: OrderingEnv, cands: list[int]) -> int:
    return min(cands, key=lambda a: env.inst.costs[a])


def random_policy(env: OrderingEnv, cands: list[int]) -> int:
    return random.choice(cands)


def evaluate(policy, instances: list[Instance], agent: LinearQ | None = None,
             seed: int = 0) -> dict:
    """Mean cost and settled fraction, over fresh instances."""
    costs, settled = [], []
    for inst in instances:
        env = OrderingEnv(inst)
        if agent is not None:
            total = _run(env, lambda e, c: agent.act(e, greedy=True))
        else:
            total = _run(env, lambda e, c: policy(e, c))
        costs.append(total)
        settled.append(len(env.done) / max(inst.all_results, 1))
    n = max(len(costs), 1)
    return {"mean_cost": sum(costs) / n,
            "mean_settled": sum(settled) / n,
            "n": len(costs)}
