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



def test_checkpoint_cache_reuses_prefixes_for_same_backend_identity():
    from quantum.service.debugger import (
        clear_debug_checkpoint_cache, debug_checkpoint_cache_info,
    )

    class StableBackend(FakeStatevectorBackend):
        cache_identity = "fake-statevector-v1"

    clear_debug_checkpoint_cache()
    circuit = Circuit("cached", 1, (
        Operation("h0", "H", (0,)),
        Operation("x0", "X", (0,)),
    ))
    first_backend = StableBackend()
    first = build_debug_trace(circuit, first_backend)
    assert len(first_backend.prefixes) == 3

    second_backend = StableBackend()
    second = build_debug_trace(circuit, second_backend)

    assert second_backend.prefixes == []
    assert [item.statevector for item in first.snapshots] == [
        item.statevector for item in second.snapshots
    ]
    assert all(item.execution_time_ms is None for item in second.snapshots)
    assert debug_checkpoint_cache_info()["hits"] == 3
    clear_debug_checkpoint_cache()


def test_checkpoint_cache_invalidates_on_operation_or_seed_change():
    from quantum.service.debugger import clear_debug_checkpoint_cache

    class StableBackend(FakeStatevectorBackend):
        cache_identity = "fake-statevector-v1"

    clear_debug_checkpoint_cache()
    backend = StableBackend()
    original = Circuit("same-id", 1, (Operation("h0", "H", (0,)),))
    changed = Circuit("same-id", 1, (Operation("x0", "X", (0,)),))

    build_debug_trace(original, backend, seed=7)
    build_debug_trace(changed, backend, seed=7)
    build_debug_trace(original, backend, seed=8)

    assert len(backend.prefixes) == 5
    clear_debug_checkpoint_cache()


def test_checkpoint_cache_can_be_bypassed():
    from quantum.service.debugger import clear_debug_checkpoint_cache

    class StableBackend(FakeStatevectorBackend):
        cache_identity = "fake-statevector-v1"

    clear_debug_checkpoint_cache()
    circuit = Circuit("uncached", 1, (Operation("h0", "H", (0,)),))
    backend = StableBackend()

    build_debug_trace(circuit, backend, use_cache=False)
    build_debug_trace(circuit, backend, use_cache=False)

    assert len(backend.prefixes) == 4
    clear_debug_checkpoint_cache()


def test_qiskit_incremental_trace_uses_single_execution_when_available():
    pytest.importorskip("qiskit_aer")
    from quantum.backends.qiskit_backend import QiskitBackend

    circuit = Circuit("incremental", 1, (
        Operation("h0", "H", (0,)),
        Operation("x0", "X", (0,)),
    ))
    clear_debug_checkpoint_cache()
    trace = build_debug_trace(circuit, QiskitBackend(), use_cache=False)

    assert len(trace.snapshots) == 3
    assert trace.snapshots[0].gate == "INITIAL"
    assert trace.snapshots[1].gate == "H"
    assert trace.snapshots[2].gate == "X"
    assert trace.snapshots[0].statevector[0] == pytest.approx((1.0, 0.0))
    assert abs(trace.snapshots[1].statevector[0][0]) == pytest.approx(2 ** -0.5)
    assert abs(trace.snapshots[2].statevector[1][0]) == pytest.approx(2 ** -0.5)


def test_qiskit_measurement_trajectories_capture_each_shot_and_collapsed_states():
    pytest.importorskip("qiskit_aer")
    from quantum.backends.qiskit_backend import QiskitBackend
    from quantum.service.debugger import build_measurement_trajectories

    circuit = Circuit("bell-trajectories", 2, (
        Operation("h0", "H", (0,)),
        Operation("cx01", "CNOT", (1,), (0,)),
        Operation("measure0", "MEASURE", (0,), classical_bits=(0,)),
        Operation("measure1", "MEASURE", (1,), classical_bits=(1,)),
    ), num_clbits=2)

    trace = build_measurement_trajectories(
        circuit, QiskitBackend(), shots=12, seed=31,
    )

    assert trace.shots == 12
    assert all(len(shot.snapshots) == 5 for shot in trace.trajectories)
    assert {shot.classical_bits for shot in trace.trajectories} <= {"00", "11"}
    for shot in trace.trajectories:
        assert shot.snapshots[-1].gate == "MEASURE"
        assert sum(shot.snapshots[-1].probabilities.values()) == pytest.approx(1.0)


def test_trajectory_debugger_rejects_backend_without_shot_support():
    from quantum.service.debugger import build_measurement_trajectories

    circuit = Circuit("unsupported-trajectory", 1, (
        Operation("m0", "MEASURE", (0,), classical_bits=(0,)),
    ), num_clbits=1)
    with pytest.raises(QuantumDebugError, match="does not implement shot trajectories"):
        build_measurement_trajectories(circuit, FakeStatevectorBackend(), shots=2)
