"""Human-reviewed RTL repair proposal agent and guarded candidate-copy approval.

Proposal generation is read-only. Approval writes a new candidate file under
results/approved_repairs; it never overwrites the original RTL.
"""
from __future__ import annotations

import difflib
import hashlib
import os
from pathlib import Path

from ..agents.repair import Repairer
from .orchestration import AgentReport, AgentStatus, AgentTask


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
            "candidate_text": candidate,
            "source_unchanged": True,
            "source_sha256": _sha256(original),
            "candidate_sha256": _sha256(candidate),
            "verification_status": "NOT_RUN",
        }
        return AgentReport(
            self.task.agent_id, AgentStatus.PASS,
            outputs={"repair_proposal:" + self.rtl_rel: payload},
            findings=("proposal generated in memory only; no RTL file was modified; review and re-run verification",),
        )


def approve_candidate_copy(
    project_root: str | Path,
    payload: dict,
    *,
    approved: bool = False,
    expected_source_sha256: str | None = None,
    expected_candidate_sha256: str | None = None,
) -> dict:
    """Write an approved candidate to a new path, with hash and no-overwrite guards.

    The original RTL is never modified. A second approval cannot overwrite an
    existing candidate file; the caller must choose a new reviewed destination
    in a later workflow rather than silently replacing evidence.
    """
    if approved is not True:
        raise PermissionError("explicit engineer approval is required")
    root = Path(project_root).resolve()
    rtl_rel = payload.get("rtl_file")
    if not isinstance(rtl_rel, str) or not rtl_rel:
        raise ValueError("proposal is missing rtl_file")
    source = (root / rtl_rel).resolve()
    if (not source.is_relative_to(root) or source.suffix.lower() not in {".sv", ".v"}
            or not source.is_file()):
        raise ValueError("proposal source must be an existing project-local .sv/.v file")
    source_text = source.read_text(encoding="utf-8")
    source_hash = _sha256(source_text)
    candidate = payload.get("candidate_text")
    if not isinstance(candidate, str):
        raise ValueError("proposal does not contain candidate text")
    candidate_hash = _sha256(candidate)
    if expected_source_sha256 != payload.get("source_sha256") or source_hash != payload.get("source_sha256"):
        raise RuntimeError("source RTL changed since proposal generation; regenerate the proposal")
    if expected_candidate_sha256 != payload.get("candidate_sha256") or candidate_hash != payload.get("candidate_sha256"):
        raise RuntimeError("candidate hash mismatch; proposal may have been altered")

    candidate_root = root / "results" / "approved_repairs"
    candidate_root.mkdir(parents=True, exist_ok=True)
    destination = candidate_root / rtl_rel
    resolved_destination = destination.resolve()
    if not resolved_destination.is_relative_to(candidate_root.resolve()):
        raise ValueError("candidate destination escapes approved_repairs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.parent.resolve().is_relative_to(candidate_root.resolve()):
        raise ValueError("candidate destination parent escapes approved_repairs")

    # O_EXCL prevents accidental replacement, including a race between checks.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(destination), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            destination.unlink()
        except OSError:
            pass
        raise
    return {
        "status": "approved_candidate_copy_written",
        "candidate_path": str(destination.relative_to(root)),
        "source_path": rtl_rel,
        "source_sha256": source_hash,
        "candidate_sha256": candidate_hash,
        "source_unchanged": source.read_text(encoding="utf-8") == source_text,
        "verification_status": "NOT_RUN",
        "next_step": "review candidate copy, then run fresh syntax, simulation, formal and coverage checks",
    }
