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

def test_statevector_qubit_zero_uses_rightmost_bit_in_both_backends():
    circuit = Circuit("qubit-zero", 2, (Operation("x0", "X", (0,)),))
    pytest.importorskip("qiskit")
    pytest.importorskip("qiskit_aer")
    from quantum.backends.qiskit_backend import QiskitBackend
    qiskit_result = QiskitBackend().run(circuit, seed=3)
    assert qiskit_result.probabilities["01"] == pytest.approx(1.0, abs=1e-8)

    pytest.importorskip("cirq")
    from quantum.backends.cirq_backend import CirqBackend
    cirq_result = CirqBackend().run(circuit, seed=3)
    assert cirq_result.probabilities["01"] == pytest.approx(1.0, abs=1e-8)

def test_quest_is_never_reported_available_before_native_bridge_exists():
    from quantum.backends import available_backends
    backends = available_backends()
    assert backends["quest"]["installed"] is False
    assert backends["quest"]["status"] == "not_implemented"


def test_reset_gate_is_supported_by_both_simulators():
    circuit = Circuit("reset", 1, (
        Operation("x0", "X", (0,)),
        Operation("reset0", "RESET", (0,)),
    ))
    pytest.importorskip("qiskit")
    pytest.importorskip("qiskit_aer")
    from quantum.backends.qiskit_backend import QiskitBackend
    qiskit_result = QiskitBackend().run(circuit, seed=5)
    assert qiskit_result.probabilities["0"] == pytest.approx(1.0, abs=1e-8)

    pytest.importorskip("cirq")
    from quantum.backends.cirq_backend import CirqBackend
    cirq_result = CirqBackend().run(circuit, seed=5)
    assert cirq_result.probabilities["0"] == pytest.approx(1.0, abs=1e-8)
