"""Bounded multi-agent Loop & Stitch orchestration.

Agents propose work and return structured results. Only real tool adapters
produce verification verdicts; this layer coordinates them and records events.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from ..ledger.store import Ledger


class AgentStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    INCONCLUSIVE = "inconclusive"
    BLOCKED = "blocked"


class RunStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class AgentTask:
    agent_id: str
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentReport:
    agent_id: str
    status: AgentStatus
    outputs: Mapping[str, Any] = field(default_factory=dict)
    findings: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    retryable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "status": self.status.value,
            "outputs": dict(self.outputs),
            "findings": list(self.findings),
            "evidence_refs": list(self.evidence_refs),
            "retryable": self.retryable,
        }


class VerificationAgent(Protocol):
    """An agent adapter. It must return a structured report, not prose-only."""

    task: AgentTask

    def execute(self, context: Mapping[str, Any]) -> AgentReport: ...


@dataclass(frozen=True)
class LoopPolicy:
    max_iterations: int = 3
    stop_on_non_retryable_failure: bool = True

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")


@dataclass(frozen=True)
class StitchResult:
    outputs: Mapping[str, Any]
    conflicts: Mapping[str, tuple[tuple[str, Any], ...]]
    missing_required: tuple[str, ...]

    @property
    def consistent(self) -> bool:
        return not self.conflicts and not self.missing_required

    def as_dict(self) -> dict[str, Any]:
        return {
            "outputs": dict(self.outputs),
            "conflicts": {
                key: [{"agent_id": agent, "value": value} for agent, value in values]
                for key, values in self.conflicts.items()
            },
            "missing_required": list(self.missing_required),
            "consistent": self.consistent,
        }


class Stitcher:
    """Merge independent agent outputs without silently choosing a winner."""

    def stitch(
        self,
        reports: list[AgentReport],
        *,
        required_keys: tuple[str, ...] = (),
        resolutions: Mapping[str, str] | None = None,
    ) -> StitchResult:
        resolutions = resolutions or {}
        candidates: dict[str, list[tuple[str, Any]]] = {}
        for report in sorted(reports, key=lambda item: item.agent_id):
            if report.status is not AgentStatus.PASS:
                continue
            for key, value in report.outputs.items():
                candidates.setdefault(key, []).append((report.agent_id, value))

        merged: dict[str, Any] = {}
        conflicts: dict[str, tuple[tuple[str, Any], ...]] = {}
        for key, values in sorted(candidates.items()):
            distinct = []
            for item in values:
                if not any(item[1] == prior[1] for prior in distinct):
                    distinct.append(item)
            if len(distinct) == 1:
                merged[key] = distinct[0][1]
                continue
            chosen_agent = resolutions.get(key)
            chosen = [value for agent, value in values if agent == chosen_agent]
            if chosen_agent is not None and chosen:
                merged[key] = chosen[0]
            else:
                conflicts[key] = tuple(values)

        missing = tuple(sorted(key for key in required_keys if key not in merged))
        return StitchResult(merged, conflicts, missing)


@dataclass
class LoopStitchResult:
    status: RunStatus
    iterations: int
    reports: list[AgentReport]
    stitch: StitchResult
    history: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "iterations": self.iterations,
            "reports": [report.as_dict() for report in self.reports],
            "stitch": self.stitch.as_dict(),
            "history": self.history,
            "claim": "orchestration_result_not_automatic_signoff",
        }


class LoopStitchCoordinator:
    """Run dependency-ordered agents in bounded feedback loops, then stitch."""

    def __init__(self, stitcher: Stitcher | None = None) -> None:
        self.stitcher = stitcher or Stitcher()

    def run(
        self,
        agents: list[VerificationAgent],
        *,
        context: Mapping[str, Any] | None = None,
        policy: LoopPolicy | None = None,
        required_outputs: tuple[str, ...] = (),
        resolutions: Mapping[str, str] | None = None,
        ledger: Ledger | None = None,
    ) -> LoopStitchResult:
        policy = policy or LoopPolicy()
        ordered = self._order_agents(agents)
        base_context = dict(context or {})
        history: list[dict[str, Any]] = []
        final_reports: list[AgentReport] = []
        final_stitch = StitchResult({}, {}, tuple(sorted(required_outputs)))
        status = RunStatus.INCOMPLETE

        for iteration in range(1, policy.max_iterations + 1):
            reports: list[AgentReport] = []
            passed: set[str] = set()
            iteration_context = dict(base_context)
            for agent in ordered:
                task = agent.task
                failed_deps = [dep for dep in task.depends_on if dep not in passed]
                if failed_deps:
                    report = AgentReport(
                        task.agent_id, AgentStatus.BLOCKED,
                        findings=("blocked by dependencies: " + ", ".join(failed_deps),),
                    )
                else:
                    report = agent.execute(dict(iteration_context))
                    if report.agent_id != task.agent_id:
                        raise ValueError(
                            f"agent {task.agent_id!r} returned report for {report.agent_id!r}"
                        )
                    if report.status is AgentStatus.PASS:
                        passed.add(task.agent_id)
                        iteration_context.update(report.outputs)
                reports.append(report)

            stitch = self.stitcher.stitch(
                reports, required_keys=required_outputs, resolutions=resolutions
            )
            all_passed = all(r.status is AgentStatus.PASS for r in reports)
            if all_passed and stitch.consistent:
                status = RunStatus.PASS
            elif any(r.status is AgentStatus.FAIL for r in reports):
                retryable = any(r.status is AgentStatus.FAIL and r.retryable for r in reports)
                status = RunStatus.INCOMPLETE if retryable else RunStatus.FAIL
            else:
                status = RunStatus.BLOCKED if any(
                    r.status in (AgentStatus.ERROR, AgentStatus.BLOCKED)
                    for r in reports
                ) or not stitch.consistent else RunStatus.INCOMPLETE

            entry = {
                "iteration": iteration,
                "reports": [r.as_dict() for r in reports],
                "stitch": stitch.as_dict(),
                "status": status.value,
            }
            history.append(entry)
            if ledger is not None:
                ledger.append("loop_stitch_iteration", entry)

            final_reports, final_stitch = reports, stitch
            if status is RunStatus.PASS:
                break
            if status in (RunStatus.FAIL, RunStatus.BLOCKED):
                break
            if policy.stop_on_non_retryable_failure and any(
                r.status is AgentStatus.FAIL and not r.retryable for r in reports
            ):
                status = RunStatus.FAIL
                break

        result = LoopStitchResult(status, len(history), final_reports, final_stitch, history)
        if ledger is not None:
            ledger.append("loop_stitch_result", result.as_dict())
        return result

    @staticmethod
    def _order_agents(agents: list[VerificationAgent]) -> list[VerificationAgent]:
        by_id = {agent.task.agent_id: agent for agent in agents}
        if len(by_id) != len(agents):
            raise ValueError("agent IDs must be unique")
        for agent in agents:
            unknown = set(agent.task.depends_on) - set(by_id)
            if unknown:
                raise ValueError(
                    f"agent {agent.task.agent_id!r} has unknown dependencies: {sorted(unknown)}"
                )

        ordered: list[VerificationAgent] = []
        remaining = dict(by_id)
        while remaining:
            ready = sorted(
                agent_id for agent_id, agent in remaining.items()
                if set(agent.task.depends_on).issubset(
                    {item.task.agent_id for item in ordered}
                )
            )
            if not ready:
                raise ValueError("agent dependency graph contains a cycle")
            for agent_id in ready:
                ordered.append(remaining.pop(agent_id))
        return ordered
