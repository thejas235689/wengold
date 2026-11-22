"""SymbiYosys proof-aware manifest agent.

A zero exit code is never enough. This adapter requires an explicitly declared
unbounded proof mode and a parsed SBY PASS status plus fresh declared artifacts.
"""
from __future__ import annotations

import configparser
import json
from pathlib import Path

from ..eda_flows import execute_manifest, inspect_manifest
from ..tools.outcome import ToolOutcome, parse_sby_status
from .orchestration import AgentReport, AgentStatus, AgentTask



def _actual_sby_mode(root: Path, argv: list[str]) -> str | None:
    """Read mode from the actual .sby file, not just manifest metadata."""
    candidates = [arg for arg in argv if isinstance(arg, str) and arg.endswith(".sby")]
    if len(candidates) != 1:
        return None
    sby_path = (root / candidates[0]).resolve()
    if not sby_path.is_relative_to(root) or not sby_path.is_file():
        return None
    if sby_path.stat().st_size > 64_000:
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(sby_path.read_text(encoding="utf-8"))
        return parser.get("options", "mode", fallback=None)
    except (OSError, UnicodeDecodeError, configparser.Error):
        return None


class SymbiYosysManifestAgent:
    def __init__(self, project_root: str | Path, manifest_rel: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.manifest_rel = manifest_rel
        self.task = AgentTask("formal:" + manifest_rel)

    def execute(self, context) -> AgentReport:
        try:
            spec = inspect_manifest(self.project_root, self.manifest_rel)
            path = (self.project_root / self.manifest_rel).resolve()
            if not path.is_relative_to(self.project_root):
                raise ValueError("manifest escapes project directory")
            data = json.loads(path.read_text(encoding="utf-8"))
        except RuntimeError as exc:
            return AgentReport(self.task.agent_id, AgentStatus.BLOCKED,
                               findings=(str(exc),))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return AgentReport(self.task.agent_id, AgentStatus.ERROR,
                               findings=(f"{type(exc).__name__}: {exc}",))

        if spec["kind"] != "formal":
            return AgentReport(self.task.agent_id, AgentStatus.BLOCKED,
                               findings=("formal agent requires kind='formal'",))
        if data.get("engine") != "symbiyosys":
            return AgentReport(self.task.agent_id, AgentStatus.BLOCKED,
                               findings=("declare engine='symbiyosys' explicitly",))
        # BMC and cover PASS are not inductive/unbounded proofs.
        declared_mode = data.get("proof_mode")
        actual_mode = _actual_sby_mode(self.project_root, data.get("argv", []))
        if declared_mode != "prove" or actual_mode != "prove":
            return AgentReport(
                self.task.agent_id, AgentStatus.BLOCKED,
                findings=(f"unbounded proof required; declared proof_mode={declared_mode!r}, "
                          f"actual .sby [options] mode={actual_mode!r}; BMC/cover cannot satisfy this proof agent",),
            )
        if not spec["artifacts_expected"]:
            return AgentReport(self.task.agent_id, AgentStatus.BLOCKED,
                               findings=("formal manifest must declare fresh proof artifacts",))

        result = execute_manifest(self.project_root, self.manifest_rel)
        parsed = parse_sby_status(result.get("log", ""))
        common = (
            f"SBY status={parsed.value if parsed else 'unparsed'}; "
            f"execution={result.get('status')}; exit_code={result.get('exit_code')}; "
            f"missing={result.get('missing_artifacts', [])}; "
            f"stale={result.get('stale_artifacts', [])}"
        )
        evidence = tuple(sorted(result.get("artifacts_sha256", {}).keys()))
        if (result.get("ok") is True and parsed is ToolOutcome.PASS and
                result.get("input_unchanged") is True and evidence):
            return AgentReport(
                self.task.agent_id, AgentStatus.PASS,
                outputs={"formal:" + self.manifest_rel: {
                    "status": "symbiyosys_proof_pass",
                    "proof_mode": "prove",
                    "engine": "symbiyosys",
                    "manifest": self.manifest_rel,
                    "inputs_sha256": result.get("inputs_sha256", {}),
                    "artifacts_sha256": result.get("artifacts_sha256", {}),
                    "qualification": "parsed SBY PASS in declared prove mode; engineer signoff still required",
                }},
                findings=(common,), evidence_refs=evidence,
            )
        if parsed is ToolOutcome.FAIL:
            status = AgentStatus.FAIL
        elif parsed is ToolOutcome.PASS:
            # PASS without fresh artifacts or stable inputs is not a proof.
            status = AgentStatus.INCONCLUSIVE
        elif result.get("status") == "tool_unavailable":
            status = AgentStatus.BLOCKED
        elif parsed is ToolOutcome.ERROR:
            status = AgentStatus.ERROR
        else:
            status = AgentStatus.INCONCLUSIVE
        return AgentReport(self.task.agent_id, status, findings=(common,),
                           evidence_refs=evidence, retryable=False)
