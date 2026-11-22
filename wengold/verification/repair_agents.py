"""Human-reviewed RTL repair proposal agent.

It creates a unified diff in memory. It never writes or overwrites RTL. The
engineer must inspect and apply the patch separately, then run fresh tools.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from ..agents.repair import Repairer
from .orchestration import AgentReport, AgentStatus, AgentTask


class RepairProposalAgent:
    def __init__(self, project_root: str | Path, rtl_rel: str,
                 failure: dict, *, repairer: Repairer | None = None) -> None:
        self.project_root = Path(project_root).resolve()
        self.rtl_rel = rtl_rel
        self.failure = dict(failure)
        self.repairer = repairer or Repairer()
        self.task = AgentTask("repair-proposal:" + rtl_rel)

    def execute(self, context) -> AgentReport:
        path = (self.project_root / self.rtl_rel).resolve()
        if (not path.is_relative_to(self.project_root) or
                path.suffix.lower() not in {".sv", ".v"} or not path.is_file()):
            return AgentReport(self.task.agent_id, AgentStatus.BLOCKED,
                               findings=("RTL path must be an existing project-local .sv/.v file",))
        if path.stat().st_size > 220_000:
            return AgentReport(self.task.agent_id, AgentStatus.BLOCKED,
                               findings=("RTL file exceeds 220 KB proposal limit",))
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return AgentReport(self.task.agent_id, AgentStatus.ERROR,
                               findings=(f"{type(exc).__name__}: {exc}",))
        proposal = self.repairer.propose(self.failure)
        candidate = self.repairer.apply(original, dict(proposal))
        diff = "".join(difflib.unified_diff(
            original.splitlines(keepends=True),
            candidate.splitlines(keepends=True),
            fromfile=self.rtl_rel, tofile=self.rtl_rel + ".proposal",
        ))
        payload = {
            "status": "proposal_only_requires_engineer_approval",
            "rtl_file": self.rtl_rel,
            "proposal": proposal,
            "diff": diff,
            "source_unchanged": True,
            "source_sha256": __import__("hashlib").sha256(original.encode()).hexdigest(),
            "candidate_sha256": __import__("hashlib").sha256(candidate.encode()).hexdigest(),
            "verification_status": "NOT_RUN",
        }
        return AgentReport(
            self.task.agent_id, AgentStatus.PASS,
            outputs={"repair_proposal:" + self.rtl_rel: payload},
            findings=("proposal generated in memory only; no RTL file was modified; review and re-run verification",),
        )
