"""Atomic persistence for WENGOLD quantum project files."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .circuit_ir import Circuit, CircuitValidationError, validate_circuit


PROJECT_FORMAT = "wengold.quantum-project"
PROJECT_VERSION = 1


def save_project(path: str | os.PathLike[str], circuit: Circuit, *, metadata: dict[str, Any] | None = None) -> Path:
    validate_circuit(circuit)
    if metadata is not None and not isinstance(metadata, dict):
        raise CircuitValidationError("project metadata must be an object")
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "format": PROJECT_FORMAT,
        "project_version": PROJECT_VERSION,
        "metadata": metadata or {},
        "circuit": circuit.to_dict(),
    }
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return destination


def load_project(path: str | os.PathLike[str]) -> tuple[Circuit, dict[str, Any]]:
    source = Path(path).expanduser()
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CircuitValidationError(f"cannot read quantum project {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise CircuitValidationError("quantum project root must be an object")
    if document.get("format") != PROJECT_FORMAT:
        raise CircuitValidationError("not a WENGOLD quantum project")
    if document.get("project_version") != PROJECT_VERSION:
        raise CircuitValidationError("unsupported WENGOLD quantum project version")
    circuit = Circuit.from_dict(document.get("circuit", {}))
    metadata = document.get("metadata", {})
    if not isinstance(metadata, dict):
        raise CircuitValidationError("project metadata must be an object")
    return circuit, metadata
