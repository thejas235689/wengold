"""Backend-neutral statevector visualization data.

Qubit zero is the least-significant basis bit. The Bloch vectors are reduced
single-qubit states, so entangled qubits may lie inside the Bloch sphere.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class BlochVector:
    qubit: int
    x: float
    y: float
    z: float
    purity: float


@dataclass(frozen=True)
class QSpherePoint:
    basis_index: int
    basis: str
    probability: float
    phase: float
    theta: float
    phi: float


def _coerce_statevector(statevector: Iterable[complex | Iterable[float]], *, tolerance: float = 1e-8):
    import numpy as np

    values = []
    for value in statevector:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            values.append(complex(float(value[0]), float(value[1])))
        else:
            values.append(complex(value))
    state = np.asarray(values, dtype=np.complex128)
    if state.ndim != 1 or state.size < 2 or state.size & (state.size - 1):
        raise ValueError("statevector length must be a power of two and at least two")
    if not np.all(np.isfinite(state.real)) or not np.all(np.isfinite(state.imag)):
        raise ValueError("statevector amplitudes must be finite")
    norm = float(np.vdot(state, state).real)
    if not math.isfinite(norm) or abs(norm - 1.0) > tolerance:
        raise ValueError(f"statevector must be normalized (norm={norm:.12g})")
    return state


def bloch_vectors(statevector: Iterable[complex | Iterable[float]], *, tolerance: float = 1e-8) -> list[BlochVector]:
    """Return each qubit's reduced-state Bloch vector in canonical q0-LSB order."""
    state = _coerce_statevector(statevector, tolerance=tolerance)
    nqubits = int(math.log2(state.size))
    output = []
    for qubit in range(nqubits):
        mask = 1 << qubit
        rho01 = 0j
        p0 = p1 = 0.0
        for index in range(state.size):
            if index & mask:
                continue
            a0 = state[index]
            a1 = state[index | mask]
            p0 += float(abs(a0) ** 2)
            p1 += float(abs(a1) ** 2)
            rho01 += a0 * a1.conjugate()
        x = 2.0 * rho01.real
        y = -2.0 * rho01.imag
        z = p0 - p1
        purity = (1.0 + x*x + y*y + z*z) / 2.0
        output.append(BlochVector(qubit, x, y, z, purity))
    return output


def qsphere_points(statevector: Iterable[complex | Iterable[float]], *, probability_cutoff: float = 1e-12) -> list[QSpherePoint]:
    """Map basis amplitudes onto Q-sphere coordinates.

    Latitude is determined by Hamming weight; longitude is phase relative to
    the largest-magnitude amplitude, making the display global-phase invariant.
    """
    state = _coerce_statevector(statevector)
    if not math.isfinite(probability_cutoff) or probability_cutoff < 0:
        raise ValueError("probability_cutoff must be finite and non-negative")
    nqubits = int(math.log2(state.size))
    reference = state[int(abs(state).argmax())]
    reference_phase = math.atan2(reference.imag, reference.real)
    points = []
    for index, amplitude in enumerate(state):
        probability = float(abs(amplitude) ** 2)
        if probability <= probability_cutoff:
            continue
        weight = index.bit_count()
        theta = math.acos(max(-1.0, min(1.0, 1.0 - 2.0 * weight / nqubits)))
        phase = math.atan2(amplitude.imag, amplitude.real) - reference_phase
        phase = (phase + math.pi) % (2.0 * math.pi) - math.pi
        points.append(QSpherePoint(
            index, format(index, f"0{nqubits}b"), probability, phase, theta, phase
        ))
    return points
