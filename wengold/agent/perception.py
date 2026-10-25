"""Perception: build the context the rest of the agent reasons over.

An agent is only as good as what it can see. This stage collects, from the real
sources rather than from a prompt:

* the **graph** — its completeness, how many nodes are unresolved and which;
* the **ledger's** view of prior results — what each result consumed, and what it
  consumed *other results*;
* the **tools** — which of the adapters are actually installed, so a plan never
  proposes a check the machine cannot run;
* the **classification** — which prior results survive the change, which are
  invalidated, and which are unknown.

The distinction that matters: `unknown` is not `invalidated`. A result with no
recorded dependencies cannot be shown unaffected, and the context says so rather
than folding it into "needs a rerun" and losing the reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.minimize import minimum_new_evidence
from ..kernel.validity import Verdict, classify_all, completeness_report

__all__ = ["Context", "perceive"]


@dataclass
class Context:
    """Everything the agent knows before it plans anything."""

    changed: set[str]
    results: dict                       # id -> Result
    verdicts: dict                      # id -> Verdict
    reasons: dict                       # id -> str (why it has that verdict)
    todo: list[str]                     # the minimum new evidence
    complete: bool
    unresolved: list[str]
    unresolved_count: int
    approximate: bool = False    # graph built without a full elaboration
    tools: dict = field(default_factory=dict)     # name -> available?
    dependents: dict = field(default_factory=dict)  # result -> results that use it
    notes: list[str] = field(default_factory=list)

    @property
    def settled(self) -> bool:
        return not self.todo

    def by_verdict(self, verdict: Verdict) -> list[str]:
        return [r for r, v in self.verdicts.items() if v is verdict]

    def summary(self) -> str:
        inv = len(self.by_verdict(Verdict.INVALIDATED))
        unk = len(self.by_verdict(Verdict.UNKNOWN))
        val = len(self.by_verdict(Verdict.VALID))
        return (f"{len(self.results)} results: {val} valid, {inv} invalidated, "
                f"{unk} unknown; {len(self.todo)} need new evidence; "
                f"graph complete={self.complete}, "
                f"{self.unresolved_count} unresolved")


def _probe_tools(names) -> dict:
    """Ask the adapters themselves whether they are installed."""
    out = {}
    for name in names:
        try:
            if name == "cocotb":
                from ..tools.adapters.cocotb import CocotbAdapter
                out[name] = CocotbAdapter().available()
            elif name == "symbiyosys":
                from ..tools.adapters.symbiyosys import SymbiYosysAdapter
                out[name] = SymbiYosysAdapter().available()
            else:
                from ..tools.registry import all_tools
                spec = next((t for t in all_tools() if t.name == name), None)
                out[name] = bool(spec and getattr(spec, "installed", False))
        except Exception:
            out[name] = False
    return out


def perceive(graph, results, changed, tool_names=("cocotb", "symbiyosys")) -> Context:
    """Assemble the context. No model, no guessing — all of this is read."""
    by_id = {r.id: r for r in results}
    classes = classify_all(graph, results, set(changed))
    verdicts = {c.result.id: c.verdict for c in classes}
    reasons = {c.result.id: c.reason for c in classes}
    todo = minimum_new_evidence(graph, classes)

    # which results other results rest on — the ordering signal for planning
    dependents: dict[str, set[str]] = {}
    for r in results:
        for dep in getattr(r, "depends_on_results", set()) or set():
            dependents.setdefault(dep, set()).add(r.id)

    report = completeness_report(graph)
    unresolved = [n for n in (report.get("unresolved") or [])]
    ctx = Context(
        changed=set(changed), results=by_id, verdicts=verdicts, reasons=reasons,
        todo=todo, complete=bool(report.get("complete")),
        unresolved=unresolved, unresolved_count=len(unresolved),
        approximate=bool(getattr(graph, "approximate", False)),
        tools=_probe_tools(tool_names),
        dependents={k: set(v) for k, v in dependents.items()},
    )
    if not ctx.complete:
        ctx.notes.append(
            f"graph is incomplete: {ctx.unresolved_count} node(s) unresolved, so "
            f"anything downstream of them stays unknown whatever we run")
    missing = [t for t, ok in ctx.tools.items() if not ok]
    if missing:
        ctx.notes.append(
            f"not installed: {', '.join(missing)} — a plan must not rely on them")
    return ctx
