"""A generic adapter for tools driven as subprocesses.

Used for commercial tools (VCS, Xcelium, Questa, JasperGold, ...) and for flow
tools (Git, Jira, Slack). Absent binaries are reported as `tool_missing` — never
as a pass.
"""
from __future__ import annotations

import shutil
import subprocess

from ..base import ToolSpec


class GenericAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    def available(self) -> bool:
        return self.spec.binary is not None and shutil.which(self.spec.binary) is not None

    def run(self, args: list[str], cwd: str | None = None) -> dict:
        if not self.available():
            return {"tool": self.spec.key, "verdict": "tool_missing"}
        p = subprocess.run([self.spec.binary, *args], capture_output=True, text=True, cwd=cwd)
        return {"tool": self.spec.key, "rc": p.returncode, "log": p.stdout + p.stderr,
                "verdict": "pass" if p.returncode == 0 else "fail"}
