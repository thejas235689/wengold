"""Agentic coding: a loop that decides what to do from what the kernel proved.

**There is no language model here.** That is the defining constraint, not a
shortcut. A coding agent without a model can still be useful if every decision it
takes is justified by something the tool actually knows, and useless if it
pretends otherwise — so this module has exactly one rule:

    every step names the fact that caused it.

The facts available are the kernel's and the graph's: which modules are unresolved,
which results are invalidated, which checks failed, what the completeness report
says. From those the loop can do four things, and it refuses everything else:

| what it can do | the fact that triggers it |
| --- | --- |
| stub the modules that are instantiated but not defined | `completeness()["unresolved"]` |
| suggest a fix for a check that failed | `review()` — which itself only reads checks that ran |
| generate a block from a spec, then verify it | `vibe()` — spec → RTL → testbench → simulation |
| stop, and say why | nothing is left that it can justify |

**How this differs from `vibe` and `review`.** Those are two commands you run.
This decides *which* to run, in what order, and when to stop — and it re-perceives
between steps, because acting changes the graph. Both are still there and still
callable directly; this composes them.

**What it will not do.** It will not write RTL logic, invent a missing module's
behaviour, guess a fix for a failing check, or claim a step succeeded because it
ran. `--apply` is required before anything is written; the default is to show the
diff and change nothing. And when it runs out of justified actions it stops and
says so rather than inventing a fifth one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

__all__ = ["Step", "CodingRun", "code", "render"]


@dataclass
class Step:
    """One decision, the fact behind it, and what happened."""
    n: int
    thought: str
    action: str
    fact: str
    outcome: str = ""
    ok: bool = True
    diff: str = ""

    def render(self) -> str:
        mark = "ok " if self.ok else "!! "
        out = [f"  {mark}{self.n}. {self.thought}",
               f"      fact:   {self.fact}",
               f"      action: {self.action}"]
        if self.outcome:
            out.append(f"      result: {self.outcome}")
        if self.diff:
            out.extend("      " + ln for ln in self.diff.rstrip().splitlines())
        return "\n".join(out)


@dataclass
class CodingRun:
    goal: str
    root: str
    steps: list[Step] = field(default_factory=list)
    done: bool = False
    reason: str = ""
    applied: bool = False
    drafted: bool = False

    @property
    def changed(self) -> bool:
        return any(s.diff for s in self.steps)

    def render(self) -> str:
        lines = [f"  goal: {self.goal}", f"  in:   {self.root}", ""]
        if not self.steps:
            lines.append("  no justified action — see the reason below")
        for s in self.steps:
            lines.append(s.render())
        lines.append("")
        lines.append(f"  {'done' if self.done else 'stopped'}: {self.reason}")
        if self.changed and not self.applied:
            lines.append("  nothing was written — re-run with --apply to take the "
                         "diffs above")
        lines.append("")
        if self.drafted:
            lines.append("  the draft step above is a MODEL'S OUTPUT, not a kernel "
                         "fact. It was compiled, not verified.")
            lines.append("  without --draft this loop writes no RTL and invents no "
                         "behaviour.")
        else:
            lines.append("  every step above is justified by a kernel fact; none is "
                         "a model's guess.")
            lines.append("  this does not write RTL logic, invent a missing "
                         "module's behaviour, or guess a fix for a check that did "
                         "not run.")
        return "\n".join(lines)


def _perceive(root: str):
    """Read the design and the kernel's view of it."""
    from ..desktop import build_state, _verdicts

    state = build_state(root)
    verdicts = _verdicts(state)
    return state, verdicts


def _failed(results) -> list:
    """Results the kernel says are invalidated or unknown — the actionable ones."""
    out = []
    for r in results or []:
        # `_verdicts` returns plain dicts. Reading `.verdict` off a dict always
        # gave None, so the loop believed nothing had failed — it announced
        # "no result invalidated" while the kernel reported one, and the review
        # branch was unreachable.
        v = r.get("verdict") if isinstance(r, dict) else getattr(r, "verdict", None)
        name = getattr(v, "name", str(v)).upper()
        if name in ("INVALIDATED", "UNKNOWN", "FAIL", "STALE"):
            out.append(r)
    return out


