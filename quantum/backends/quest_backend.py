"""QuEST adapter placeholder with explicit capability gating.

QuEST is a native C/C++ simulator. A supported Python binding or WENGOLD-owned
pybind11 bridge must be built and ABI-tested before execution is enabled.
"""
from .base import Backend, BackendUnavailable, SimulationResult
from quantum.core.circuit_ir import Circuit
class QuESTBackend(Backend):
    name="quest"
    def __init__(self):
        raise BackendUnavailable("QuEST execution is not enabled: build and install the WENGOLD QuEST native bridge first. See docs/quantum/architecture.md.")
    def capabilities(self): return {"statevector":True,"density_matrix":True,"gpu":"build-dependent","mpi":"build-dependent"}
    def run(self,circuit:Circuit,*,shots=1024,seed=None)->SimulationResult:
        raise BackendUnavailable("QuEST native bridge unavailable")
