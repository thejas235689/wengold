"""Multi-agent orchestration: a planner, an executor and a reviewer.

Three sub-agents with different jobs and — this is the part that matters —
**different information**. The planner sees the context and proposes. The executor
runs the plan. The reviewer sees the plan and the context *independently* and can
reject it before a single check is spent.

Why a separate reviewer rather than one agent checking its own work: a planner that
validated its own output would be marking its own homework. The reviewer here
re-derives what the plan must satisfy from the context — every open result covered,
no step relying on a tool that is not installed, no step taken before something it
depends on — and rejects with a reason. That is the same separation of duties the
validity kernel applies to evidence, applied to the agent's own plan.

The orchestrator runs planner → reviewer → (revise, bounded) → executor, and
records every hand-off so the exchange is auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.validity import Verdict
from .planning import plan as make_plan

__all__ = ["Handoff", "Verdict_", "Review", "Planner", "Executor", "Reviewer",
           "Orchestra"]


@dataclass
class Handoff:
    frm: str
    to: str
    what: str
    detail: str = ""

    def render(self) -> str:
        tail = f"  ({self.detail})" if self.detail else ""
        return f"  {self.frm:>8} -> {self.to:<9} {self.what}{tail}"


@dataclass
class Review:
    accepted: bool
    problems: list[str] = field(default_factory=list)

    def render(self) -> str:
        if self.accepted:
            return "accepted"
        return "REJECTED: " + "; ".join(self.problems)


@dataclass
class Verdict_:
    """Kept distinct from the kernel's Verdict on purpose."""
    ok: bool
    reason: str


class Planner:
    """Proposes an ordered plan from the context."""

    name = "planner"

    def __init__(self, strategy: str = "best_first"):
        self.strategy = strategy

    def propose(self, ctx, strategy: str | None = None) -> list[dict]:
        return make_plan(ctx, strategy or self.strategy)


class Reviewer:
    """Independently re-derives what a plan must satisfy, and checks it.

    It does not trust the planner's reasoning: it recomputes the obligations from
    the context and tests the plan against them.
    """

    name = "reviewer"

    def review(self, ctx, steps: list[dict]) -> Review:
        problems: list[str] = []
        covered = {s["result"] for s in steps}
        open_results = set(ctx.todo)

        missing = sorted(open_results - covered)
        if missing:
            problems.append(f"{len(missing)} open result(s) not in the plan: "
                            f"{', '.join(missing[:4])}")

        extra = sorted(covered - open_results)
        if extra:
            problems.append(f"plan includes {len(extra)} result(s) that need no "
                            f"new evidence: {', '.join(extra[:4])}")

        # a step may not rely on a tool the machine does not have. Reported once
        # per tool, not once per step: on a real design every step needs the same
        # missing tool, and eleven identical lines hide the point.
        missing_tools: dict[str, list[int]] = {}
        for s in steps:
            tool = s.get("tool")
            if tool and ctx.tools.get(tool) is False:
                missing_tools.setdefault(tool, []).append(s["step"])
        for tool, where in missing_tools.items():
            problems.append(
                f"{len(where)} step(s) need {tool}, which is not installed "
                f"(steps {', '.join(str(w) for w in where[:6])}"
                f"{'…' if len(where) > 6 else ''})")

        # a result may not be scheduled before something it depends on, when that
        # something is itself in the plan
        position = {s["result"]: s["step"] for s in steps}
        for s in steps:
            deps = set(getattr(ctx.results.get(s["result"]),
                               "depends_on_results", set()) or set()) & covered
            late = [d for d in deps if position.get(d, 0) > s["step"]]
            if late:
                problems.append(f"step {s['step']} ({s['result']}) is scheduled "
                                f"before {', '.join(sorted(late)[:3])}, which it "
                                f"depends on")

        return Review(accepted=not problems, problems=problems)


class Executor:
    """Runs a plan, one step at a time, reporting what each step produced."""

    name = "executor"

    def execute(self, ctx, steps, runner) -> list[dict]:
        outcomes = []
        for s in steps:
            outcome = runner(s["result"], s["kind"])
            if not isinstance(outcome, dict):
                outcome = outcome.as_dict()
            outcomes.append(outcome)
        return outcomes


@dataclass
class Orchestra:
    """Planner -> Reviewer -> (revise) -> Executor, with every hand-off recorded."""

    strategy: str = "best_first"
    max_revisions: int = 2

    def run(self, ctx, runner, strategy: str | None = None) -> dict:
        planner, reviewer, executor = Planner(self.strategy), Reviewer(), Executor()
        handoffs: list[Handoff] = []
        reviews: list[Review] = []
        steps = planner.propose(ctx, strategy)
        handoffs.append(Handoff("planner", "reviewer", "plan proposed",
                                f"{len(steps)} step(s)"))

        revisions = 0
        while True:
            review = reviewer.review(ctx, steps)
            reviews.append(review)
            handoffs.append(Handoff("reviewer", "planner", review.render()))
            if review.accepted or revisions >= self.max_revisions:
                break
            revisions += 1
            # revise: re-plan with a *different* strategy, and carry the choice
            # forward — recomputing it from the original argument alternated to
            # the same strategy every time
            current = getattr(self, "_last_strategy", strategy or self.strategy)
            alt = "cheapest" if current != "cheapest" else "greedy"
            self._last_strategy = alt
            steps = planner.propose(ctx, alt)
            handoffs.append(Handoff("planner", "reviewer",
                                    f"re-planned with {alt}",
                                    f"{len(steps)} step(s)"))

        if not reviews[-1].accepted:
            handoffs.append(Handoff("orchestra", "executor",
                                    "refusing to execute an unreviewed plan"))
            return {"executed": False, "reviews": reviews, "handoffs": handoffs,
                    "outcomes": [], "revisions": revisions}

        handoffs.append(Handoff("reviewer", "executor", "plan approved"))
        outcomes = executor.execute(ctx, steps, runner)
        handoffs.append(Handoff("executor", "orchestra", "execution finished",
                                f"{len(outcomes)} outcome(s)"))
        return {"executed": True, "reviews": reviews, "handoffs": handoffs,
                "outcomes": outcomes, "revisions": revisions, "steps": steps}

    @staticmethod
    def render(result: dict) -> str:
        lines = ["orchestration:"]
        for h in result["handoffs"]:
            lines.append(h.render())
        lines.append(f"  executed: {result['executed']}  "
                     f"revisions: {result['revisions']}  "
                     f"outcomes: {len(result['outcomes'])}")
        return "\n".join(lines)
