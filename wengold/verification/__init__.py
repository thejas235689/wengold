"""Lean verification planning and orchestration primitives.

This package composes the existing graph, validity kernel and evidence ledger;
it does not create a parallel source of truth.
"""
from .models import RunManifest
from .orchestration import (
    AgentReport, AgentStatus, AgentTask, LoopPolicy, LoopStitchCoordinator,
    LoopStitchResult, RunStatus, StitchResult, Stitcher, VerificationAgent,
)
from .planner import LeanPlan, LeanPlanner, PlanAction, PlanItem

__all__ = [
    "RunManifest", "LeanPlan", "LeanPlanner", "PlanAction", "PlanItem",
    "AgentReport", "AgentStatus", "AgentTask", "LoopPolicy",
    "LoopStitchCoordinator", "LoopStitchResult", "RunStatus",
    "StitchResult", "Stitcher", "VerificationAgent",
]
