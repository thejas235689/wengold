"""Small versioned quantum circuit IR. Qubit indices are zero-based logical indices."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import json

SCHEMA_VERSION = "1.0"
SINGLE_QUBIT = {"I", "H", "X", "Y", "Z", "S", "SDG", "T", "TDG", "SX", "RX", "RY", "RZ"}
TWO_QUBIT = {"CNOT", "CX", "CZ", "SWAP", "ISWAP", "RXX", "RYY", "RZZ"}
THREE_QUBIT = {"CCX", "TOFFOLI", "CSWAP"}
NON_UNITARY = {"MEASURE", "RESET", "BARRIER", "DELAY"}

class CircuitValidationError(ValueError):
    pass

@dataclass(frozen=True)
class Operation:
    id: str
    gate: str
    targets: tuple[int, ...] = ()
    controls: tuple[int, ...] = ()
    params: tuple[float | str, ...] = ()
    classical_bits: tuple[int, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "gate": self.gate.upper(), "targets": list(self.targets),
                "controls": list(self.controls), "params": list(self.params),
                "classical_bits": list(self.classical_bits), "metadata": self.metadata}

@dataclass(frozen=True)
class Circuit:
    circuit_id: str
    num_qubits: int
    operations: tuple[Operation, ...] = ()
    num_clbits: int = 0
    schema_version: str = SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "circuit_id": self.circuit_id,
                "num_qubits": self.num_qubits, "num_clbits": self.num_clbits,
                "operations": [op.to_dict() for op in self.operations], "metadata": self.metadata}

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Circuit":
        if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise CircuitValidationError("unsupported circuit schema_version")
        ops = tuple(Operation(id=str(o["id"]), gate=str(o["gate"]).upper(),
            targets=tuple(int(x) for x in o.get("targets", [])),
            controls=tuple(int(x) for x in o.get("controls", [])),
            params=tuple(o.get("params", [])),
            classical_bits=tuple(int(x) for x in o.get("classical_bits", [])),
            metadata=dict(o.get("metadata", {}))) for o in data.get("operations", []))
        circuit = cls(str(data["circuit_id"]), int(data["num_qubits"]), ops,
                      int(data.get("num_clbits", 0)), SCHEMA_VERSION,
                      dict(data.get("metadata", {})))
        validate_circuit(circuit)
        return circuit

def validate_circuit(circuit: Circuit) -> None:
    if circuit.num_qubits < 1 or circuit.num_clbits < 0:
        raise CircuitValidationError("num_qubits must be positive and num_clbits non-negative")
    if circuit.schema_version != SCHEMA_VERSION:
        raise CircuitValidationError("unsupported schema version")
    seen: set[str] = set()
    for op in circuit.operations:
        gate = op.gate.upper()
        if not op.id or op.id in seen:
            raise CircuitValidationError(f"missing or duplicate operation id: {op.id!r}")
        seen.add(op.id)
        if gate not in SINGLE_QUBIT | TWO_QUBIT | THREE_QUBIT | NON_UNITARY:
            raise CircuitValidationError(f"unsupported gate: {gate}")
        qubits = op.targets + op.controls
        if not qubits or any(q < 0 or q >= circuit.num_qubits for q in qubits):
            raise CircuitValidationError(f"invalid qubit operand in {op.id}")
        if len(set(qubits)) != len(qubits):
            raise CircuitValidationError(f"qubit repeated within operation {op.id}")
        expected = 1 if gate in SINGLE_QUBIT else 2 if gate in TWO_QUBIT else 3 if gate in THREE_QUBIT else None
        if expected is not None and len(op.targets) + len(op.controls) != expected:
            raise CircuitValidationError(f"{gate} expects {expected} qubit operands")
        if gate in {"RX", "RY", "RZ", "RXX", "RYY", "RZZ"} and len(op.params) != 1:
            raise CircuitValidationError(f"{gate} requires one rotation parameter")
        if gate == "MEASURE":
            if len(op.targets) != len(op.classical_bits) or not op.targets:
                raise CircuitValidationError("MEASURE needs one classical bit per target qubit")
            if any(b < 0 or b >= circuit.num_clbits for b in op.classical_bits):
                raise CircuitValidationError("measurement classical bit out of range")
        if gate in {"BARRIER", "DELAY"} and not op.targets:
            raise CircuitValidationError(f"{gate} requires at least one target")
