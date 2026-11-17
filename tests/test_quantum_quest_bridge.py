import pytest

from quantum.backends.base import BackendUnavailable
from quantum.backends.quest_backend import QuESTBackend, _quest_bridge
from quantum.core.circuit_ir import Circuit, Operation


def test_quest_is_explicitly_unavailable_without_compiled_extension():
    if _quest_bridge is not None:
        pytest.skip("native QuEST extension is installed in this test environment")
    with pytest.raises(BackendUnavailable, match="bridge is not built"):
        QuESTBackend()


@pytest.mark.skipif(_quest_bridge is None, reason="optional QuEST native extension not built")
def test_quest_bell_statevector_and_terminal_measurement():
    backend = QuESTBackend()
    bell = Circuit("quest-bell", 2, (
        Operation("h0", "H", (0,)),
        Operation("cx", "CNOT", (1,), (0,)),
    ))
    result = backend.run(bell)
    assert result.probabilities["00"] == pytest.approx(0.5, abs=1e-8)
    assert result.probabilities["11"] == pytest.approx(0.5, abs=1e-8)
    measured = Circuit("quest-measure", 2, bell.operations + (
        Operation("measure", "MEASURE", (0, 1), classical_bits=(0, 1)),
    ), num_clbits=2)
    sampled = backend.run(measured, shots=512, seed=17)
    assert set(sampled.counts).issubset({"00", "11"})
    assert sum(sampled.counts.values()) == 512


@pytest.mark.skipif(_quest_bridge is None, reason="optional QuEST native extension not built")
def test_quest_qubit_zero_uses_rightmost_bit():
    backend = QuESTBackend()
    circuit = Circuit("quest-q0", 2, (Operation("x0", "X", (0,)),))
    result = backend.run(circuit)
    assert result.probabilities["01"] == pytest.approx(1.0, abs=1e-8)
