"""Planner: decides what to re-establish and which tool settles each open result.

A real planner asks the model to choose tools and order inside the team's limits;
the deterministic default maps a result's kind to the tool that can settle it,
so the loop runs with no model in the path.
"""
from __future__ import annotations

from ..graph.model import DesignGraph

_TOOL_FOR_KIND = {
    "sim": "cocotb",
    "coverage": "verilator",
    "formal": "symbiyosys",
    "cdc": "verilator",
    "lint": "verilator",
    "synth": "yosys",
}


class Planner:
    def __init__(self, llm=None) -> None:
        self.llm = llm

    def tool_for(self, kind: str) -> str | None:
        return _TOOL_FOR_KIND.get(kind)

    def plan(self, graph: DesignGraph, todo: list[str],
             results: dict | None = None) -> list[dict]:
        results = results or {}
        plan = []
        for rid in todo:
            kind = getattr(results.get(rid), "kind", None) or "sim"
            plan.append({"result": rid, "action": "run", "tool": self.tool_for(kind)})
        return plan
