"""Run reviewed project manifests as real Loop & Stitch verification agents.

This is the bridge from orchestration to WENGOLD's existing EDA manifest
runner. It never runs LLM-generated commands and never treats a missing tool,
timeout, stale/missing artifact, or non-simulation flow as PASS.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ..dv_pipeline import run_regression
from ..eda_flows import inspect_manifest
from ..ledger.store import Ledger
from .orchestration import (
    AgentReport, AgentStatus, AgentTask, LoopPolicy,
    LoopStitchCoordinator, LoopStitchResult,
)

_ALLOWED_KINDS = {"simulation", "uvm", "rustdv_sim", "pss"}


class ReviewedManifestAgent:
    """A single explicitly selected, project-local regression manifest."""

    def __init__(self, project_root: str | Path, manifest_rel: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.manifest_rel = manifest_rel
        self.task = AgentTask("manifest:" + manifest_rel)

    def execute(self, context) -> AgentReport:
        try:
            manifest = inspect_manifest(self.project_root, self.manifest_rel)
        except RuntimeError as exc:
            return AgentReport(
                self.task.agent_id, AgentStatus.BLOCKED,
                findings=(str(exc),), retryable=False,
            )
        except (OSError, ValueError) as exc:
            return AgentReport(
                self.task.agent_id, AgentStatus.ERROR,
                findings=(f"{type(exc).__name__}: {exc}",), retryable=False,
            )

        if manifest["kind"] not in _ALLOWED_KINDS:
            return AgentReport(
                self.task.agent_id, AgentStatus.BLOCKED,
                findings=(f"flow kind {manifest['kind']!r} is not a regression agent; "
                          f"allowed: {sorted(_ALLOWED_KINDS)}",),
                retryable=False,
            )

        result = run_regression(self.project_root, self.manifest_rel)
        status = result.get("status")
        if result.get("ok") is True and result.get("gate") == "tool_evidence_present":
            artifacts = tuple(sorted(result.get("artifacts_sha256", {}).keys()))
            return AgentReport(
                self.task.agent_id, AgentStatus.PASS,
                outputs={"manifest:" + self.manifest_rel: result},
                findings=(result.get("note", "real tool run and declared artifacts verified"),),
                evidence_refs=artifacts,
            )
        if status in ("tool_unavailable",):
            agent_status = AgentStatus.BLOCKED
        elif status in ("tool_failed",):
            agent_status = AgentStatus.FAIL
        else:
            # Includes timeout, missing/stale evidence, changed inputs and
            # other non-settled conditions. Never retry identical inputs blindly.
            agent_status = AgentStatus.INCONCLUSIVE
        return AgentReport(
            self.task.agent_id, agent_status,
            findings=(f"manifest {self.manifest_rel}: {status}; "
                      f"exit_code={result.get('exit_code')}; "
                      f"missing={result.get('missing_artifacts', [])}; "
                      f"stale={result.get('stale_artifacts', [])}",),
            evidence_refs=tuple(sorted(result.get("artifacts_sha256", {}).keys())),
            retryable=False,
        )


def run_reviewed_manifests(
    project_root: str | Path,
    manifests: Iterable[str],
    *,
    ledger_path: str = "results/loop-stitch-ledger.jsonl",
) -> LoopStitchResult:
    """Execute selected reviewed regression manifests through Loop & Stitch.

    Each manifest is an independently selectable agent. The current version
    runs each manifest once: retrying an unchanged failing test would add no
    information. A future repair agent must change and re-fingerprint inputs
    before the coordinator may safely schedule a retry.
    """
    root = Path(project_root).resolve()
    selected = tuple(dict.fromkeys(str(item).strip() for item in manifests if str(item).strip()))
    if not selected:
        raise ValueError("select at least one reviewed regression manifest")
    if len(selected) > 20:
        raise ValueError("at most 20 regression manifests may be run in one orchestration")
    agents = [ReviewedManifestAgent(root, item) for item in selected]

    ledger_file = (root / ledger_path).resolve()
    if not ledger_file.is_relative_to(root):
        raise ValueError("ledger path must remain inside the project")
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(ledger_file)
    required = tuple("manifest:" + item for item in selected)
    return LoopStitchCoordinator().run(
        agents,
        context={"project_root": str(root), "execution_mode": "reviewed_manifest"},
        policy=LoopPolicy(max_iterations=1),
        required_outputs=required,
        ledger=ledger,
    )
