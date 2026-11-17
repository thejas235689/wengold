import pytest

from quantum.core.circuit_ir import Circuit, Operation, CircuitValidationError, validate_circuit
from quantum.verification.math_checks import is_normalized, pure_state_fidelity, unitary_residual


def test_bell_circuit_ir_validates_and_roundtrips():
    circuit = Circuit("bell", 2, (
        Operation("h0", "H", (0,)),
        Operation("cx01", "CNOT", (1,), (0,)),
    ))
    validate_circuit(circuit)
    assert Circuit.from_dict(circuit.to_dict()) == circuit


def test_rejects_out_of_range_qubit():
    with pytest.raises(CircuitValidationError):
        validate_circuit(Circuit("bad", 1, (Operation("x", "X", (1,)),)))


def test_rejects_duplicate_ids():
    with pytest.raises(CircuitValidationError):
        validate_circuit(Circuit("bad", 1, (
            Operation("a", "H", (0,)), Operation("a", "X", (0,))
        )))


def test_rejects_wrong_rotation_parameter_count():
    with pytest.raises(CircuitValidationError):
        validate_circuit(Circuit("bad", 1, (Operation("r", "RX", (0,)),)))


def test_measurement_requires_classical_register():
    with pytest.raises(CircuitValidationError):
        validate_circuit(Circuit("bad", 1, (Operation("m", "MEASURE", (0,)),)))


def test_rejects_ambiguous_cnot_operand_shape():
    with pytest.raises(CircuitValidationError):
        validate_circuit(Circuit("bad", 2, (Operation("cx", "CNOT", (0, 1)),)))


def test_rejects_non_measurement_classical_bits():
    with pytest.raises(CircuitValidationError):
        validate_circuit(Circuit("bad", 1, (
            Operation("x", "X", (0,), classical_bits=(0,)),
        ), num_clbits=1))


def test_quantum_math_checks():
    state = [2**-0.5 + 0j, 2**-0.5 + 0j]
    assert is_normalized(state)
    assert pure_state_fidelity(state, [-x for x in state]) == pytest.approx(1.0)
    assert unitary_residual([[0, 1], [1, 0]]) == pytest.approx(0.0)

def test_quantum_project_save_load_is_atomic_and_roundtrips(tmp_path):
    from quantum.core.project import save_project, load_project

    circuit = Circuit("bell", 2, (
        Operation("h0", "H", (0,)),
        Operation("cx01", "CNOT", (1,), (0,)),
    ))
    path = save_project(tmp_path / "bell.wqproj", circuit, metadata={"authoring": "test"})
    restored, metadata = load_project(path)
    assert restored == circuit
    assert metadata == {"authoring": "test"}
