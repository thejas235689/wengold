import pytest

from quantum.core.circuit_ir import Circuit, Operation
from quantum.backends.base import BackendUnavailable


def bell_circuit(measure=False):
    operations = [
        Operation("h0", "H", (0,)),
        Operation("cx01", "CNOT", (1,), (0,)),
    ]
    if measure:
        operations.append(Operation("measure", "MEASURE", (0, 1), classical_bits=(0, 1)))
    return Circuit("bell", 2, tuple(operations), num_clbits=2 if measure else 0)


def assert_bell_distribution(probabilities):
    assert probabilities.get("00", 0.0) == pytest.approx(0.5, abs=0.08)
    assert probabilities.get("11", 0.0) == pytest.approx(0.5, abs=0.08)
    assert sum(probabilities.values()) == pytest.approx(1.0, abs=1e-8)


def test_qiskit_bell_statevector_and_measurement():
    pytest.importorskip("qiskit")
    pytest.importorskip("qiskit_aer")
    from quantum.backends.qiskit_backend import QiskitBackend
    backend = QiskitBackend()
    state = backend.run(bell_circuit(), shots=256, seed=7)
    assert state.status == "COMPLETED"
    assert state.statevector is not None
    assert_bell_distribution(state.probabilities)
    measured = backend.run(bell_circuit(measure=True), shots=1024, seed=7)
    assert set(measured.counts).issubset({"00", "11"})
    assert sum(measured.counts.values()) == 1024


def test_cirq_bell_statevector_and_measurement():
    pytest.importorskip("cirq")
    from quantum.backends.cirq_backend import CirqBackend
    backend = CirqBackend()
    state = backend.run(bell_circuit(), shots=256, seed=7)
    assert state.status == "COMPLETED"
    assert state.statevector is not None
    assert_bell_distribution(state.probabilities)
    measured = backend.run(bell_circuit(measure=True), shots=1024, seed=7)
    assert set(measured.counts).issubset({"00", "11"})
    assert sum(measured.counts.values()) == 1024
