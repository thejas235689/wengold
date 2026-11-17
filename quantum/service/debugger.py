"""Gate-by-gate statevector replay for the Quantum Studio debugger.

The first debugger milestone intentionally supports unitary-only circuits. It
replays each prefix through the selected backend, producing state snapshots
without pretending to support mid-circuit measurement or reset.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quantum.core.circuit_ir import Circuit, NON_UNITARY, Operation, validate_circuit


class QuantumDebugError(ValueError):
    """Raised when a circuit cannot be represented safely as a statevector trace."""


@dataclass(frozen=True)
class DebugSnapshot:
    """State after one circuit boundary; index zero is the initial state."""

    step: int
    operation_id: str | None
    gate: str
    statevector: tuple[tuple[float, float], ...]
    probabilities: dict[str, float]
    execution_time_ms: float | None = None


@dataclass(frozen=True)
class QuantumDebugTrace:
    circuit_id: str
    backend: str
    snapshots: tuple[DebugSnapshot, ...]

    @property
    def num_steps(self) -> int:
        return max(0, len(self.snapshots) - 1)

    def snapshot(self, step: int) -> DebugSnapshot:
        if step < 0 or step >= len(self.snapshots):
            raise IndexError(f"debug step {step} outside 0..{len(self.snapshots) - 1}")
        return self.snapshots[step]


def build_debug_trace(
    circuit: Circuit,
    backend: Any,
    *,
    seed: int | None = 7,
) -> QuantumDebugTrace:
    """Replay each unitary prefix and capture its statevector.

    The backend is called once for the initial state and once after every gate.
    Measurement, reset, barrier and delay are rejected because a single
    pure-state snapshot is not a faithful representation of those operations.
    """
    validate_circuit(circuit)
    for operation in circuit.operations:
        if operation.gate.upper() in NON_UNITARY:
            raise QuantumDebugError(
                f"{operation.gate.upper()} at operation {operation.id!r} "
                "is not supported by the statevector debugger"
            )

    snapshots: list[DebugSnapshot] = []
    prefixes: list[Operation] = []
    boundaries = [(None, "INITIAL")]
    boundaries.extend((op.id, op.gate.upper()) for op in circuit.operations)

    for step, (operation_id, gate) in enumerate(boundaries):
        if step:
            prefixes.append(circuit.operations[step - 1])
        prefix = Circuit(
            circuit_id=f"{circuit.circuit_id}:debug:{step}",
            num_qubits=circuit.num_qubits,
            operations=tuple(prefixes),
            num_clbits=circuit.num_clbits,
            schema_version=circuit.schema_version,
            metadata=dict(circuit.metadata),
        )
        result = backend.run(prefix, shots=1, seed=seed)
        if result.statevector is None:
            raise QuantumDebugError(
                f"backend {result.backend!r} did not return a statevector at step {step}"
            )
        vector = tuple((float(pair[0]), float(pair[1])) for pair in result.statevector)
        snapshots.append(DebugSnapshot(
            step=step,
            operation_id=operation_id,
            gate=gate,
            statevector=vector,
            probabilities=dict(result.probabilities),
            execution_time_ms=result.execution_time_ms,
        ))

    return QuantumDebugTrace(
        circuit_id=circuit.circuit_id,
        backend=getattr(backend, "name", "unknown"),
        snapshots=tuple(snapshots),
    )
