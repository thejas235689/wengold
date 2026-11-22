"""Conservative lean-regression planning over WENGOLD's existing validity kernel."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..graph.model import DesignGraph
from ..kernel.minimize import minimum_new_evidence
from ..kernel.validity import Classification, Result, Verdict, classify_all


class PlanAction(str, Enum):
    REESTABLISH = "reestablish"
    RETAIN_CURRENT = "retain_current"


@dataclass(frozen=True)
class PlanItem:
    result_id: str
    action: PlanAction
    reason: str
    verdict: Verdict


@dataclass
class LeanPlan:
    changed_nodes: tuple[str, ...]
    items: list[PlanItem] = field(default_factory=list)
    graph_complete: bool = False

    @property
    def reestablish(self) -> list[str]:
        return [item.result_id for item in self.items
                if item.action is PlanAction.REESTABLISH]

    @property
    def retained_current(self) -> list[str]:
        return [item.result_id for item in self.items
                if item.action is PlanAction.RETAIN_CURRENT]

    def as_dict(self) -> dict:
        return {
            "changed_nodes": list(self.changed_nodes),
            "graph_complete": self.graph_complete,
            "reestablish": self.reestablish,
            "retained_current": self.retained_current,
            "items": [
                {"result_id": item.result_id, "action": item.action.value,
                 "reason": item.reason, "verdict": item.verdict.value}
                for item in self.items
            ],
            "claim": "planning_only_not_execution_or_signoff",
        }


class LeanPlanner:
    """Plan the minimum re-establishment set without weakening kernel rules.

    The planner delegates currency classification and downstream closure to the
    existing validity kernel. A result is retained only when the kernel classifies
    it VALID and it is not downstream of another result selected for rerun.
    This class does not execute tests or assert that a design is verified.
    """

    def plan(self, graph: DesignGraph, results: list[Result],
             changed_nodes: set[str],
             result_dependencies: dict[str, set[str]] | None = None) -> LeanPlan:
        ids = [result.id for result in results]
        if len(ids) != len(set(ids)):
            raise ValueError("result IDs must be unique")

        classifications = classify_all(graph, results, set(changed_nodes))
        rerun_ids = set(minimum_new_evidence(
            graph, classifications, result_deps=result_dependencies))

        by_id = {c.result.id: c for c in classifications}
        items: list[PlanItem] = []
        for result in sorted(results, key=lambda r: r.id):
            classification = by_id[result.id]
            if result.id in rerun_ids:
                reason = classification.reason
                if classification.verdict is Verdict.VALID:
                    reason = "downstream of evidence selected for re-establishment"
                items.append(PlanItem(result.id, PlanAction.REESTABLISH,
                                      reason, classification.verdict))
            else:
                # Only a kernel VALID classification can reach this branch.
                items.append(PlanItem(result.id, PlanAction.RETAIN_CURRENT,
                                      classification.reason, classification.verdict))

        return LeanPlan(
            changed_nodes=tuple(sorted(changed_nodes)),
            items=items,
            graph_complete=graph.completeness()["complete"],
        )
