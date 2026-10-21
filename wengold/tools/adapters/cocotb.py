"""cocotb adapter — Python testbenches against any simulator, fully open."""
from __future__ import annotations

from ..base import ToolSpec
from ..registry import TOOL_GROUPS

SPEC: ToolSpec = next(t for t in TOOL_GROUPS["simulation"] if t.key == "cocotb")


class CocotbAdapter:
    spec = SPEC

    def available(self) -> bool:
        try:
            import cocotb  # noqa: F401
            return True
        except Exception:
            return False

    def run(self, **kwargs) -> dict:
        # Delegated to `make`/pytest with the simulator env (SIM=verilator).
        raise NotImplementedError("wire to your project's cocotb runner")
