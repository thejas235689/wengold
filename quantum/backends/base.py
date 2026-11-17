"""Stable simulator adapter contract."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from quantum.core.circuit_ir import Circuit

class BackendUnavailable(RuntimeError):
    pass

@dataclass
class SimulationResult:
    job_id: str
    backend: str
    status: str
    shots: int | None = None
    statevector: list[list[float]] | None = None  # [real, imag] pairs; absent when unavailable
    probabilities: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    execution_time_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

class Backend(ABC):
    name = "abstract"
    @abstractmethod
    def capabilities(self) -> dict[str, Any]: ...
    @abstractmethod
    def run(self, circuit: Circuit, *, shots: int = 1024, seed: int | None = None) -> SimulationResult: ...
