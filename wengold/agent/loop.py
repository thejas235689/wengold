"""The agent loop: perceive → reason → plan → act → reflect → adapt.

Six stages, and each one is wired to something real rather than to a prompt:

1. **Perceive** — read the graph, the results, the tool availability and the
   kernel's classification (`perception.perceive`).
2. **Reason** — produce a checkable chain of thought per result: why does it have
   the verdict it has, citing the nodes and results it rests on (`reasoning.explain`).
3. **Plan** — order the minimum new evidence, choosing a strategy
   (`planning.plan`). Which strategy is itself learned — see stage 6.
4. **Act** — execute each step through a runner, recording the outcome. The
   runner is the same one the orchestrator uses, so a missing tool is reported as
   `tool_missing` and never as a pass.
5. **Reflect** — compare what happened against the goal. If results are still open,
   re-perceive (the world changed) and re-plan, bounded by `max_iters`. A run that
   changes nothing is not retried.
6. **Adapt** — feed the run's outcome back to the bandit, so the next run's choice
   of strategy is informed by this one.

**What is modelled and what is measured.** The dependency structure, the
classification and the minimum evidence are the real kernel's. Whether a check
*settles* a result is modelled, because no simulator or prover is installed here —
`SimulatedRunner` says so in its own docstring. That is the honest boundary, and
the benchmark reports it rather than dressing a model up as a measurement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.validity import Verdict, classify_all
from .adaptation import Bandit
from .perception import Context, perceive
from .planning import plan as make_plan
from .reasoning import Trace, explain_all

__all__ = ["Agent", "AgentRun", "SimulatedRunner"]


@dataclass
class AgentRun:
    strategy: str
    context: Context
    traces: list[Trace] = field(default_factory=list)
    plan: list[dict] = field(default_factory=list)
    outcomes: list[dict] = field(default_factory=list)
    iterations: int = 0
    runs: int = 0
    settled: int = 0
    reward: float = 0.0
    reflections: list[str] = field(default_factory=list)

    @property
    def done(self) -> bool:
        return self.context.settled

    def render(self) -> str:
        lines = [f"perception: {self.context.summary()}"]
        for note in self.context.notes:
            lines.append(f"  ! {note}")
        lines.append(f"reasoning: {len(self.traces)} trace(s)")
        for t in self.traces[:3]:
            lines.append(t.render())
        if len(self.traces) > 3:
            lines.append(f"  … {len(self.traces) - 3} more")
        lines.append(f"plan ({self.strategy}): {len(self.plan)} step(s)")
        for s in self.plan:
            warn = "" if s["available"] else "   (tool not installed)"
            lines.append(f"  {s['step']}. {s['result']:<22} {s['kind']:<8} "
                         f"cost {s['cost']:.1f}  unblocks {s['blocked_by_it']}{warn}")
        if self.outcomes:
            lines.append("act:")
            for o in self.outcomes:
                lines.append(f"  {o['result']:<22} {o['outcome']:<12} "
                             f"{o.get('tool') or '-'}")
        if self.reflections:
            lines.append("reflect:")
            for r in self.reflections:
                lines.append(f"  {r}")
        lines.append(f"adapt: reward {self.reward:.3f}  "
                     f"({self.settled} settled / {self.runs} check(s), "
                     f"{self.iterations} iteration(s))")
        return "\n".join(lines)


class SimulatedRunner:
    """Settles a result when it is run, and auto-settles results whose inputs are
    all settled.

    **This is a model, not a measurement.** No simulator or prover is installed in
    this environment, so "did the check pass?" cannot be observed. What *is* real
    is the dependency structure: a result whose result-dependencies are all settled
    needs no separate run, which is what makes the order of the plan matter. The
    benchmark therefore measures *ordering*, not verification.
    """

    def __init__(self, settle_always: bool = True):
        self.settle_always = settle_always
        self.calls: list[str] = []

    def __call__(self, rid: str, kind: str) -> dict:
        self.calls.append(rid)
        return {"result": rid, "tool": "simulated", "outcome": "pass",
                "rc": 0, "kind": kind}


def _auto_settled(ctx: Context, settled: set[str]) -> set[str]:
    """Results whose result-dependencies are all settled need no run of their own.

    Seeded with the results the kernel already calls VALID: a coverage result whose
    simulations are all either valid or re-established needs no rerun of its own.
    Without that seed nothing ever auto-settles, every strategy ties, and the
    comparison is meaningless — which is what the first version did.
    """
    changed = True
    out = set(settled) | set(ctx.by_verdict(Verdict.VALID))
    while changed:
        changed = False
        for rid in ctx.todo:
            if rid in out:
                continue
            deps = set(getattr(ctx.results.get(rid), "depends_on_results", set()) or set())
            if deps and deps <= out:
                out.add(rid)
                changed = True
    return out


class Agent:
    def __init__(self, graph, results, ledger=None, bandit: Bandit | None = None,
                 seed: int = 0):
        self.graph = graph
        self.results = results
        self.ledger = ledger
        self.bandit = bandit or Bandit(seed=seed)
        self.seed = seed

    def _log(self, kind: str, payload: dict) -> None:
        if self.ledger is not None:
            try:
                self.ledger.append(kind, payload)
            except Exception:
                pass

    def run(self, changed, runner=None, max_iters: int = 3,
            strategy: str | None = None, adaptive: bool = True,
            budget: int | None = None) -> AgentRun:
        """Run the six stages.

        `budget` caps how many checks may be spent. Without a cap the order of the
        plan cannot change how many checks are needed — the kernel's minimum
        evidence is already minimal and the auto-settle cascade is
        order-independent, which the first benchmark showed by tying three
        strategies at the same count. Under a cap the order decides *how much gets
        settled before the money runs out*, which is the question planning can
        actually answer.
        """
        runner = runner or SimulatedRunner()
        chosen = strategy or (self.bandit.choose() if adaptive else "best_first")
        ctx = perceive(self.graph, self.results, changed)
        run = AgentRun(strategy=chosen, context=ctx)
        run.traces = explain_all(ctx)
        # the kernel's VALID results are already settled; a plan only has to
        # re-establish the rest
        settled: set[str] = set(ctx.by_verdict(Verdict.VALID))

        for it in range(1, max_iters + 1):
            run.iterations = it
            if not ctx.todo:
                break
            run.plan = make_plan(ctx, chosen)
            self._log("plan", {"iter": it, "strategy": chosen,
                               "steps": [s["result"] for s in run.plan]})

            progressed = False
            for step in run.plan:
                if budget is not None and run.runs >= budget:
                    run.reflections.append(
                        f"budget of {budget} check(s) reached with "
                        f"{len(ctx.todo) - len(settled & set(ctx.todo))} still open")
                    break
                rid = step["result"]
                if rid in settled:
                    continue
                outcome = runner(rid, step["kind"])
                if not isinstance(outcome, dict):
                    outcome = outcome.as_dict()
                run.outcomes.append(outcome)
                run.runs += 1
                self._log("run", {"iter": it, "result": rid,
                                  "outcome": outcome.get("outcome")})
                if outcome.get("outcome") == "pass":
                    settled.add(rid)
                    progressed = True
                    # a result whose inputs are now all settled comes for free
                    for extra in _auto_settled(ctx, settled) - settled:
                        settled.add(extra)
                        run.reflections.append(
                            f"{extra} settled without its own run — everything it "
                            f"rested on is settled")

            # ---- reflect: re-perceive, and stop if nothing moved
            still = [r for r in ctx.todo if r not in settled]
            run.settled = len(settled & set(ctx.todo))
            if not still:
                run.reflections.append("goal met: no result needs new evidence")
                ctx.todo = []
                break
            if not progressed:
                run.reflections.append(
                    f"iteration {it} settled nothing new — stopping rather than "
                    f"retrying the same plan")
                break
            ctx = perceive(self.graph, self.results, changed)
            ctx.todo = still
            run.context = ctx
            run.reflections.append(
                f"iteration {it}: {len(still)} still open, re-planned")

        # ---- adapt
        run.reward = self.bandit.update(chosen, run.settled, run.runs)
        self._log("adapt", {"strategy": chosen, "reward": run.reward,
                            "settled": run.settled, "runs": run.runs})
        return run
