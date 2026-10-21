"""Tool adapter contract.

A ToolAdapter turns one EDA or workflow tool into a deterministic action the
agents can call. The tools settle every verdict; agents only decide where to
look and which tool to run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ToolSpec:
    key: str                 # "verilator"
    name: str                # "Verilator"
    vendor: str              # "Verilator" | "Synopsys" | "Cadence" | ...
    group: str               # "simulation" | "formal" | "flow"
    role: str                # "simulator" | "lint" | "formal" | "debug" | ...
    open_source: bool
    binary: str | None = None


class ToolAdapter(Protocol):
    spec: ToolSpec

    def available(self) -> bool: ...
    def run(self, **kwargs) -> dict: ...
