"""The agent orchestrator.

Agents propose; the kernel and the tools decide. On every change the
orchestrator asks the kernel what is still valid, then drives only the minimum
set of new checks — generating tests, investigating failures and proposing
repairs inside the limits the team sets. Engineers keep signoff.
"""
from __future__ import annotations

from ..graph.model import DesignGraph
from ..kernel.minimize import minimum_new_evidence
from ..kernel.validity import Result, classify_all
from ..ledger.store import Ledger
from .debugger import Debugger
from .planner import Planner
from .repair import Repairer
from .testgen import TestGen


class Orchestrator:
    def __init__(self, graph: DesignGraph, ledger: Ledger, llm=None) -> None:
        self.graph = graph
        self.ledger = ledger
        self.llm = llm
        self.planner = Planner(llm)
        self.testgen = TestGen(llm)
        self.debugger = Debugger(llm)
        self.repairer = Repairer(llm)

    def on_change(self, changed: set[str], prior: list[Result]) -> dict:
        self.ledger.append("change", {"nodes": sorted(changed)})
        classes = classify_all(self.graph, prior, changed)
        for c in classes:
            self.ledger.append("verdict", {"result": c.result.id,
                                           "verdict": c.verdict.value, "reason": c.reason})
        todo = minimum_new_evidence(self.graph, classes)
        plan = self.planner.plan(self.graph, todo)
        return {"classification": {c.result.id: c.verdict.value for c in classes},
                "reverify": todo, "plan": plan}
