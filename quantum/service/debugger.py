"""Gate-by-gate statevector replay with bounded, opt-in checkpoint caching.

The debugger supports unitary-only circuits. It replays prefixes and captures
state snapshots; measurement/reset trajectories require a separate model.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import threading
from typing import Any

from quantum.core.circuit_ir import Circuit, NON_UNITARY, Operation, validate_circuit


class QuantumDebugError(ValueError):
    """Raised when a circuit cannot be represented safely as a statevector trace."""


@dataclass(frozen=True)
class DebugSnapshot:
    """State after one circuit boundary; index zero is the initial state."""

    step: int
    operation_id: str | None
    gate: str
    statevector: tuple[tuple[float, float], ...]
    probabilities: dict[str, float]
    execution_time_ms: float | None = None


@dataclass(frozen=True)
class QuantumDebugTrace:
    circuit_id: str
    backend: str
    snapshots: tuple[DebugSnapshot, ...]

    @property
    def num_steps(self) -> int:
        return max(0, len(self.snapshots) - 1)

    def snapshot(self, step: int) -> DebugSnapshot:
        if step < 0 or step >= len(self.snapshots):
            raise IndexError(f"debug step {step} outside 0..{len(self.snapshots) - 1}")
        return self.snapshots[step]


# Store only immutable numerical payloads. Bound memory use and serialize cache
# access because Qt workers may build traces concurrently.
_CACHE_MAX_ENTRIES = 512
_CHECKPOINT_CACHE: OrderedDict[str, tuple[
    tuple[tuple[float, float], ...], tuple[tuple[str, float], ...]
]] = OrderedDict()
_CACHE_LOCK = threading.RLock()
_CACHE_HITS = 0
_CACHE_MISSES = 0


def clear_debug_checkpoint_cache() -> None:
    """Clear all cached statevector checkpoints and reset cache counters."""
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        _CHECKPOINT_CACHE.clear()
        _CACHE_HITS = _CACHE_MISSES = 0


def debug_checkpoint_cache_info() -> dict[str, int]:
    """Return a stable snapshot of cache size, capacity, hits and misses."""
    with _CACHE_LOCK:
        return {
            "size": len(_CHECKPOINT_CACHE),
            "max_entries": _CACHE_MAX_ENTRIES,
            "hits": _CACHE_HITS,
            "misses": _CACHE_MISSES,
        }


def _checkpoint_key(circuit: Circuit, operations: tuple[Operation, ...],
                    backend: Any, seed: int | None) -> str:
    # Backend implementations can expose cache_identity when simulator options
    # affect semantics. Otherwise isolate entries to this backend instance.
    identity = getattr(backend, "cache_identity", None)
    if identity is None:
        identity = (type(backend).__module__, type(backend).__qualname__, id(backend))
    payload = repr((
        identity, getattr(backend, "name", "unknown"), seed,
        circuit.num_qubits, circuit.num_clbits, circuit.schema_version,
        operations, tuple(sorted((circuit.metadata or {}).items())),
    )).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _cache_get(key: str):
    global _CACHE_HITS, _CACHE_MISSES
    with _CACHE_LOCK:
        value = _CHECKPOINT_CACHE.get(key)
        if value is None:
            _CACHE_MISSES += 1
            return None
        _CHECKPOINT_CACHE.move_to_end(key)
        _CACHE_HITS += 1
        return value


def _cache_put(key: str, statevector, probabilities) -> None:
    with _CACHE_LOCK:
        _CHECKPOINT_CACHE[key] = (statevector, tuple(sorted(probabilities.items())))
        _CHECKPOINT_CACHE.move_to_end(key)
        while len(_CHECKPOINT_CACHE) > _CACHE_MAX_ENTRIES:
            _CHECKPOINT_CACHE.popitem(last=False)


def build_debug_trace(
    circuit: Circuit,
    backend: Any,
    *,
    seed: int | None = 7,
    use_cache: bool = True,
) -> QuantumDebugTrace:
    """Replay each unitary prefix and capture its statevector.

    Checkpoints are cached by backend identity, seed, circuit dimensions,
    metadata and exact operation prefix. Set use_cache=False for debugging
    backend nondeterminism or bypassing potentially stateful simulator options.
    """
    validate_circuit(circuit)
    for operation in circuit.operations:
        if operation.gate.upper() in NON_UNITARY:
            raise QuantumDebugError(
                f"{operation.gate.upper()} at operation {operation.id!r} "
                "is not supported by the statevector debugger"
            )

    boundaries = [(None, "INITIAL")]
    boundaries.extend((op.id, op.gate.upper()) for op in circuit.operations)

    # Prefer adapters that can expose all operation-boundary snapshots from
    # one simulator execution. The prefix replay path remains the compatibility
    # fallback for adapters without incremental support.
    incremental = getattr(backend, "run_incremental", None)
    if callable(incremental):
        prefixes = [tuple(circuit.operations[:step]) for step in range(len(boundaries))]
        keys = [_checkpoint_key(circuit, prefix, backend, seed) for prefix in prefixes]
        cached_values = [_cache_get(key) for key in keys] if use_cache else [None] * len(keys)
        if use_cache and all(value is not None for value in cached_values):
            snapshots = [
                DebugSnapshot(
                    step=step, operation_id=boundaries[step][0], gate=boundaries[step][1],
                    statevector=value[0], probabilities=dict(value[1]), execution_time_ms=None,
                )
                for step, value in enumerate(cached_values)
            ]
        else:
            results = incremental(circuit, seed=seed)
            if len(results) != len(boundaries):
                raise QuantumDebugError(
                    f"backend {getattr(backend, 'name', 'unknown')!r} returned "
                    f"{len(results)} incremental snapshots; expected {len(boundaries)}"
                )
            snapshots = []
            for step, (operation_id, gate) in enumerate(boundaries):
                result = results[step]
                if result.statevector is None:
                    raise QuantumDebugError(
                        f"backend {result.backend!r} did not return a statevector at step {step}"
                    )
                vector = tuple((float(pair[0]), float(pair[1])) for pair in result.statevector)
                probabilities = dict(result.probabilities or {})
                if use_cache:
                    _cache_put(keys[step], vector, probabilities)
                snapshots.append(DebugSnapshot(
                    step=step, operation_id=operation_id, gate=gate,
                    statevector=vector, probabilities=probabilities,
                    execution_time_ms=result.execution_time_ms,
                ))
        return QuantumDebugTrace(
            circuit_id=circuit.circuit_id,
            backend=getattr(backend, "name", "unknown"),
            snapshots=tuple(snapshots),
        )

    snapshots: list[DebugSnapshot] = []
    prefixes: list[Operation] = []

    for step, (operation_id, gate) in enumerate(boundaries):
        if step:
            prefixes.append(circuit.operations[step - 1])
        prefix = tuple(prefixes)
        key = _checkpoint_key(circuit, prefix, backend, seed) if use_cache else None
        cached = _cache_get(key) if key is not None else None
        if cached is not None:
            vector, cached_probabilities = cached
            probabilities = dict(cached_probabilities)
            execution_time_ms = None
        else:
            prefix_circuit = Circuit(
                circuit_id=f"{circuit.circuit_id}:debug:{step}",
                num_qubits=circuit.num_qubits,
                operations=prefix,
                num_clbits=circuit.num_clbits,
                schema_version=circuit.schema_version,
                metadata=dict(circuit.metadata),
            )
            result = backend.run(prefix_circuit, shots=1, seed=seed)
            if result.statevector is None:
                raise QuantumDebugError(
                    f"backend {result.backend!r} did not return a statevector at step {step}"
                )
            vector = tuple((float(pair[0]), float(pair[1])) for pair in result.statevector)
            probabilities = dict(result.probabilities or {})
            execution_time_ms = result.execution_time_ms
            if key is not None:
                _cache_put(key, vector, probabilities)

        snapshots.append(DebugSnapshot(
            step=step,
            operation_id=operation_id,
            gate=gate,
            statevector=vector,
            probabilities=probabilities,
            execution_time_ms=execution_time_ms,
        ))

    return QuantumDebugTrace(
        circuit_id=circuit.circuit_id,
        backend=getattr(backend, "name", "unknown"),
        snapshots=tuple(snapshots),
    )
