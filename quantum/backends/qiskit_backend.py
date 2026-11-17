"""Qiskit Aer adapter with canonical classical-bit ordering and statevector output."""
from __future__ import annotations
import time
import uuid

from .base import Backend, BackendUnavailable, SimulationResult
from quantum.core.circuit_ir import Circuit, validate_circuit


class QiskitBackend(Backend):
    name = "qiskit"

    def __init__(self):
        try:
            from qiskit import QuantumCircuit
            from qiskit_aer import AerSimulator
        except ImportError as exc:
            raise BackendUnavailable(
                "Install optional simulator dependencies: pip install 'wengold[quantum]'"
            ) from exc
        self._qc_type = QuantumCircuit
        self._sim_type = AerSimulator

    def capabilities(self):
        return {
            "statevector": True, "sampling": True, "noise": False, "hardware": False,
            "supported_gates": [
                "I", "H", "X", "Y", "Z", "S", "SDG", "T", "TDG", "SX",
                "RX", "RY", "RZ", "CNOT", "CX", "CZ", "SWAP", "CCX",
                "MEASURE", "RESET", "BARRIER",
            ],
        }

    def run(self, circuit: Circuit, *, shots: int = 1024, seed: int | None = None):
        validate_circuit(circuit)
        if shots < 1:
            raise ValueError("shots must be positive")
        start = time.perf_counter()
        measured = any(op.gate.upper() == "MEASURE" for op in circuit.operations)
        nclbits = circuit.num_clbits if measured else 0
        qc = self._qc_type(circuit.num_qubits, nclbits)

        for op in circuit.operations:
            gate = op.gate.upper()
            targets = list(op.targets)
            controls = list(op.controls)
            params = op.params
            if gate in {"CNOT", "CX"}:
                qc.cx(controls[0], targets[0])
            elif gate == "CCX":
                qc.ccx(controls[0], controls[1], targets[0])
            elif gate == "MEASURE":
                for qubit, cbit in zip(targets, op.classical_bits):
                    qc.measure(qubit, cbit)
            elif gate == "BARRIER":
                qc.barrier(*targets)
            elif gate == "RESET":
                for qubit in targets:
                    qc.reset(qubit)
            elif gate in {"I", "H", "X", "Y", "Z", "S", "SDG", "T", "TDG", "SX",
                          "RX", "RY", "RZ", "CZ", "SWAP"}:
                method = {"I": "id", "SDG": "sdg", "TDG": "tdg"}.get(gate, gate.lower())
                fn = getattr(qc, method)
                if gate in {"RX", "RY", "RZ"}:
                    fn(float(params[0]), targets[0])
                elif gate in {"CZ", "SWAP"}:
                    fn(*targets)
                else:
                    fn(targets[0])
            else:
                raise BackendUnavailable(f"Qiskit adapter does not support {gate}")

        simulator = self._sim_type(seed_simulator=seed)
        if not measured:
            qc.save_statevector()
            compiled = __import__("qiskit").transpile(qc, simulator)
            result = simulator.run(compiled, shots=1).result()
            state = result.get_statevector(compiled)
            encoded = [[float(a.real), float(a.imag)] for a in state]
            probabilities = {
                format(index, f"0{circuit.num_qubits}b"): float(abs(amplitude) ** 2)
                for index, amplitude in enumerate(state)
            }
            elapsed = (time.perf_counter() - start) * 1000
            return SimulationResult(
                uuid.uuid4().hex, self.name, "COMPLETED", None,
                statevector=encoded, probabilities=probabilities,
                execution_time_ms=elapsed,
                metadata={"method": "aer_statevector", "bit_order": "c[n-1]..c[0]"},
            )

        compiled = __import__("qiskit").transpile(qc, simulator)
        counts = simulator.run(compiled, shots=shots).result().get_counts()
        normalized = {}
        for raw_key, value in counts.items():
            bits = str(raw_key).replace(" ", "")
            canonical = bits.zfill(circuit.num_clbits)[-circuit.num_clbits:]
            normalized[canonical] = normalized.get(canonical, 0) + int(value)
        total = sum(normalized.values()) or 1
        elapsed = (time.perf_counter() - start) * 1000
        return SimulationResult(
            uuid.uuid4().hex, self.name, "COMPLETED", shots,
            probabilities={key: value / total for key, value in normalized.items()},
            counts=normalized, execution_time_ms=elapsed,
            metadata={"method": "aer_sampling", "bit_order": "c[n-1]..c[0]"},
        )
