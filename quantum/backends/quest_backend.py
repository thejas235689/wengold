"""WENGOLD-owned pybind11 bridge to QuEST v4.

Build the extension with quantum/native/CMakeLists.txt. The bridge executes
unitary gates on QuEST and returns a canonical Python statevector. Terminal
measurements are sampled in Python; mid-circuit measurement/reset are rejected
until trajectory execution is implemented.
"""
from __future__ import annotations

import time
import uuid
import numpy as np

from .base import Backend, BackendUnavailable, SimulationResult
from quantum.core.circuit_ir import Circuit, validate_circuit

try:
    from . import _quest_bridge
except ImportError as exc:
    _quest_bridge = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class QuESTBackend(Backend):
    name = "quest"

    def __init__(self):
        if _quest_bridge is None:
            raise BackendUnavailable(
                "QuEST bridge is not built. Install QuEST v4 and pybind11, then "
                "build quantum/native with CMake. See quantum/native/README.md."
            ) from _IMPORT_ERROR

    def capabilities(self):
        return {
            "statevector": True, "sampling": True, "density_matrix": False,
            "noise": False, "hardware": False, "gpu": "QuEST-build-dependent",
            "mpi": "QuEST-build-dependent",
            "supported_gates": [
                "I", "H", "X", "Y", "Z", "S", "SDG", "T", "TDG",
                "RX", "RY", "RZ", "CNOT", "CX", "CZ", "SWAP",
                "CCX", "TOFFOLI", "CSWAP", "BARRIER", "MEASURE",
            ],
        }

    def run(self, circuit: Circuit, *, shots: int = 1024, seed: int | None = None):
        validate_circuit(circuit)
        if shots < 1:
            raise ValueError("shots must be positive")

        measured = [op for op in circuit.operations if op.gate.upper() == "MEASURE"]
        if measured:
            first_measure = next(i for i, op in enumerate(circuit.operations)
                                 if op.gate.upper() == "MEASURE")
            if any(op.gate.upper() not in {"MEASURE", "BARRIER"}
                   for op in circuit.operations[first_measure:]):
                raise BackendUnavailable(
                    "QuEST adapter currently supports terminal measurements only; "
                    "mid-circuit measurement and reset require trajectory execution."
                )

        gates = []
        for op in circuit.operations:
            gate = op.gate.upper()
            if gate == "MEASURE":
                continue
            if gate in {"RESET", "DELAY"}:
                raise BackendUnavailable(f"QuEST adapter does not yet support {gate}")
            gates.append((gate, list(op.targets), list(op.controls),
                          float(op.params[0]) if op.params else 0.0))

        start = time.perf_counter()
        raw_state = _quest_bridge.run_statevector(circuit.num_qubits, gates)
        state = np.asarray([complex(real, imag) for real, imag in raw_state], dtype=np.complex128)
        norm = float(np.vdot(state, state).real)
        if not np.isfinite(norm) or norm <= 0.0:
            raise RuntimeError("QuEST returned a zero or invalid statevector")
        state /= np.sqrt(norm)

        if not measured:
            probabilities = {
                format(index, f"0{circuit.num_qubits}b"): float(abs(amplitude) ** 2)
                for index, amplitude in enumerate(state)
            }
            elapsed = (time.perf_counter() - start) * 1000
            return SimulationResult(
                uuid.uuid4().hex, self.name, "COMPLETED", None,
                statevector=[[float(a.real), float(a.imag)] for a in state],
                probabilities=probabilities, execution_time_ms=elapsed,
                metadata={"method": "quest_v4_statevector", "bit_order": "q[n-1]..q[0]"},
            )

        rng = np.random.default_rng(seed)
        sampling_probabilities = np.abs(state) ** 2
        sampling_probabilities /= sampling_probabilities.sum()
        basis = rng.choice(len(state), size=shots, p=sampling_probabilities)
        counts: dict[str, int] = {}
        for index in basis:
            qbits = format(int(index), f"0{circuit.num_qubits}b")
            classical = [0] * circuit.num_clbits
            for op in measured:
                for qubit, cbit in zip(op.targets, op.classical_bits):
                    classical[cbit] = int(qbits[-1 - qubit])
            key = "".join(str(classical[i]) for i in reversed(range(circuit.num_clbits)))
            counts[key] = counts.get(key, 0) + 1
        total = sum(counts.values()) or 1
        elapsed = (time.perf_counter() - start) * 1000
        return SimulationResult(
            uuid.uuid4().hex, self.name, "COMPLETED", shots,
            probabilities={key: value / total for key, value in counts.items()},
            counts=counts, execution_time_ms=elapsed,
            metadata={"method": "quest_v4_sampling", "bit_order": "c[n-1]..c[0]",
                      "seed": seed, "measurement_mode": "terminal"},
        )
