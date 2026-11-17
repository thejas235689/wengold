import math
import numpy as np
import pytest

from quantum.visualization.state import bloch_vectors, qsphere_points


def test_zero_and_one_qubit_bloch_vectors():
    zero = bloch_vectors([1 + 0j, 0 + 0j])[0]
    assert (zero.x, zero.y, zero.z) == pytest.approx((0, 0, 1))
    one = bloch_vectors([0 + 0j, 1 + 0j])[0]
    assert (one.x, one.y, one.z) == pytest.approx((0, 0, -1))


def test_plus_i_state_has_positive_y_bloch_component():
    vector = bloch_vectors([1 / math.sqrt(2), 1j / math.sqrt(2)])[0]
    assert (vector.x, vector.y, vector.z) == pytest.approx((0, 1, 0))


def test_bell_pair_reduced_bloch_vectors_are_mixed_at_origin():
    state = [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)]
    vectors = bloch_vectors(state)
    for vector in vectors:
        assert (vector.x, vector.y, vector.z) == pytest.approx((0, 0, 0))
        assert vector.purity == pytest.approx(0.5)


def test_qsphere_points_use_relative_phase_and_hamming_weight():
    state = [1 / math.sqrt(2), 0, 0, 1j / math.sqrt(2)]
    points = qsphere_points(state)
    assert [point.basis for point in points] == ["00", "11"]
    assert points[0].probability == pytest.approx(0.5)
    assert points[1].phase == pytest.approx(math.pi / 2)
    assert points[0].theta == pytest.approx(0)
    assert points[1].theta == pytest.approx(math.pi)


def test_qsphere_is_invariant_to_global_phase():
    state = np.array([1, 1j], dtype=np.complex128) / math.sqrt(2)
    rotated = state * np.exp(1.234j)
    first = qsphere_points(state)
    second = qsphere_points(rotated)
    assert [p.phase for p in first] == pytest.approx([p.phase for p in second])


def test_visualization_rejects_unnormalized_and_nonfinite_states():
    with pytest.raises(ValueError, match="normalized"):
        bloch_vectors([1, 1])
    with pytest.raises(ValueError, match="finite"):
        qsphere_points([complex(float("nan"), 0), 0])


def test_qsphere_caps_large_basis_state_display():
    state = [0.5, 0.5, 0.5, 0.5]
    points = qsphere_points(state, max_points=2)
    assert len(points) == 2
    assert [point.basis_index for point in points] == sorted(
        point.basis_index for point in points
    )
