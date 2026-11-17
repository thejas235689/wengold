"""Lazy discovery: importing WENGOLD never requires all simulator packages."""
from __future__ import annotations
from .base import BackendUnavailable

def available_backends() -> dict[str, dict[str, object]]:
    import importlib.util
    return {
        "qiskit": {"installed": importlib.util.find_spec("qiskit") is not None, "adapter": "QiskitBackend"},
        "cirq": {"installed": importlib.util.find_spec("cirq") is not None, "adapter": "CirqBackend"},
        "quest": {"installed": importlib.util.find_spec("pyquest") is not None, "adapter": "QuESTBackend",
                  "note": "A compatible pyquest binding is required; native QuEST is not a Python package."},
    }

def create_backend(name: str):
    key = name.lower()
    if key == "qiskit":
        from .qiskit_backend import QiskitBackend
        return QiskitBackend()
    if key == "cirq":
        from .cirq_backend import CirqBackend
        return CirqBackend()
    if key == "quest":
        from .quest_backend import QuESTBackend
        return QuESTBackend()
    raise BackendUnavailable(f"unknown backend: {name}")
