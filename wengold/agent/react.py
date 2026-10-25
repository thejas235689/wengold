"""ReAct: interleave a thought, an action and an observation, and let the
observation decide the next thought.

This is not the batch loop in `loop.py`. There the whole plan is made up front and
executed in order. Here there is no up-front plan: each step is chosen from what
the *last observation* said, which is the whole point of interleaving — a failing
check changes the next action from "continue" to "diagnose", and a pass changes it
to "take what that unblocked".

The thought is generated from the observation, not recalled, so it cannot claim
something the run did not show. When nothing sensible follows an observation the
loop stops rather than inventing a move.

    thought   "the base result must be re-established first"
    action    run sec_firewall_sim
    observe   pass
    thought   "cov_0 rested on it and is now settled for free"
    action    run soc_smoke
    observe   fail
    thought   "it failed; diagnose before spending another check"
    action    diagnose soc_smoke
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.validity import Verdict

__all__ = ["Step", "ReActRun", "react"]


@dataclass
class Step:
    n: int
    thought: str
    action: str
    target: str | None
    observation: str
    because: list[str] = field(default_factory=list)

    def render(self) -> str:
        tail = f"   [{' , '.join(self.because)}]" if self.because else ""
        tgt = f" {self.target}" if self.target else ""
        return (f"  {self.n:2}. think: {self.thought}{tail}\n"
                f"      act  : {self.action}{tgt}\n"
                f"      obs  : {self.observation}")


@dataclass
class ReActRun:
    steps: list[Step] = field(default_factory=list)
    settled: set[str] = field(default_factory=set)
    checks: int = 0
    done: bool = False

    def render(self) -> str:
        head = (f"react: {len(self.steps)} step(s), {self.checks} check(s), "
                f"{len(self.settled)} settled, done={self.done}")
        return "\n".join([head] + [s.render() for s in self.steps])


def _next_target(ctx, settled: set[str], tried: set[str]) -> str | None:
    """The next result worth a check: open, untried, and unblocked."""
    for rid in ctx.todo:
        if rid in settled or rid in tried:
            continue
        deps = set(getattr(ctx.results.get(rid), "depends_on_results", set()) or set())
        if deps <= (settled | set(ctx.by_verdict(Verdict.VALID))):
            return rid
    # nothing unblocked: take any open, untried result
    for rid in ctx.todo:
        if rid not in settled and rid not in tried:
            return rid
    return None


def react(ctx, runner, diagnose=None, max_steps: int = 40) -> ReActRun:
    """Think, act, observe — each thought chosen from the previous observation."""
    run = ReActRun()
    settled = set(ctx.by_verdict(Verdict.VALID))
    tried: set[str] = set()
    n = 0

    while len(run.steps) < max_steps:
        target = _next_target(ctx, settled, tried)
        if target is None:
            n += 1
            run.steps.append(Step(
                n, "every open result has been tried; nothing left to do",
                "stop", None, "the loop is finished"))
            run.done = True
            break

        kind = getattr(ctx.results.get(target), "kind", None) or "sim"
        n += 1
        thought = (f"{target} is open and everything it rests on is settled, so "
                   f"it is the next thing that can be decided")
        outcome = runner(target, kind)
        if not isinstance(outcome, dict):
            outcome = outcome.as_dict()
        run.checks += 1
        tried.add(target)
        verdict = outcome.get("outcome", "unknown")
        run.steps.append(Step(n, thought, "run", target, verdict,
                              [target]))

        if verdict == "pass":
            settled.add(target)
            # what that unblocked
            gained = []
            for rid in ctx.todo:
                if rid in settled:
                    continue
                deps = set(getattr(ctx.results.get(rid),
                                   "depends_on_results", set()) or set())
                if deps and deps <= settled:
                    settled.add(rid)
                    gained.append(rid)
            n += 1
            obs = (f"{len(gained)} result(s) settled for free" if gained
                   else "nothing else depended on it")
            run.steps.append(Step(
                n, "a pass means what rested on it can be taken as settled",
                "observe", None, obs, gained[:6]))
        else:
            # the observation changes the next action: diagnose before continuing
            n += 1
            diag = "no diagnoser configured"
            if diagnose is not None:
                try:
                    diag = str(diagnose(outcome))[:160]
                except Exception as e:  # noqa: BLE001
                    diag = f"diagnosis failed: {e}"
            run.steps.append(Step(
                n, "it failed, so continuing would spend checks on results that "
                   "rest on a broken one — diagnose first",
                "diagnose", target, diag, [target]))

    run.settled = settled
    return run
