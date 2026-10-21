"""Yosys adapter — synthesis and structural checks, fully open."""
from __future__ import annotations

import shutil
import subprocess

from ..base import ToolSpec
from ..registry import TOOL_GROUPS

SPEC: ToolSpec = next(t for t in TOOL_GROUPS["formal"] if t.key == "yosys")


class YosysAdapter:
    spec = SPEC

    def available(self) -> bool:
        return shutil.which(self.spec.binary or "yosys") is not None

    def synthesize(self, top: str, files: list[str]) -> dict:
        script = f"read_verilog {' '.join(files)}; synth -top {top}; stat"
        p = subprocess.run([self.spec.binary or "yosys", "-p", script],
                           capture_output=True, text=True)
        return {"tool": "yosys", "action": "synth", "rc": p.returncode,
                "log": p.stdout + p.stderr, "verdict": "pass" if p.returncode == 0 else "fail"}

    def run(self, **kwargs) -> dict:
        return self.synthesize(**kwargs)
