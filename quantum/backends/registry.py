"""Lazy backend discovery; unavailable engines are never advertised as runnable."""
from __future__ import annotations
import importlib.util

from .base import BackendUnavailable


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def available_backends() -> dict[str, dict[str, object]]:
    qiskit_ready = _installed("qiskit") and _installed("qiskit_aer")
    cirq_ready = _installed("cirq")
    quest_ready = _installed("quantum.backends._quest_bridge")
    return {
        "qiskit": {
            "installed": qiskit_ready,
            "missing_dependencies": [] if qiskit_ready else [
                name for name, ok in (("qiskit", _installed("qiskit")),
                                      ("qiskit-aer", _installed("qiskit_aer"))) if not ok
            ],
            "adapter": "QiskitBackend",
        },
        "cirq": {"installed": cirq_ready, "adapter": "CirqBackend"},
        "quest": {
            "installed": quest_ready,
            "adapter": "QuESTBackend",
            "status": "ready" if quest_ready else "not_built",
            "note": "WENGOLD QuEST v4 native bridge detected." if quest_ready else
                    "Build the optional WENGOLD QuEST v4 native bridge to enable execution.",
        },
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
