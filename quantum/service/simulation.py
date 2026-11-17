"""Synchronous local simulation service; GUI callers should dispatch it to a worker."""
from quantum.core.circuit_ir import Circuit, validate_circuit
from quantum.backends import create_backend

def run_circuit(circuit: Circuit, backend: str, *, shots: int = 1024, seed: int | None = None):
    validate_circuit(circuit)
    if shots < 1: raise ValueError("shots must be positive")
    engine=create_backend(backend)
    return engine.run(circuit,shots=shots,seed=seed)
