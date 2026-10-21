"""A generic adapter for tools driven as subprocesses.

Used for commercial tools (VCS, Xcelium, Questa, JasperGold, ...) and for flow
tools (Git, Jira, Slack). Absent binaries are reported as `tool_missing` — never
as a pass; a timeout or crash is reported as such, never as a check failure.
"""
from __future__ import annotations

import shutil

from ..base import ToolSpec
from ..outcome import Outcome, run_tool


class GenericAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    def available(self) -> bool:
        return self.spec.binary is not None and shutil.which(self.spec.binary) is not None

    def run(self, args: list[str], cwd: str | None = None, timeout: float = 600.0,
            env: dict | None = None, interpret=None, collect: list[str] | None = None) -> Outcome:
        return run_tool(self.spec.binary, list(args), tool=self.spec.key,
                        action=self.spec.role, timeout=timeout, cwd=cwd, env=env,
                        interpret=interpret, collect=collect)
