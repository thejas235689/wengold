"""Gate-by-gate statevector replay for the Quantum Studio debugger.

The first debugger milestone intentionally supports unitary-only circuits. It
replays each prefix through the selected backend, producing state snapshots
without pretending to support mid-circuit measurement or reset.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
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



@dataclass(frozen=True)
class AmplitudeRow:
    basis_state: str
    real: float
    imag: float
    magnitude: float
    phase_radians: float
    probability: float


@dataclass(frozen=True)
class StatevectorComparison:
    fidelity: float
    global_phase_radians: float
    reference_norm: float
    candidate_norm: float
    dimension: int


def _complex_amplitude(value: Any) -> complex:
    """Accept Python complex values or backend [real, imag] pairs."""
    if isinstance(value, complex):
        result = value
    elif isinstance(value, (tuple, list)) and len(value) == 2:
        result = complex(float(value[0]), float(value[1]))
    else:
        result = complex(float(value), 0.0)
    if not (math.isfinite(result.real) and math.isfinite(result.imag)):
        raise QuantumDebugError("statevector contains a non-finite amplitude")
    return result


def amplitude_rows(statevector: Any, *, threshold: float = 0.0) -> tuple[AmplitudeRow, ...]:
    """Return basis-indexed amplitude details; basis labels use q[n-1]…q[0]."""
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("threshold must be a finite non-negative number")
    values = tuple(_complex_amplitude(value) for value in statevector)
    if not values:
        raise QuantumDebugError("statevector is empty")
    norm_sq = sum(abs(value) ** 2 for value in values)
    if not math.isfinite(norm_sq) or norm_sq <= 0:
        raise QuantumDebugError("statevector has zero or invalid norm")
    qubits = (len(values) - 1).bit_length()
    rows = []
    for index, value in enumerate(values):
        probability = abs(value) ** 2 / norm_sq
        if probability < threshold:
            continue
        rows.append(AmplitudeRow(
            basis_state=format(index, f"0{qubits}b"),
            real=value.real,
            imag=value.imag,
            magnitude=abs(value),
            phase_radians=math.atan2(value.imag, value.real) if value else 0.0,
            probability=probability,
        ))
    return tuple(rows)


def compare_statevectors(reference: Any, candidate: Any) -> StatevectorComparison:
    """Compare two pure states using fidelity invariant to global phase.

    Both inputs are normalized for comparison. The reported phase is the
    candidate's global phase relative to the reference, inferred from <ref|cand>.
    """
    ref = tuple(_complex_amplitude(value) for value in reference)
    cand = tuple(_complex_amplitude(value) for value in candidate)
    if not ref or not cand:
        raise QuantumDebugError("statevectors must not be empty")
    if len(ref) != len(cand):
        raise QuantumDebugError(
            f"statevector dimensions differ: {len(ref)} != {len(cand)}"
        )
    ref_norm_sq = sum(abs(value) ** 2 for value in ref)
    cand_norm_sq = sum(abs(value) ** 2 for value in cand)
    if ref_norm_sq <= 0 or cand_norm_sq <= 0:
        raise QuantumDebugError("statevector has zero norm")
    overlap = sum(a.conjugate() * b for a, b in zip(ref, cand))
    fidelity = min(1.0, max(0.0, abs(overlap) ** 2 / (ref_norm_sq * cand_norm_sq)))
    phase = math.atan2(overlap.imag, overlap.real) if overlap else 0.0
    return StatevectorComparison(
        fidelity=fidelity,
        global_phase_radians=phase,
        reference_norm=math.sqrt(ref_norm_sq),
        candidate_norm=math.sqrt(cand_norm_sq),
        dimension=len(ref),
    )
