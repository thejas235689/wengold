"""SymbiYosys adapter — open formal proofs (BMC, k-induction, cover).

The exit code is not the verdict: sby can exit 0 having proved nothing. The
outcome is parsed from its `DONE (...)` / `Status:` lines, and anything that does
not clearly say PASS becomes FAIL or INCONCLUSIVE — never a silent pass.
"""
from __future__ import annotations

import shutil

from ..base import ToolSpec
from ..outcome import (Outcome, ToolOutcome, parse_sby_status, run_tool)
from ..registry import TOOL_GROUPS

SPEC: ToolSpec = next(t for t in TOOL_GROUPS["formal"] if t.key == "symbiyosys")
BIN = SPEC.binary or "sby"


class SymbiYosysAdapter:
    spec = SPEC

    def available(self) -> bool:
        return shutil.which(BIN) is not None

    def prove(self, sby_file: str, timeout: float = 1800.0, cwd: str | None = None) -> Outcome:
        def interpret(log: str, rc: int):
            parsed = parse_sby_status(log)
            if parsed is not None:
                return parsed
            # no structured status: an unparseable run proves nothing
            return ToolOutcome.INCONCLUSIVE if rc == 0 else ToolOutcome.ERROR

        return run_tool(BIN, ["-f", sby_file], tool="symbiyosys", action="prove",
                        timeout=timeout, cwd=cwd, interpret=interpret,
                        collect=["*.vcd", "*.log", "**/logfile.txt"])

    def run(self, **kwargs) -> Outcome:
        return self.prove(**kwargs)
