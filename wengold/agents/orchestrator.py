"""The agent orchestrator.

Agents propose; the kernel and the tools decide. On every change the orchestrator
asks the kernel what is still valid, then drives only the minimum set of new
checks — running the tools, recording evidence, investigating failures and
proposing repairs — inside the limits the team sets. Engineers keep signoff.

`run_loop()` is a complete verification loop: classify -> plan -> run -> record
evidence -> diagnose -> propose -> re-check, bounded by `max_iters`. It stops
when everything it re-ran passes, or when an iteration makes no progress (a
missing tool or a stuck failure), and reports exactly what is left unsettled.
"""
from __future__ import annotations

from ..graph.model import DesignGraph
from ..kernel.minimize import minimum_new_evidence
from ..kernel.validity import Result, classify_all
from ..ledger.evidence import make_evidence
from ..ledger.repro import RunSpec
from ..ledger.store import Ledger
from ..tools.adapters.cocotb import CocotbAdapter
from ..tools.adapters.symbiyosys import SymbiYosysAdapter
from ..tools.outcome import Outcome, ToolOutcome
from .debugger import Debugger
from .planner import Planner
from .repair import Repairer
from .testgen import TestGen


class Orchestrator:
    def __init__(self, graph: DesignGraph, ledger: Ledger, llm=None,
                 workdir: str | None = None) -> None:
        self.graph = graph
        self.ledger = ledger
        self.llm = llm
        self.workdir = workdir or "/tmp/wengold-run"
        self.planner = Planner(llm)
        self.testgen = TestGen(llm)
        self.debugger = Debugger(llm)
        self.repairer = Repairer(llm)

    # ---- default (honest) runner: real tools, else tool_missing -------
    def default_runner(self):
        cocotb = CocotbAdapter()
        sby = SymbiYosysAdapter()

        def run(result_id: str, kind: str) -> Outcome:
            if kind in ("sim", "coverage"):
                if not cocotb.available():
                    return Outcome("cocotb", "run", ToolOutcome.TOOL_MISSING)
                return cocotb.run(workdir=self.workdir, toplevel=result_id)
            if kind == "formal":
                if not sby.available():
                    return Outcome("symbiyosys", "prove", ToolOutcome.TOOL_MISSING)
                return sby.prove(f"{result_id}.sby", cwd=self.workdir)
            return Outcome(kind, "run", ToolOutcome.TOOL_MISSING)

        return run

    # ---- the loop ------------------------------------------------------
    def run_loop(self, changed: set[str], prior: list[Result], runner=None,
                 result_deps: dict[str, set[str]] | None = None,
                 max_iters: int = 3) -> dict:
        runner = runner or self.default_runner()
        by_id = {r.id: r for r in prior}
        self.ledger.append("loop_start", {"changed": sorted(changed), "results": sorted(by_id)})
        iterations: list[dict] = []
        unsettled: dict[str, dict] = {}
        prev_unsettled: set[str] = set()

        for it in range(max_iters):
            classes = classify_all(self.graph, prior, changed)
            for c in classes:
                self.ledger.append("verdict", {"iter": it, "result": c.result.id,
                                               "verdict": c.verdict.value, "reason": c.reason})
            todo = minimum_new_evidence(self.graph, classes, result_deps)
            iterations.append({"iter": it, "todo": todo,
                               "verdicts": {c.result.id: c.verdict.value for c in classes}})
            if not todo:
                unsettled = {}
                break

            outcomes: dict[str, dict] = {}
            for rid in todo:
                result = by_id.get(rid)
                out = runner(rid, result.kind if result else "sim")
                d = out.as_dict() if isinstance(out, Outcome) else dict(out)
                outcomes[rid] = d
                self.ledger.append("run", {"iter": it, "result": rid, "tool": d.get("tool"),
                                           "outcome": d.get("outcome"), "rc": d.get("rc")})
                if isinstance(out, Outcome):
                    ev = make_evidence(
                        claim=f"{rid}:{d.get('outcome')}", tool=d.get("tool") or "unknown",
                        artifact_text=out.log,
                        run=RunSpec.make(d.get("tool") or "unknown",
                                         argv=d.get("spec", {}).get("argv", [])),
                        meta={"result": rid})
                    self.ledger.append("evidence", {"iter": it, "result": rid,
                                                    "repro": ev.repro, "digest": ev.digest})
                if d.get("outcome") == "fail":
                    diag = self.debugger.investigate(d)
                    prop = self.repairer.propose({**d, **diag})
                    self.ledger.append("diagnosis", {"iter": it, "result": rid, **diag})
                    self.ledger.append("repair", {"iter": it, "result": rid, **prop})

            # fold outcomes back into the results
            for rid, d in outcomes.items():
                r = by_id.get(rid)
                if r is not None:
                    r.status = {"pass": "pass", "fail": "fail"}.get(d.get("outcome"), "unknown")
            unsettled = {rid: d for rid, d in outcomes.items() if d.get("outcome") != "pass"}

            if not unsettled:
                break
            if set(unsettled) == prev_unsettled:
                break                     # no progress; stop and report
            prev_unsettled = set(unsettled)

        report = {
            "iterations": iterations,
            "rerun": iterations[-1]["todo"] if iterations else [],
            "unsettled": sorted(unsettled),
            "failures": sorted(r for r, d in unsettled.items() if d.get("outcome") == "fail"),
            "settled": not unsettled,
        }
        self.ledger.append("loop_end", {"settled": report["settled"],
                                        "unsettled": report["unsettled"]})
        return report

    # ---- single-shot API (kept for callers that only want the answer) --
    def on_change(self, changed: set[str], prior: list[Result],
                  result_deps: dict[str, set[str]] | None = None) -> dict:
        self.ledger.append("change", {"nodes": sorted(changed)})
        classes = classify_all(self.graph, prior, changed)
        for c in classes:
            self.ledger.append("verdict", {"result": c.result.id,
                                           "verdict": c.verdict.value, "reason": c.reason})
        todo = minimum_new_evidence(self.graph, classes, result_deps)
        plan = self.planner.plan(self.graph, todo, {r.id: r for r in prior})
        return {"classification": {c.result.id: c.verdict.value for c in classes},
                "reverify": todo, "plan": plan}
