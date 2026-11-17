"""Optional quantum simulation backend adapters."""
from .base import Backend, BackendUnavailable, SimulationResult
from .registry import available_backends, create_backend
__all__ = ["Backend", "BackendUnavailable", "SimulationResult", "available_backends", "create_backend"]
