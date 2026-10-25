"""A swarm scheduler: no centre, local decisions, and it survives losing members.

Every planner in this package so far has been centralised — one component holds the
whole open set and orders it. That has a property nobody asked for and everybody
inherits: **if that component stops, the work stops.** The swarm claim is precisely
that this is avoidable.

Three properties, and each is implemented rather than asserted:

* **Decentralised control** — no worker schedules another. There is no scheduler
  object. `Swarm.step()` asks every living worker for its own next move.
* **Local interaction** — a worker owns a slice of the open set (one IP, in a real
  design) and only chooses among results in it. It cannot see the other slices'
  contents, only whether the results they feed have settled.
* **Fault tolerance** — a dead worker's slice stops; the rest do not. That is the
  whole point, and it is the only thing here that a central planner cannot match.

The rule inside a worker is deliberately trivial: take the result it believes most
likely to pass, among those it can act on. That is the same `safest_first` signal
from `belief.py`, applied locally. Nothing emergent is claimed — what is claimed is
that a trivial local rule plus no centre is *robust*, and the cost of that is
measured rather than waved away.

`potential` gives the other rule from the literature: attraction from how much a
result unblocks, repulsion from how likely it is to fail. It is a vector field over
the result graph and it is compared, not preferred.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..kernel.validity import Verdict
from .belief import Belief

__all__ = ["Worker", "Swarm", "SwarmRun", "partition", "potential"]


def _ip_of(result_id: str, ctx) -> str:
    """The IP a result belongs to — the natural neighbourhood in a real design."""
    deps = getattr(ctx.results.get(result_id), "depends_on", set()) or set()
    for d in sorted(deps):
        # open-titan names: adc_ctrl_core -> adc_ctrl; aes_cipher_core -> aes
        parts = d.split("_")
        return parts[0] if parts else d
    return "unowned"


def partition(ctx, n_workers: int = 4) -> dict[str, set[str]]:
    """Split the open set into `n_workers` slices, by IP where possible.

    Grouping by IP rather than by count is deliberate: it is what makes the
    neighbourhood *local*. A worker owning all of `aes` shares almost no state with
    one owning `usbdev`, which is the situation the swarm is supposed to handle.
    """
    groups: dict[str, set[str]] = {}
    for rid in ctx.todo:
        groups.setdefault(_ip_of(rid, ctx), set()).add(rid)
    slices = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    out: dict[str, set[str]] = {}
    for i in range(n_workers):
        out[f"w{i}"] = set()
    # largest-first bin packing, so slices are comparable in size
    for ip, members in slices:
        target = min(out, key=lambda w: len(out[w]))
        out[target] |= members
    return {w: s for w, s in out.items() if s}


@dataclass
class Worker:
    name: str
    owns: set[str]
    alive: bool = True
    checks: int = 0

    def next_move(self, ctx, settled: set[str], belief: Belief | None,
                  rule: str = "safest") -> str | None:
        """Choose locally. No worker is consulted about any other's choice."""
        if not self.alive:
            return None
        open_here = [r for r in self.owns if r not in settled]
        if not open_here:
            return None
        # a result is actionable when what it rests on has settled — this is the
        # only thing a worker needs to know about the rest of the design
        def ready(r):
            deps = set(getattr(ctx.results.get(r), "depends_on_results",
                               set()) or set())
            return deps <= settled

        candidates = [r for r in open_here if ready(r)] or open_here
        if rule == "potential":
            return max(candidates, key=lambda r: potential(ctx, r, belief))
        if belief is not None:
            return max(candidates, key=lambda r: (belief.p(r), -len(r)))
        return candidates[0]


def potential(ctx, rid: str, belief: Belief | None) -> float:
    """Attraction from what it unblocks, repulsion from how likely it is to fail.

    The sign convention is the point: a check that unblocks a lot pulls the
    scheduler towards it, and a check likely to fail pushes it away, because a
    failure stops the run. With no belief, repulsion is zero and this reduces to
    the flat heuristic.
    """
    attraction = len(ctx.dependents.get(rid, set())) + 1.0
    repulsion = 1.0 - (belief.p(rid) if belief else 0.5)
    return attraction - 2.0 * repulsion


@dataclass
class SwarmRun:
    settled: set[str] = field(default_factory=set)
    checks: int = 0
    per_worker: dict = field(default_factory=dict)
    dead: list[str] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return False  # a swarm has no global completion condition to report

    def render(self) -> str:
        return (f"  swarm: {self.checks} check(s), {len(self.settled)} settled, "
                f"dead={self.dead or 'none'}, per-worker {self.per_worker}")


class Swarm:
    """N workers, no centre, and a way to kill members."""

    def __init__(self, ctx, n_workers: int = 4, belief: Belief | None = None,
                 rule: str = "safest", seed: int = 0):
        self.ctx = ctx
        self.belief = belief
        self.rule = rule
        self.slices = partition(ctx, n_workers)
        self.workers = [Worker(name=w, owns=s) for w, s in self.slices.items()]
        self.rng = random.Random(seed)

    def kill(self, *names: str) -> None:
        for w in self.workers:
            if w.name in names:
                w.alive = False

    def run(self, runner, max_checks: int = 40, kill_after: int = -1,
            kill: tuple = (), max_rounds: int | None = None) -> SwarmRun:
        """Run the swarm.

        `max_checks` caps the total work; `max_rounds` caps the *time*. The
        difference is the whole point of a swarm and it took a wrong measurement to
        see it: under a check budget, killing workers changes nothing, because one
        survivor simply spends the whole budget itself. A swarm's resilience only
        shows up when the constraint is rounds — one check per living worker per
        round — and losing a worker then costs throughput directly.
        """
        run = SwarmRun()
        settled = set(self.ctx.by_verdict(Verdict.VALID))
        run.per_worker = {w.name: 0 for w in self.workers}
        rounds = 0

        while run.checks < max_checks:
            if max_rounds is not None and rounds >= max_rounds:
                break
            rounds += 1
            if kill_after >= 0 and run.checks >= kill_after and not run.dead:
                self.kill(*kill)
                run.dead = list(kill)
            moved = False
            for w in self.workers:
                if not w.alive:
                    continue
                rid = w.next_move(self.ctx, settled, self.belief, self.rule)
                if rid is None:
                    continue
                outcome = runner(rid, getattr(self.ctx.results.get(rid), "kind",
                                              None) or "sim")
                if not isinstance(outcome, dict):
                    outcome = outcome.as_dict()
                w.checks += 1
                run.checks += 1
                run.per_worker[w.name] = run.per_worker.get(w.name, 0) + 1
                moved = True
                if outcome.get("outcome") == "pass":
                    settled.add(rid)
                    changed = True
                    while changed:
                        changed = False
                        for o in self.ctx.todo:
                            if o in settled:
                                continue
                            d = set(getattr(self.ctx.results.get(o),
                                            "depends_on_results", set()) or set())
                            if d and d <= settled:
                                settled.add(o)
                                changed = True
                if run.checks >= max_checks:
                    break
                if max_rounds is not None and run.checks >= rounds * len(self.workers):
                    break   # this round's slot is spent
            if not moved:
                break
        run.settled = settled
        return run
