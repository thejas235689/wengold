"""Backend-independent mathematical checks for state and gate data."""
from __future__ import annotations
import math

def state_norm(amplitudes: list[complex]) -> float:
    return sum(abs(a)**2 for a in amplitudes)

def is_normalized(amplitudes: list[complex], *, atol: float = 1e-10) -> bool:
    return math.isclose(state_norm(amplitudes),1.0,rel_tol=0.0,abs_tol=atol)

def pure_state_fidelity(a: list[complex], b: list[complex]) -> float:
    if len(a)!=len(b) or not a: raise ValueError("statevectors must have equal non-zero length")
    na=state_norm(a); nb=state_norm(b)
    if na==0 or nb==0: raise ValueError("zero vector is not a valid quantum state")
    overlap=sum(x.conjugate()*y for x,y in zip(a,b))
    return min(1.0,max(0.0,(abs(overlap)**2)/(na*nb)))

def unitary_residual(matrix: list[list[complex]]) -> float:
    n=len(matrix)
    if n==0 or any(len(row)!=n for row in matrix): raise ValueError("matrix must be non-empty and square")
    worst=0.0
    for i in range(n):
        for j in range(n):
            value=sum(matrix[k][i].conjugate()*matrix[k][j] for k in range(n))
            expected=1.0 if i==j else 0.0
            worst=max(worst,abs(value-expected))
    return worst
