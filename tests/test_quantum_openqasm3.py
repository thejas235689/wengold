import math
import pytest

from quantum.core.circuit_ir import Circuit, Operation, CircuitValidationError
from quantum.core.openqasm3 import import_openqasm3, export_openqasm3


def test_import_export_roundtrip_for_supported_gate_set():
    circuit = Circuit("bell", 2, (
        Operation("h0", "H", (0,)),
        Operation("rx1", "RX", (1,), params=(math.pi / 2,)),
        Operation("cx01", "CNOT", (1,), (0,)),
        Operation("m0", "MEASURE", (0,), classical_bits=(1,)),
    ), num_clbits=2)
    restored = import_openqasm3(export_openqasm3(circuit), circuit_id="bell")
    assert [(op.gate, op.targets, op.controls, op.params, op.classical_bits) for op in restored.operations] == [\n        (op.gate, op.targets, op.controls, op.params, op.classical_bits) for op in circuit.operations\n    ]\n    assert restored.num_qubits == circuit.num_qubits\n    assert restored.num_clbits == circuit.num_clbits


def test_import_accepts_measure_arrow_and_rotation_expression():
    source = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
bit[2] c;
ry(pi/2) q[1];
measure q[1] -> c[0];
"""
    circuit = import_openqasm3(source, circuit_id="sample")
    assert circuit.operations[0].params == pytest.approx((math.pi / 2,))
    assert circuit.operations[1].classical_bits == (0,)


def test_import_maps_ccx_and_cswap_operands():
    source = """OPENQASM 3.0;
qubit[3] q;
ccx q[0], q[1], q[2];
cswap q[0], q[1], q[2];
"""
    circuit = import_openqasm3(source)
    assert circuit.operations[0].controls == (0, 1)
    assert circuit.operations[0].targets == (2,)
    assert circuit.operations[1].controls == (0,)
    assert circuit.operations[1].targets == (1, 2)


def test_import_rejects_unsupported_control_flow_instead_of_dropping_it():
    source = """OPENQASM 3.0;
qubit[1] q;
if (true) { x q[0]; }
"""
    with pytest.raises(CircuitValidationError, match="unsupported OpenQASM"):
        import_openqasm3(source)


def test_import_rejects_out_of_range_operands():
    source = """OPENQASM 3.0;
qubit[1] q;
x q[1];
"""
    with pytest.raises(CircuitValidationError, match="out of range"):
        import_openqasm3(source)


def test_parameter_parser_does_not_evaluate_arbitrary_python():
    source = """OPENQASM 3.0;
qubit[1] q;
rx(__import__('os').system('id')) q[0];
"""
    with pytest.raises(CircuitValidationError):
        import_openqasm3(source)
