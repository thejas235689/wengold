"""Verilator adapter — lint and simulate, fully open."""
from __future__ import annotations

import shutil

from ..base import ToolSpec
from ..outcome import Outcome, ToolOutcome, run_tool
from ..registry import TOOL_GROUPS

SPEC: ToolSpec = next(t for t in TOOL_GROUPS["simulation"] if t.key == "verilator")
BIN = SPEC.binary or "verilator"


class VerilatorAdapter:
    spec = SPEC

    def available(self) -> bool:
        return shutil.which(BIN) is not None

    def lint(self, top: str, files: list[str], timeout: float = 300.0,
             cwd: str | None = None, warnings_as_errors: bool = True) -> Outcome:
        argv = ["--lint-only", "-Wall", "--top-module", top]
        # Verilator has no bare `-Werror` (warnings are fatal by default); the
        # switch that exists is `-Wno-fatal`, so that is what turns it off.
        if not warnings_as_errors:
            argv.append("-Wno-fatal")
        argv += list(files)
        return run_tool(BIN, argv, tool="verilator", action="lint",
                        timeout=timeout, cwd=cwd,
                        interpret=lambda log, rc: ToolOutcome.PASS if rc == 0 else ToolOutcome.FAIL)

    def run(self, **kwargs) -> Outcome:
        return self.lint(**kwargs)
