"""SymbiYosys adapter — open formal proofs (BMC, k-induction, cover)."""
from __future__ import annotations

import shutil
import subprocess

from ..base import ToolSpec
from ..registry import TOOL_GROUPS

SPEC: ToolSpec = next(t for t in TOOL_GROUPS["formal"] if t.key == "symbiyosys")


class SymbiYosysAdapter:
    spec = SPEC

    def available(self) -> bool:
        return shutil.which(self.spec.binary or "sby") is not None

    def prove(self, sby_file: str) -> dict:
        p = subprocess.run([self.spec.binary or "sby", "-f", sby_file],
                           capture_output=True, text=True)
        return {"tool": "symbiyosys", "action": "prove", "rc": p.returncode,
                "log": p.stdout + p.stderr, "verdict": "pass" if p.returncode == 0 else "fail"}

    def run(self, **kwargs) -> dict:
        return self.prove(**kwargs)
