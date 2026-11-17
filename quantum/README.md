# WENGOLD Quantum Design Studio

This package is an additive quantum-circuit workspace for WENGOLD. It establishes a typed, backend-neutral circuit IR, lazy backend discovery, validation, a PyQt6 circuit editor, and a standalone launcher. Optional simulator dependencies are only reported available when installed and, for QuEST, when the native extension is compiled.

## Development install

```sh
python3.11 -m venv .venv-quantum
. .venv-quantum/bin/activate
python -m pip install -e '.[quantum]'
python -m pip install -e '.[native]'
python -m wengold.quantum_app
```

QuEST is a native C/C++ dependency and is built separately; see [quantum/native/README.md](native/README.md) for the pinned v4.2.0 bridge build and [docs/quantum/architecture.md](../docs/quantum/architecture.md) for the backend contract. Qiskit and Cirq are optional runtime dependencies.

## Current capabilities

- Backend-neutral JSON circuit IR with operation IDs, qubit operands, parameters, classical operands and schema version.
- Atomic `.wqproj` save/load with format-version validation.
- Validation for qubit bounds, duplicate IDs, gate arity and parameter shape.
- Qiskit and Cirq adapters, plus an optional QuEST v4.2.0 pybind11 CPU bridge (20-qubit desktop safety cap).
- PyQt6 drag-and-drop editor with backend selector, shot control and QThread simulation execution.
- Bloch-sphere reduced-state vectors, Q-sphere probability/relative-phase points and measurement histograms.
- Strict OpenQASM 3 supported-subset import/export; unsupported syntax raises a validation error instead of being silently dropped.
- Initial gate-by-gate debugger service: replays unitary circuit prefixes and captures statevector/probability snapshots at the initial state and after each operation.

## Project persistence and OpenQASM 3

Use `quantum.core.project.save_project(path, circuit, metadata=...)` and `load_project(path)` for atomic `.wqproj` persistence.

Use `import_openqasm3(source)` and `export_openqasm3(circuit)` from `quantum.core.openqasm3`. The supported subset includes indexed single-qubit gates, RX/RY/RZ numeric expressions using `pi`, CX/CNOT, CZ, SWAP, CCX, CSWAP, measurement, reset and barriers. Custom gate declarations, control flow, whole-register broadcast, timing and opaque pragmas are not supported.

## Running and inspecting a circuit

Launch with `python -m quantum_app`. Drag gates onto the circuit wires, choose Qiskit, Cirq or QuEST, set the shot count, and select **Run simulation**. Runs execute in a Qt worker thread. A statevector result updates the reduced-state Bloch spheres and Q-sphere; a sampled result updates the measurement histogram. The Q-sphere limits rendering to the 2,048 highest-probability populated basis states.

## Gate-by-gate debug trace (GUI and developer API)

```python
from quantum.backends import create_backend
from quantum.service.debugger import build_debug_trace

trace = build_debug_trace(circuit, create_backend("qiskit"))
for snapshot in trace.snapshots:
    print(snapshot.step, snapshot.operation_id, snapshot.gate)
    print(snapshot.statevector, snapshot.probabilities)
```

In the editor, select **Build debug trace** to compute snapshots off the Qt UI thread. Use **Previous**, **Next** or the step slider to navigate; the active gate is outlined on the circuit and its snapshot is loaded into the State Visualizer. The panel reports operation ID, backend, execution time and probability L1 change from the prior step. Starting a new normal simulation clears the previous debug trace.

The debugger also includes a basis-state amplitude table (real/imaginary components, magnitude, phase in radians and normalized probability) and the developer API `amplitude_rows(statevector)`. Compare two pure states with `compare_statevectors(reference, candidate)`; it validates dimensions and finite/non-zero vectors and reports squared, global-phase-invariant fidelity plus the relative global phase. Fidelity is a state comparison metric, not a substitute for checking gate semantics, measurement distributions or hardware noise.\n\nThe initial implementation is deliberately **unitary-only**. It rejects measurement, reset, barrier and delay because pure-state snapshots do not faithfully represent their execution semantics. It replays each circuit prefix independently, so a trace costs one backend run per boundary; checkpoint caching and incremental simulator state are future optimizations. This is a debug trace engine, not yet a GUI time-travel debugger or a formal equivalence checker.

## Verification boundary

A successful simulation is not proof of circuit equivalence. Cross-backend comparisons must account for global phase, endianness, supported gate sets, floating-point tolerances and sampling uncertainty. No backend is labelled verified unless actual tests execute in CI.
