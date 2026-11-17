"""Strict OpenQASM 3.0 subset import/export for the WENGOLD circuit IR.

This module intentionally supports an explicit, testable subset. It rejects
control flow, custom gate definitions, opaque pragmas and unsupported syntax
instead of silently dropping semantics.
"""
from __future__ import annotations

import math
import re
import uuid

from .circuit_ir import Circuit, Operation, CircuitValidationError, validate_circuit

_HEADER = re.compile(r"^OPENQASM\s+3(?:\.0)?\s*;$", re.I)
_QREG = re.compile(r"^qubit\[(\d+)\]\s+([A-Za-z_]\w*)\s*;$")
_CREG = re.compile(r"^bit\[(\d+)\]\s+([A-Za-z_]\w*)\s*;$")
_INDEX = r"([A-Za-z_]\w*)\[(\d+)\]"
_PARAM = re.compile(r"^([A-Za-z_]\w*)\s*\((.+)\)\s+(.+)$")
_CALL = re.compile(r"^([A-Za-z_]\w*)\s+(.+)$")


def _angle(expression: str) -> float:
    """Evaluate a small arithmetic expression over numbers and pi only."""
    expression = expression.strip().replace("π", "pi")
    if not re.fullmatch(r"[0-9eE+\-*/(). pi]+", expression):
        raise CircuitValidationError(f"unsupported OpenQASM parameter expression: {expression}")
    try:
        value = eval(expression, {"__builtins__": {}}, {"pi": math.pi})
    except Exception as exc:
        raise CircuitValidationError(f"invalid OpenQASM parameter: {expression}") from exc
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise CircuitValidationError(f"non-finite OpenQASM parameter: {expression}")
    return float(value)


def _operand(token: str, register: str, size: int, line: int) -> int:
    match = re.fullmatch(_INDEX, token.strip())
    if not match or match.group(1) != register:
        raise CircuitValidationError(f"line {line}: expected indexed operand from {register}, got {token!r}")
    index = int(match.group(2))
    if index >= size:
        raise CircuitValidationError(f"line {line}: {register}[{index}] is out of range")
    return index