def code(goal: str, root: str, tools: str | None = None,
         apply: bool = False, max_steps: int = 6,
         draft: bool = False) -> CodingRun:
    """Run the loop until nothing left can be justified, or `max_steps`.

    `apply=False` shows every diff and writes nothing. That default is deliberate:
    a tool that edits RTL without showing the diff first is not one you would let
    near silicon signoff.
    """
    run = CodingRun(goal=goal, root=root, applied=apply)
    root_p = Path(root)

    if not root_p.exists():
        run.reason = f"{root} does not exist"
        return run

    state, verdicts = _perceive(root)
    blocks = state.get("block_names") or []

    # ---- decide, from facts only -----------------------------------------
    for n in range(1, max_steps + 1):
        completeness = state["graph"].completeness()
        unresolved = completeness.get("unresolved") or []

        # 1. a module is instantiated but not defined — the graph says so
        if unresolved:
            from .propose import missing_modules, propose_stubs

            missing = missing_modules(completeness)
            # `root` matters: the graph does not record an undefined module's
            # ports, but its instantiation site does, and the stub is better with
            # them than without.
            prop = propose_stubs(state["graph"], completeness, root)
            if prop is not None:
                step = Step(
                    n=n,
                    thought="stub the modules the graph knows are missing",
                    # name the modules being stubbed, and say which list they came
                    # from: `unresolved` holds the *dependents*, which is why an
                    # earlier version of this line named a module it was not
                    # touching
                    fact=(f"instantiated but not defined: "
                          f"{', '.join(missing[:4])}"
                          + (f"; completeness() marks "
                             f"{', '.join(str(u) for u in unresolved[:3])} "
                             f"unresolved as a consequence"
                             if unresolved else "")),
                    action=f"propose a diff against {prop.path}",
                    diff=prop.diff)
                if apply:
                    prop.apply(root)
                    run.applied = True
                    step.outcome = f"written to {prop.path}"
                    state, verdicts = _perceive(root)
                    run.steps.append(step)
                    continue
                # without --apply the world did not change, so re-perceiving would
                # find the same fact and propose the same diff. Stopping is the
                # honest move; repeating it six times is not a loop, it is a stutter.
                step.outcome = "diff shown, not written — nothing changed to re-plan from"
                run.steps.append(step)
                run.reason = ("showed a diff and wrote nothing; re-running with "
                              "--apply would take it and let the loop continue")
                return run

        # 2. a check failed — review() reads only checks that ran
        bad = _failed(getattr(verdicts, "results", []) or verdicts.get("results", []))
        if bad:
            from ..review import review

            rep = review(root, tools=tools)
            sugg = rep.get("suggestions") or []
            if sugg:
                s0 = sugg[0]
                run.steps.append(Step(
                    n=n,
                    thought=f"suggest a fix for {len(bad)} failing result(s)",
                    fact=f"the kernel marks {len(bad)} result(s) not valid; "
                         f"review() found {len(sugg)} suggestion(s) from checks "
                         f"that actually ran",
                    action=f"review: {s0.get('title') or s0.get('id', 'suggestion')}",
                    outcome=str(s0.get("why") or s0.get("detail") or "")[:160]))
                break

        # 3. the kernel has nothing to justify, but the goal asks for RTL the
        #    spec grammar cannot express. This is the one step a local model is
        #    allowed to contribute, and it is opt-in: without `draft` the loop
        #    behaves exactly as before.
        if draft and not unresolved and not bad and not run.drafted:
            step = _draft_step(n, goal, root, apply)
            if step is not None:
                run.steps.append(step)
                run.drafted = True
                # the reason must describe what actually happened: no model, a
                # model that failed, or a draft that compiled
                # most specific reason first: a missing model or an unanswered
                # call is not "you forgot --apply"
                if "no local model is configured" in step.fact:
                    run.reason = ("the goal needs RTL the spec grammar cannot "
                                  "express, and no local model is configured")
                elif "unavailable" in step.outcome:
                    run.reason = f"the local model did not answer: {step.outcome}"
                elif not apply:
                    run.reason = ("the model drafted a block and the diff is "
                                  "shown; nothing was written and nothing was "
                                  "compiled — re-run with --apply")
                elif "[unchecked]" in step.outcome:
                    run.reason = ("the model drafted a block but it could not be "
                                  "compiled here — install iverilog and re-run "
                                  "before trusting it")
                elif step.ok:
                    run.done = True
                    run.reason = ("the model drafted a block and it compiles; "
                                  "compiling is not verifying — simulate it with "
                                  "`vibe` before trusting it")
                else:
                    run.reason = ("the model drafted a block and it did NOT "
                                  "compile; the error above is the model's, not "
                                  "the kernel's")
                return run

        # 3b. nothing failing, nothing missing
        if not unresolved and not bad:
            run.done = True
            run.reason = (f"nothing left that can be justified: "
                          f"{len(blocks)} block(s) resolved, no result invalidated")
            return run

        # 4. there is a problem but no justified action for it
        if bad:
            run.reason = (f"{len(bad)} result(s) are not valid and no "
                          f"kernel-justified action settles them — re-run the "
                          f"check, or ask the kernel why: `verdicts`")
        else:
            run.reason = ("problems remain but none of them has a "
                          "kernel-justified action — stopping rather than "
                          "inventing one")
        return run

    if not run.reason:
        run.reason = f"reached the {max_steps}-step limit"
    return run


