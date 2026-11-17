"""Cirq adapter for common unitary gates and measurement sampling."""
from __future__ import annotations
import time, uuid
from .base import Backend, BackendUnavailable, SimulationResult
from quantum.core.circuit_ir import Circuit

class CirqBackend(Backend):
    name = "cirq"
    def __init__(self):
        try: import cirq
        except ImportError as exc: raise BackendUnavailable("Install Cirq: pip install 'wengold[quantum]'") from exc
        self.cirq=cirq
    def capabilities(self):
        return {"statevector": True, "sampling": True, "noise": "adapter extension required", "hardware": False,
                "supported_gates": ["I","H","X","Y","Z","S","T","RX","RY","RZ","CNOT","CX","CZ","SWAP","MEASURE"]}
    def run(self,circuit:Circuit,*,shots=1024,seed=None):
        c=self.cirq; qubits=[c.LineQubit(i) for i in range(circuit.num_qubits)]; ops=[]; measured=False
        for op in circuit.operations:
            g=op.gate.upper(); t=[qubits[i] for i in op.targets]; controls=[qubits[i] for i in op.controls]; p=op.params
            if g=="MEASURE": ops.append(c.measure(*t,key="m")); measured=True
            elif g in {"CNOT","CX"}: ops.append(c.CNOT(controls[0] if controls else t[0],t[-1]))
            elif g=="CZ": ops.append(c.CZ(*(controls+t)))
            elif g=="SWAP": ops.append(c.SWAP(*t))
            elif g in {"I","H","X","Y","Z","S","T","RX","RY","RZ"}:
                gate={"I":c.I,"H":c.H,"X":c.X,"Y":c.Y,"Z":c.Z,"S":c.S,"T":c.T}.get(g)
                if gate is None: gate={"RX":c.rx,"RY":c.ry,"RZ":c.rz}[g](float(p[0]))
                ops.append(gate.on(t[0]))
            else: raise BackendUnavailable(f"Cirq adapter does not support {g}")
        circuit_obj=c.Circuit(ops); start=time.perf_counter(); sim=c.Simulator(seed=seed)
        if measured:
            result=sim.run(circuit_obj,repetitions=shots); rows=result.measurements["m"]
            counts={}
            for row in rows:
                key="".join(str(int(bit)) for bit in row)
                counts[key]=counts.get(key,0)+1
            total=sum(counts.values()) or 1
            probs={k:v/total for k,v in counts.items()}; state=None
        else:
            state=sim.simulate(circuit_obj).final_state_vector
            probs={format(i,f"0{circuit.num_qubits}b"):float(abs(a)**2) for i,a in enumerate(state)}
            counts={};
        elapsed=(time.perf_counter()-start)*1000
        encoded=[[float(a.real),float(a.imag)] for a in state] if state is not None else None
        return SimulationResult(uuid.uuid4().hex,self.name,"COMPLETED",shots if measured else None,
            statevector=encoded,probabilities=probs,counts=counts,execution_time_ms=elapsed,
            metadata={"method":"cirq_simulator","qubit_order":"little_endian_line_qubits"})
