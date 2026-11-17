import pytest

from quantum.core.circuit_ir import Circuit, Operation
from quantum.backends.base import SimulationResult
from quantum.service.debugger import QuantumDebugError, build_debug_trace


class FakeStatevectorBackend:
    name = "fake"

    def __init__(self):
        self.prefixes = []

    def run(self, circuit, *, shots=1, seed=None):
        self.prefixes.append(tuple(op.id for op in circuit.operations))
        return SimulationResult(
            job_id=str(len(self.prefixes)),
            backend=self.name,
            status="COMPLETED",
            statevector=[[1.0, 0.0], [0.0, 0.0]],
            probabilities={"0": 1.0},
            execution_time_ms=0.1,
        )


def test_debug_trace_captures_initial_and_each_gate_boundary():
    circuit = Circuit("trace", 1, (
        Operation("h0", "H", (0,)),
        Operation("x0", "X", (0,)),
    ))
    backend = FakeStatevectorBackend()

    trace = build_debug_trace(circuit, backend)

    assert trace.backend == "fake"
    assert trace.circuit_id == "trace"
    assert trace.num_steps == 2
    assert [s.gate for s in trace.snapshots] == ["INITIAL", "H", "X"]
    assert [s.operation_id for s in trace.snapshots] == [None, "h0", "x0"]
    assert backend.prefixes == [(), ("h0",), ("h0", "x0")]
    assert trace.snapshot(2).probabilities == {"0": 1.0}


def test_debug_trace_rejects_measurement_and_reset():
    for gate, clbits in (("MEASURE", (0,)), ("RESET", ())):
        circuit = Circuit("non-unitary", 1, (
            Operation("op0", gate, (0,), classical_bits=clbits),
        ), num_clbits=1)
        with pytest.raises(QuantumDebugError, match="not supported"):
            build_debug_trace(circuit, FakeStatevectorBackend())


def test_debug_trace_rejects_missing_statevector():
    class CountsOnlyBackend(FakeStatevectorBackend):
        def run(self, circuit, *, shots=1, seed=None):
            return SimulationResult(
                job_id="counts", backend=self.name, status="COMPLETED",
                counts={"0": 1},
            )

    circuit = Circuit("no-state", 1, (Operation("h0", "H", (0,)),))
    with pytest.raises(QuantumDebugError, match="did not return a statevector"):
        build_debug_trace(circuit, CountsOnlyBackend())


def test_debug_snapshot_index_is_checked():
    trace = build_debug_trace(Circuit("empty", 1), FakeStatevectorBackend())
    with pytest.raises(IndexError):
        trace.snapshot(1)



def test_amplitude_rows_report_complex_components_and_probability():
    from quantum.service.debugger import amplitude_rows

    rows = amplitude_rows(((1.0, 0.0), (0.0, 1.0)))
    assert [row.basis_state for row in rows] == ["0", "1"]
    assert rows[0].probability == pytest.approx(0.5)
    assert rows[1].probability == pytest.approx(0.5)
    assert rows[1].phase_radians == pytest.approx(1.57079632679)


def test_amplitude_rows_threshold_and_invalid_vectors():
    from quantum.service.debugger import QuantumDebugError, amplitude_rows

    assert len(amplitude_rows(((0.99, 0.0), (0.1, 0.0)), threshold=0.02)) == 1
    with pytest.raises(QuantumDebugError, match="zero or invalid norm"):
        amplitude_rows(((0.0, 0.0), (0.0, 0.0)))
    with pytest.raises(ValueError, match="threshold"):
        amplitude_rows(((1.0, 0.0),), threshold=-1)


def test_statevector_comparison_is_global_phase_invariant():
    import cmath
    from quantum.service.debugger import compare_statevectors

    reference = (1 / 2**0.5, 1j / 2**0.5)
    phase = cmath.exp(0.73j)
    candidate = tuple(phase * value for value in reference)

    result = compare_statevectors(reference, candidate)

    assert result.fidelity == pytest.approx(1.0)
    assert result.global_phase_radians == pytest.approx(0.73)
    assert result.dimension == 2


def test_statevector_comparison_rejects_dimension_and_zero_norm():
    from quantum.service.debugger import QuantumDebugError, compare_statevectors

    with pytest.raises(QuantumDebugError, match="dimensions differ"):
        compare_statevectors((1.0, 0.0), (1.0,))
    with pytest.raises(QuantumDebugError, match="zero norm"):
        compare_statevectors((0.0, 0.0), (1.0, 0.0))
