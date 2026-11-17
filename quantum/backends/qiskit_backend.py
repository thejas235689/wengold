"""Qiskit adapter. Supports the unitary gate subset; measurement is sampled by Qiskit."""
from __future__ import annotations
import time, uuid
from .base import Backend, BackendUnavailable, SimulationResult
from quantum.core.circuit_ir import Circuit

class QiskitBackend(Backend):
    name = "qiskit"
    def __init__(self):
        try:
            from qiskit import QuantumCircuit
        except ImportError as exc:
            raise BackendUnavailable("Install the optional Qiskit dependencies: pip install 'wengold[quantum]'") from exc
        self._qc_type = QuantumCircuit
    def capabilities(self):
        return {"statevector": False, "sampling": True, "noise": False, "hardware": False,
                "supported_gates": ["I","H","X","Y","Z","S","SDG","T","TDG","SX","RX","RY","RZ","CNOT","CX","CZ","SWAP","CCX","MEASURE","RESET","BARRIER"]}
    def run(self, circuit: Circuit, *, shots=1024, seed=None):
        from qiskit import transpile
        from qiskit_aer import AerSimulator
        start=time.perf_counter(); qc=self._qc_type(circuit.num_qubits, circuit.num_clbits)
        for op in circuit.operations:
            g=op.gate.upper(); t=list(op.targets); c=list(op.controls); q=t+c; p=op.params
            if g in {"CNOT","CX"}: qc.cx(c[0] if c else t[0], t[-1])
            elif g=="CCX": qc.ccx(*q)
            elif g=="MEASURE":
                for qb,cb in zip(t,op.classical_bits): qc.measure(qb,cb)
            elif g=="BARRIER": qc.barrier(*t)
            elif g=="RESET":
                for qb in t: qc.reset(qb)
            elif g in {"I","H","X","Y","Z","S","SDG","T","TDG","SX","RX","RY","RZ","CZ","SWAP"}:
                method={"I":"id","SDG":"sdg","TDG":"tdg"}.get(g,g.lower())
                fn=getattr(qc,method,None)
                if fn is None: raise BackendUnavailable(f"Qiskit gate not mapped: {g}")
                if g in {"RX","RY","RZ"}: fn(float(p[0]),t[0])
                elif g in {"CZ","SWAP"}: fn(*q)
                else: fn(t[0])
            else: raise BackendUnavailable(f"Qiskit adapter does not support {g}")
        if circuit.num_clbits == 0:
            qc.measure_all()
        sim=AerSimulator(seed_simulator=seed)
        compiled=transpile(qc,sim)
        counts=sim.run(compiled,shots=shots).result().get_counts()
        elapsed=(time.perf_counter()-start)*1000
        normalized={str(k).replace(" ",""):int(v) for k,v in counts.items()}
        total=sum(normalized.values()) or 1
        return SimulationResult(uuid.uuid4().hex,self.name,"COMPLETED",shots,
            probabilities={k:v/total for k,v in normalized.items()},counts=normalized,
            execution_time_ms=elapsed,metadata={"method":"aer_sampling","statevector_exposed":False})
