"""Yosys adapter — synthesis and structural checks, fully open."""
from __future__ import annotations

import shutil

from ..base import ToolSpec
from ..outcome import Outcome, ToolOutcome, run_tool
from ..registry import TOOL_GROUPS

SPEC: ToolSpec = next(t for t in TOOL_GROUPS["formal"] if t.key == "yosys")
BIN = SPEC.binary or "yosys"


class YosysAdapter:
    spec = SPEC

    def available(self) -> bool:
        return shutil.which(BIN) is not None

    def synthesize(self, top: str, files: list[str], timeout: float = 600.0,
                   cwd: str | None = None, liberty: str | None = None) -> Outcome:
        # SystemVerilog needs `-sv`; read_verilog defaults to Verilog-2005.
        script = f"read_verilog -sv {' '.join(files)}; synth -top {top}"
        if liberty:
            script += f"; dfflibmap -liberty {liberty}; abc -liberty {liberty}"
        script += "; stat"
        return run_tool(BIN, ["-p", script], tool="yosys", action="synth",
                        timeout=timeout, cwd=cwd,
                        interpret=lambda log, rc: ToolOutcome.PASS if rc == 0 else ToolOutcome.FAIL)

    def run(self, **kwargs) -> Outcome:
        return self.synthesize(**kwargs)
