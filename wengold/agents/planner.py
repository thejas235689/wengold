"""Planner: decides where to look and which checks settle each open result."""
from __future__ import annotations

from ..graph.model import DesignGraph


class Planner:
    def __init__(self, llm=None) -> None:
        self.llm = llm

    def plan(self, graph: DesignGraph, todo: list[str]) -> list[dict]:
        # A real planner asks the model to choose tools and order, bounded by
        # the team's limits. Deterministic fallback: one check per open result.
        return [{"result": r, "action": "run", "tool": None} for r in todo]
