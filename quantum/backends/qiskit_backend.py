"""Qiskit Aer adapter with canonical classical-bit ordering and statevector output."""
from __future__ import annotations
import time
import uuid
import numpy as np

from .base import Backend, BackendUnavailable, SimulationResult
from quantum.core.circuit_ir import Circuit, validate_circuit


class QiskitBackend(Backend):
    name = "qiskit"
    cache_identity = "qiskit-aer-statevector-v1"

    def __init__(self):
        try:
            from qiskit import QuantumCircuit, transpile
            from qiskit_aer import AerSimulator
        except ImportError as exc:
            raise BackendUnavailable(
                "Install optional simulator dependencies: pip install 'wengold[quantum]'"
            ) from exc
        self._qc_type = QuantumCircuit
        self._sim_type = AerSimulator
        self._transpile = transpile

    def capabilities(self):
        return {
            "statevector": True, "sampling": True, "noise": False, "hardware": False,
            "supported_gates": [
                "I", "H", "X", "Y", "Z", "S", "SDG", "T", "TDG", "SX",
                "RX", "RY", "RZ", "CNOT", "CX", "CZ", "SWAP", "CCX", "TOFFOLI", "CSWAP",
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
            elif gate in {"CCX", "TOFFOLI"}:
                qc.ccx(controls[0], controls[1], targets[0])
            elif gate == "CSWAP":
                qc.cswap(controls[0], targets[0], targets[1])
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
            compiled = self._transpile(qc, simulator)
            result = simulator.run(compiled, shots=1).result()
            state = np.asarray(result.get_statevector(compiled), dtype=np.complex128)
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

        compiled = self._transpile(qc, simulator)
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

    def run_incremental(self, circuit: Circuit, *, seed: int | None = 7):
        """Execute a unitary circuit once and capture every gate boundary.

        Aer save_statevector instructions create labelled snapshots within one
        simulator job; this avoids replaying every circuit prefix separately.
        """
        validate_circuit(circuit)
        if any(op.gate.upper() in {"MEASURE", "RESET", "BARRIER", "DELAY"}
               for op in circuit.operations):
            raise BackendUnavailable(
                "Incremental statevector debugging currently requires a unitary-only circuit"
            )
        start = time.perf_counter()
        qc = self._qc_type(circuit.num_qubits)
        labels = ["wengold_step_0"]
        qc.save_statevector(label=labels[0])
        for index, op in enumerate(circuit.operations, start=1):
            gate = op.gate.upper()
            targets = list(op.targets)
            controls = list(op.controls)
            params = op.params
            if gate in {"CNOT", "CX"}:
                qc.cx(controls[0], targets[0])
            elif gate in {"CCX", "TOFFOLI"}:
                qc.ccx(controls[0], controls[1], targets[0])
            elif gate == "CSWAP":
                qc.cswap(controls[0], targets[0], targets[1])
            elif gate in {"CZ", "SWAP"}:
                getattr(qc, gate.lower())(*targets)
            else:
                method = {"I": "id", "SDG": "sdg", "TDG": "tdg"}.get(gate, gate.lower())
                fn = getattr(qc, method, None)
                if fn is None:
                    raise BackendUnavailable(f"Qiskit adapter does not support {gate}")
                if gate in {"RX", "RY", "RZ"}:
                    fn(float(params[0]), targets[0])
                else:
                    fn(targets[0])
            label = f"wengold_step_{index}"
            qc.save_statevector(label=label)
            labels.append(label)

        simulator = self._sim_type(seed_simulator=seed)
        compiled = self._transpile(qc, simulator)
        result = simulator.run(compiled, shots=1).result()
        data = result.data(0)
        elapsed = (time.perf_counter() - start) * 1000
        snapshots = []
        for index, label in enumerate(labels):
            state = np.asarray(data[label], dtype=np.complex128)
            encoded = [[float(a.real), float(a.imag)] for a in state]
            probabilities = {
                format(basis, f"0{circuit.num_qubits}b"): float(abs(amplitude) ** 2)
                for basis, amplitude in enumerate(state)
            }
            snapshots.append(SimulationResult(
                job_id=f"{result.get_job_id()}:{index}",
                backend=self.name,
                status="COMPLETED",
                statevector=encoded,
                probabilities=probabilities,
                execution_time_ms=(elapsed if index == len(labels) - 1 else None),
                metadata={"method": "aer_incremental_statevector", "step": index,
                          "snapshot_label": label, "single_execution": True},
            ))
        return snapshots

    def run_trajectory(self, circuit: Circuit, *, seed: int | None = None):
        """Run one seeded shot and return state snapshots after each operation.

        Measurements collapse the Aer statevector. The final classical register
        value is returned with the trajectory; per-boundary classical history is
        not exposed by this adapter yet.
        """
        validate_circuit(circuit)
        if circuit.num_clbits < 1 or not any(
            op.gate.upper() == "MEASURE" for op in circuit.operations
        ):
            raise ValueError("trajectory execution requires measurement and classical bits")
        start = time.perf_counter()
        qc = self._qc_type(circuit.num_qubits, circuit.num_clbits)
        labels = ["wengold_trajectory_0"]
        qc.save_statevector(label=labels[0])
        boundary_ops = [(None, "INITIAL")]
        for index, op in enumerate(circuit.operations, start=1):
            gate = op.gate.upper()
            targets = list(op.targets)
            controls = list(op.controls)
            params = op.params
            if gate == "MEASURE":
                for qubit, cbit in zip(targets, op.classical_bits):
                    qc.measure(qubit, cbit)
            elif gate == "RESET":
                for qubit in targets:
                    qc.reset(qubit)
            elif gate == "BARRIER":
                qc.barrier(*targets)
            elif gate in {"CNOT", "CX"}:
                qc.cx(controls[0], targets[0])
            elif gate in {"CCX", "TOFFOLI"}:
                qc.ccx(controls[0], controls[1], targets[0])
            elif gate == "CSWAP":
                qc.cswap(controls[0], targets[0], targets[1])
            elif gate in {"CZ", "SWAP"}:
                getattr(qc, gate.lower())(*targets)
            else:
                method = {"I": "id", "SDG": "sdg", "TDG": "tdg"}.get(gate, gate.lower())
                fn = getattr(qc, method, None)
                if fn is None:
                    raise BackendUnavailable(f"Qiskit adapter does not support {gate}")
                if gate in {"RX", "RY", "RZ"}:
                    fn(float(params[0]), targets[0])
                else:
                    fn(targets[0])
            label = f"wengold_trajectory_{index}"
            qc.save_statevector(label=label)
            labels.append(label)
            boundary_ops.append((op.id, gate))

        simulator = self._sim_type(seed_simulator=seed)
        compiled = self._transpile(qc, simulator)
        result = simulator.run(compiled, shots=1).result()
        data = result.data(0)
        raw_counts = result.get_counts(compiled)
        raw_key = next(iter(raw_counts))
        classical = str(raw_key).replace(" ", "").zfill(circuit.num_clbits)[-circuit.num_clbits:]
        elapsed = (time.perf_counter() - start) * 1000
        snapshots = []
        for index, label in enumerate(labels):
            state = np.asarray(data[label], dtype=np.complex128)
            snapshots.append({
                "step": index,
                "operation_id": boundary_ops[index][0],
                "gate": boundary_ops[index][1],
                "statevector": tuple((float(a.real), float(a.imag)) for a in state),
            })
        return {
            "classical_bits": classical,
            "snapshots": snapshots,
            "execution_time_ms": elapsed,
            "metadata": {"method": "aer_single_shot_trajectory", "seed": seed},
        }
