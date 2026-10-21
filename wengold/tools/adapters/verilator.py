"""Verilator adapter — lint and simulate, fully open."""
from __future__ import annotations

import shutil
import subprocess

from ..base import ToolSpec
from ..registry import TOOL_GROUPS

SPEC: ToolSpec = next(t for t in TOOL_GROUPS["simulation"] if t.key == "verilator")


class VerilatorAdapter:
    spec = SPEC

    def available(self) -> bool:
        return shutil.which(self.spec.binary or "verilator") is not None

    def lint(self, top: str, files: list[str]) -> dict:
        cmd = [self.spec.binary or "verilator", "--lint-only", "-Wall", "--top-module", top, *files]
        p = subprocess.run(cmd, capture_output=True, text=True)
        return {"tool": "verilator", "action": "lint", "rc": p.returncode,
                "log": p.stdout + p.stderr, "verdict": "pass" if p.returncode == 0 else "fail"}

    def run(self, **kwargs) -> dict:
        return self.lint(**kwargs)
