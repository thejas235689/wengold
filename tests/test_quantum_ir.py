import pytest
from quantum.core.circuit_ir import Circuit, Operation, CircuitValidationError, validate_circuit
from quantum.verification.math_checks import is_normalized, pure_state_fidelity, unitary_residual

def test_bell_circuit_ir_validates_and_roundtrips():
    c=Circuit("bell",2,(Operation("h0","H",(0,)),Operation("cx01","CNOT",(1,),(0,))))
    validate_circuit(c)
    assert Circuit.from_dict(c.to_dict()) == c

def test_rejects_out_of_range_qubit():
    with pytest.raises(CircuitValidationError): validate_circuit(Circuit("bad",1,(Operation("x","X",(1,)),)))

def test_rejects_duplicate_ids():
    with pytest.raises(CircuitValidationError): validate_circuit(Circuit("bad",1,(Operation("a","H",(0,)),Operation("a","X",(0,)))))

def test_rejects_wrong_rotation_parameter_count():
    with pytest.raises(CircuitValidationError): validate_circuit(Circuit("bad",1,(Operation("r","RX",(0,)),)))

def test_measurement_requires_classical_register():
    with pytest.raises(CircuitValidationError): validate_circuit(Circuit("bad",1,(Operation("m","MEASURE",(0,)),)))

def test_quantum_math_checks():
    state=[2**-0.5+0j,2**-0.5+0j]
    assert is_normalized(state)
    assert pure_state_fidelity(state,[-x for x in state]) == pytest.approx(1.0)
    assert unitary_residual([[0,1],[1,0]]) == pytest.approx(0.0)
