"""Cirq adapter with explicit classical-bit mapping and canonical bit ordering."""
from __future__ import annotations
import time
import uuid

from .base import Backend, BackendUnavailable, SimulationResult
from quantum.core.circuit_ir import Circuit, validate_circuit


class CirqBackend(Backend):
    name = "cirq"

    def __init__(self):
        try:
            import cirq
        except ImportError as exc:
            raise BackendUnavailable("Install optional simulator dependencies: pip install 'wengold[quantum]'") from exc
        self.cirq = cirq

    def capabilities(self):
        return {
            "statevector": True, "sampling": True, "noise": False, "hardware": False,
            "supported_gates": [
                "I", "H", "X", "Y", "Z", "S", "T", "RX", "RY", "RZ",
                "CNOT", "CX", "CZ", "SWAP", "CCX", "MEASURE",
            ],
        }

    def run(self, circuit: Circuit, *, shots: int = 1024, seed: int | None = None):
        validate_circuit(circuit)
        if shots < 1:
            raise ValueError("shots must be positive")
        c = self.cirq
        qubits = [c.LineQubit(i) for i in range(circuit.num_qubits)]
        operations = []
        measurement_keys: dict[str, tuple[int, ...]] = {}

        for op in circuit.operations:
            gate = op.gate.upper()
            targets = [qubits[i] for i in op.targets]
            controls = [qubits[i] for i in op.controls]
            params = op.params
            if gate == "MEASURE":
                key = f"m_{op.id}"
                operations.append(c.measure(*targets, key=key))
                measurement_keys[key] = tuple(op.classical_bits)
            elif gate in {"CNOT", "CX"}:
                operations.append(c.CNOT(controls[0], targets[0]))
            elif gate == "CCX":
                operations.append(c.TOFFOLI(controls[0], controls[1], targets[0]))
            elif gate == "CZ":
                operations.append(c.CZ(*targets))
            elif gate == "SWAP":
                operations.append(c.SWAP(*targets))
            elif gate in {"I", "H", "X", "Y", "Z", "S", "T", "RX", "RY", "RZ"}:
                fixed = {"I": c.I, "H": c.H, "X": c.X, "Y": c.Y, "Z": c.Z, "S": c.S, "T": c.T}
                gate_obj = fixed[gate] if gate in fixed else {
                    "RX": c.rx, "RY": c.ry, "RZ": c.rz
                }[gate](float(params[0]))
                operations.append(gate_obj.on(targets[0]))
            elif gate == "BARRIER":
                # Cirq moments preserve operation order; barriers have no state effect.
                continue
            else:
                raise BackendUnavailable(f"Cirq adapter does not support {gate}")

        circuit_obj = c.Circuit(operations)
        start = time.perf_counter()
        simulator = c.Simulator(seed=seed)
        if measurement_keys:
            result = simulator.run(circuit_obj, repetitions=shots)
            counts: dict[str, int] = {}
            for row_index in range(shots):
                classical = [0] * circuit.num_clbits
                for key, bit_indices in measurement_keys.items():
                    row = result.measurements[key][row_index]
                    for column, classical_bit in enumerate(bit_indices):
                        classical[classical_bit] = int(row[column])
                bitstring = "".join(str(classical[index]) for index in reversed(range(circuit.num_clbits)))
                counts[bitstring] = counts.get(bitstring, 0) + 1
            total = sum(counts.values()) or 1
            elapsed = (time.perf_counter() - start) * 1000
            return SimulationResult(
                uuid.uuid4().hex, self.name, "COMPLETED", shots,
                probabilities={key: value / total for key, value in counts.items()},
                counts=counts, execution_time_ms=elapsed,
                metadata={"method": "cirq_sampling", "bit_order": "c[n-1]..c[0]"},
            )

        state = simulator.simulate(circuit_obj, qubit_order=qubits).final_state_vector
        encoded = [[float(a.real), float(a.imag)] for a in state]
        probabilities = {
            format(index, f"0{circuit.num_qubits}b")[::-1]: float(abs(amplitude) ** 2)
            for index, amplitude in enumerate(state)
        }
        elapsed = (time.perf_counter() - start) * 1000
        return SimulationResult(
            uuid.uuid4().hex, self.name, "COMPLETED", None,
            statevector=encoded, probabilities=probabilities,
            execution_time_ms=elapsed,
            metadata={"method": "cirq_statevector", "bit_order": "q[n-1]..q[0]"},
        )