def import_openqasm3(source: str, *, circuit_id: str | None = None) -> Circuit:
    """Import the supported OpenQASM 3 subset into a validated circuit."""
    if not isinstance(source, str):
        raise TypeError("OpenQASM source must be text")
    lines = []
    for raw in source.splitlines():
        line = raw.split("//", 1)[0].strip()
        if line:
            lines.append(line)
    if not lines or not _HEADER.fullmatch(lines[0]):
        raise CircuitValidationError("OpenQASM 3 source must start with OPENQASM 3.0;")

    qreg = creg = None
    nq = nc = 0
    operations = []
    single = {"id": "I", "i": "I", "h": "H", "x": "X", "y": "Y", "z": "Z",
              "s": "S", "sdg": "SDG", "t": "T", "tdg": "TDG"}
    rotations = {"rx", "ry", "rz"}
    two = {"cx": "CNOT", "cnot": "CNOT", "cz": "CZ", "swap": "SWAP"}
    three = {"ccx": "CCX", "cswap": "CSWAP"}
    seen_header = False

    for line_no, line in enumerate(lines[1:], start=2):
        if line.lower() == "include \"stdgates.inc\";":
            continue
        match = _QREG.fullmatch(line)
        if match:
            if qreg is not None:
                raise CircuitValidationError(f"line {line_no}: multiple quantum registers are not supported")
            nq, qreg = int(match.group(1)), match.group(2)
            if nq < 1:
                raise CircuitValidationError(f"line {line_no}: quantum register must be non-empty")
            continue
        match = _CREG.fullmatch(line)
        if match:
            if creg is not None:
                raise CircuitValidationError(f"line {line_no}: multiple classical registers are not supported")
            nc, creg = int(match.group(1)), match.group(2)
            if nc < 1:
                raise CircuitValidationError(f"line {line_no}: classical register must be non-empty")
            continue
        if qreg is None:
            raise CircuitValidationError(f"line {line_no}: declare a qubit register before operations")

        operation_id = f"qasm_{line_no}"
        lower = line.lower()
        if lower.startswith("measure ") and "->" in lower:
            body = line[:-1] if line.endswith(";") else line
            left, right = body[len("measure "):].split("->", 1)
            if creg is None:
                raise CircuitValidationError(f"line {line_no}: measurement requires a bit register")
            q = _operand(left.strip(), qreg, nq, line_no)
            cbit = _operand(right.strip(), creg, nc, line_no)
            operations.append(Operation(operation_id, "MEASURE", (q,), classical_bits=(cbit,)))
            continue
        assignment = re.fullmatch(rf"{_INDEX}\s*=\s*measure\s+({_INDEX})\s*;", line, re.I)
        if assignment:
            if creg is None:
                raise CircuitValidationError(f"line {line_no}: measurement requires a bit register")
            cbit = _operand(f"{assignment.group(1)}[{assignment.group(2)}]", creg, nc, line_no)
            q = _operand(f"{assignment.group(3)}[{assignment.group(4)}]", qreg, nq, line_no)
            operations.append(Operation(operation_id, "MEASURE", (q,), classical_bits=(cbit,)))
            continue
        if lower.startswith("barrier"):
            operands = [x.strip() for x in line.rstrip(";")[len("barrier"):].split(",")]
            if not operands or operands == [""]:
                operands = [f"{qreg}[{i}]" for i in range(nq)]
            qubits = tuple(_operand(x, qreg, nq, line_no) for x in operands)
            operations.append(Operation(operation_id, "BARRIER", qubits))
            continue
        if lower.startswith("reset "):
            q = _operand(line[:-1].split(None, 1)[1], qreg, nq, line_no)
            operations.append(Operation(operation_id, "RESET", (q,)))
            continue

        parameter_match = _PARAM.fullmatch(line.rstrip(";"))
        if parameter_match:
            gate = parameter_match.group(1).lower()
            if gate not in rotations:
                raise CircuitValidationError(f"line {line_no}: unsupported parameterized gate {gate}")
            params = (_angle(parameter_match.group(2)),)
            operands = [x.strip() for x in parameter_match.group(3).split(",")]
        else:
            call = _CALL.fullmatch(line.rstrip(";"))
            if not call:
                raise CircuitValidationError(f"line {line_no}: unsupported OpenQASM statement: {line}")
            gate = call.group(1).lower()
            params = ()
            operands = [x.strip() for x in call.group(2).split(",")]

        if gate in single or gate in rotations:
            if len(operands) != 1:
                raise CircuitValidationError(f"line {line_no}: {gate} expects one qubit")
            q = _operand(operands[0], qreg, nq, line_no)
            operations.append(Operation(operation_id, single.get(gate, gate.upper()), (q,), params=params))
        elif gate in two:
            if len(operands) != 2:
                raise CircuitValidationError(f"line {line_no}: {gate} expects two qubits")
            a, b = (_operand(x, qreg, nq, line_no) for x in operands)
            mapped = two[gate]
            operations.append(Operation(operation_id, mapped, (b,), (a,)) if mapped == "CNOT"
                              else Operation(operation_id, mapped, (a, b)))
        elif gate in three:
            if len(operands) != 3:
                raise CircuitValidationError(f"line {line_no}: {gate} expects three qubits")
            a, b, c = (_operand(x, qreg, nq, line_no) for x in operands)
            mapped = three[gate]
            operations.append(Operation(operation_id, mapped, (c,), (a, b)) if mapped == "CCX"
                              else Operation(operation_id, mapped, (b, c), (a,)))
        else:
            raise CircuitValidationError(f"line {line_no}: unsupported OpenQASM gate {gate}")

    if qreg is None:
        raise CircuitValidationError("OpenQASM source has no qubit register")
    circuit = Circuit(circuit_id or f"qasm-{uuid.uuid4().hex[:12]}", nq,
                      tuple(operations), num_clbits=nc)
    validate_circuit(circuit)
    return circuit


def export_openqasm3(circuit: Circuit) -> str:
    """Export the supported WENGOLD IR subset; fail on unrepresentable operations."""
    validate_circuit(circuit)
    if circuit.num_clbits:
        declarations = [f"bit[{circuit.num_clbits}] c;"]
    else:
        declarations = []
    lines = ["OPENQASM 3.0;", 'include "stdgates.inc";',
             f"qubit[{circuit.num_qubits}] q;"] + declarations
    simple = {"I": "id", "H": "h", "X": "x", "Y": "y", "Z": "z",
              "S": "s", "SDG": "sdg", "T": "t", "TDG": "tdg"}
    for op in circuit.operations:
        gate = op.gate.upper()
        targets = [f"q[{q}]" for q in op.targets]
        controls = [f"q[{q}]" for q in op.controls]
        if gate in simple:
            lines.append(f"{simple[gate]} {targets[0]};")
        elif gate in {"RX", "RY", "RZ"}:
            lines.append(f"{gate.lower()}({op.params[0]}) {targets[0]};")
        elif gate in {"CNOT", "CX"}:
            lines.append(f"cx {controls[0]}, {targets[0]};")
        elif gate in {"CZ", "SWAP"}:
            lines.append(f"{gate.lower()} {targets[0]}, {targets[1]};")
        elif gate in {"CCX", "TOFFOLI"}:
            lines.append(f"ccx {controls[0]}, {controls[1]}, {targets[0]};")
        elif gate == "CSWAP":
            lines.append(f"cswap {controls[0]}, {targets[0]}, {targets[1]};")
        elif gate == "MEASURE":
            for q, cbit in zip(op.targets, op.classical_bits):
                lines.append(f"c[{cbit}] = measure q[{q}];")
        elif gate == "RESET":
            lines.extend(f"reset {q};" for q in targets)
        elif gate == "BARRIER":
            lines.append("barrier " + ", ".join(targets) + ";")
        else:
            raise CircuitValidationError(f"OpenQASM exporter does not support {gate}")
    return "\n".join(lines) + "\n"
