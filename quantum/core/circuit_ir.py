"""Versioned backend-neutral circuit IR. Logical qubits are zero-based."""
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
    """Raised when a circuit cannot be represented safely by the current IR."""


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
        return {
            "id": self.id, "gate": self.gate.upper(), "targets": list(self.targets),
            "controls": list(self.controls), "params": list(self.params),
            "classical_bits": list(self.classical_bits), "metadata": self.metadata,
        }


@dataclass(frozen=True)
class Circuit:
    circuit_id: str
    num_qubits: int
    operations: tuple[Operation, ...] = ()
    num_clbits: int = 0
    schema_version: str = SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "circuit_id": self.circuit_id,
            "num_qubits": self.num_qubits, "num_clbits": self.num_clbits,
            "operations": [op.to_dict() for op in self.operations], "metadata": self.metadata,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Circuit":
        if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise CircuitValidationError("unsupported circuit schema_version")
        try:
            operations = tuple(
                Operation(
                    id=str(item["id"]), gate=str(item["gate"]).upper(),
                    targets=tuple(int(value) for value in item.get("targets", [])),
                    controls=tuple(int(value) for value in item.get("controls", [])),
                    params=tuple(item.get("params", [])),
                    classical_bits=tuple(int(value) for value in item.get("classical_bits", [])),
                    metadata=dict(item.get("metadata", {})),
                )
                for item in data.get("operations", [])
            )
            circuit = cls(
                str(data["circuit_id"]), int(data["num_qubits"]), operations,
                int(data.get("num_clbits", 0)), SCHEMA_VERSION, dict(data.get("metadata", {})),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CircuitValidationError(f"malformed circuit document: {exc}") from exc
        validate_circuit(circuit)
        return circuit


def validate_circuit(circuit: Circuit) -> None:
    if not circuit.circuit_id.strip():
        raise CircuitValidationError("circuit_id must not be empty")
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
        if any(not isinstance(value, (int, float, str)) or isinstance(value, bool) for value in op.params):
            raise CircuitValidationError(f"invalid parameter in {op.id}")
        qubits = op.targets + op.controls
        if not qubits or any(q < 0 or q >= circuit.num_qubits for q in qubits):
            raise CircuitValidationError(f"invalid qubit operand in {op.id}")
        if len(set(qubits)) != len(qubits):
            raise CircuitValidationError(f"qubit repeated within operation {op.id}")

        if gate in {"CNOT", "CX"} and (len(op.controls), len(op.targets)) != (1, 1):
            raise CircuitValidationError(f"{gate} requires exactly one control and one target")
        if gate in {"CCX", "TOFFOLI"} and (len(op.controls), len(op.targets)) != (2, 1):
            raise CircuitValidationError(f"{gate} requires exactly two controls and one target")
        if gate == "CSWAP" and (len(op.controls), len(op.targets)) != (1, 2):
            raise CircuitValidationError("CSWAP requires exactly one control and two targets")
        if gate in {"CZ", "SWAP", "ISWAP", "RXX", "RYY", "RZZ"} and (
            len(op.controls) != 0 or len(op.targets) != 2
        ):
            raise CircuitValidationError(f"{gate} requires exactly two targets and no controls")
        if gate in SINGLE_QUBIT and (len(op.targets), len(op.controls)) != (1, 0):
            raise CircuitValidationError(f"{gate} requires exactly one target and no controls")
        if gate in {"RX", "RY", "RZ", "RXX", "RYY", "RZZ"}:
            if len(op.params) != 1 or not isinstance(op.params[0], (int, float)):
                raise CircuitValidationError(f"{gate} requires one numeric rotation parameter")
        elif op.params:
            raise CircuitValidationError(f"{gate} does not accept parameters in schema {SCHEMA_VERSION}")

        if gate == "MEASURE":
            if len(op.targets) != len(op.classical_bits) or not op.targets or op.controls:
                raise CircuitValidationError("MEASURE needs one classical bit per target qubit")
            if any(bit < 0 or bit >= circuit.num_clbits for bit in op.classical_bits):
                raise CircuitValidationError("measurement classical bit out of range")
        elif op.classical_bits:
            raise CircuitValidationError(f"classical_bits are only valid on MEASURE operations")
        if gate in {"BARRIER", "DELAY"} and not op.targets:
            raise CircuitValidationError(f"{gate} requires at least one target")
        if gate in {"RESET", "BARRIER", "DELAY"} and op.controls:
            raise CircuitValidationError(f"{gate} does not accept controls")