def _draft_step(n: int, goal: str, root: str, apply: bool):
    """Ask the local model for RTL, then compile it. Never call it verified.

    The fact this step rests on is real: the kernel found nothing left to
    justify, and the goal asks for something the spec grammar cannot express.
    Everything after that is the model's, and the only thing reported as a fact
    is whether the result compiles.
    """
    try:
        from .llm import LLMUnavailable, from_env
    except Exception:                                            # noqa: BLE001
        return None
    model = from_env()
    if model is None:
        return Step(n=n, thought="draft the block the goal asks for",
                    fact="the kernel has nothing left to justify, and no local "
                         "model is configured",
                    action="none", ok=False,
                    outcome="set WENGOLD_LLM_MODEL to let a model draft; "
                            "`wengold doctor --llm` checks it")
    try:
        rtl = model.draft_rtl(goal)
    except LLMUnavailable as e:
        return Step(n=n, thought="draft the block the goal asks for",
                    fact="the kernel has nothing left to justify",
                    action=f"draft_rtl via {model.model}", ok=False,
                    outcome=f"model unavailable: {e}")

    # strip a markdown fence if the model wrapped the code
    body = rtl.strip()
    if body.startswith("```"):
        body = "\n".join(body.splitlines()[1:])
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    name = _module_name(body) or "drafted"
    path = Path(root) / f"{name}.sv"

    if not apply:
        return Step(n=n, thought="draft the block the goal asks for",
                    fact=f"the kernel has nothing left to justify; the goal asks "
                         f"for RTL the spec grammar cannot express",
                    action=f"draft_rtl via {model.model} -> {path.name}",
                    ok=True, outcome="diff shown, not written",
                    diff=f"--- a/{path.name}\n+++ b/{path.name}\n"
                         + "".join(f"+{ln}\n" for ln in body.splitlines()))

    if path.exists():
        return Step(n=n, thought="draft the block the goal asks for",
                    fact=f"the kernel has nothing left to justify",
                    action=f"draft_rtl via {model.model} -> {path.name}",
                    ok=False,
                    outcome=(f"{path.name} already exists — refusing to overwrite "
                             f"a design file with model output. Move it, or draft "
                             f"under a different name."))

    try:
        path.write_text(body)
    except OSError as e:
        return Step(n=n, thought="draft the block", fact="kernel has nothing left",
                    action="write", ok=False, outcome=f"could not write: {e}")

    # the only claim this loop makes about model output: does it compile?
    status, detail = _compiles(path)
    return Step(n=n, thought="draft the block the goal asks for",
                fact=f"the kernel has nothing left to justify; the goal asks for "
                     f"RTL the spec grammar cannot express",
                action=f"draft_rtl via {model.model} -> {path.name}",
                ok=(status == "ok"),
                outcome=f"written to {path.name}; {detail} [{status}]")


def _module_name(rtl: str) -> str:
    import re
    m = re.search(r"\bmodule\s+([A-Za-z_]\w*)", rtl)
    return m.group(1) if m else ""


def _compiles(path: Path) -> tuple[str, str]:
    """Does it compile? The only fact this loop can establish about model output.

    Three states, not two: `ok`, `failed`, and `unchecked` when there is no
    compiler. Collapsing "no iverilog" into "did not compile" would blame the
    model for the environment.
    """
    import shutil
    import subprocess
    iv = shutil.which("iverilog")
    if not iv:
        return "unchecked", ("iverilog is not on PATH, so the draft is UNCHECKED "
                             "— it has not been compiled or simulated")
    r = subprocess.run([iv, "-o", os.devnull, str(path)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        return "ok", "compiles. That is not verification — simulate it with `vibe`"
    first = (r.stderr or r.stdout).strip().splitlines()
    return "failed", "does not compile: " + (first[0] if first else "unknown error")


def render(run: CodingRun) -> str:
    return run.render()
