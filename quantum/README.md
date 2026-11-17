# WENGOLD Quantum Design Studio

This package is an additive quantum-circuit workspace for WENGOLD. The initial implementation establishes a typed, backend-neutral circuit IR, lazy backend discovery, validation, a small PyQt6 circuit editor, and a standalone launcher. It does **not** claim that Qiskit, Cirq, QuEST, GPU, hardware execution, or quantum verification has been run merely because an adapter is present.

## Development install

```sh
python3.11 -m venv .venv-quantum
. .venv-quantum/bin/activate
python -m pip install -e '.[quantum]'
python -m pip install -e '.[native]'
python -m wengold.quantum_app
```

QuEST is a native C/C++ dependency and is built separately; see [quantum/native/README.md](native/README.md) for the pinned v4.2.0 bridge build and [docs/quantum/architecture.md](../docs/quantum/architecture.md) for the backend contract. Qiskit and Cirq are optional runtime dependencies. The editor and IR tests do not require a simulator backend.

## Initial scope

- Backend-neutral JSON circuit IR with explicit operation IDs, qubit operands, parameters, classical operands and schema version.
- Atomic `.wqproj` save/load with format-version validation.
- Validation for qubit bounds, duplicate IDs, gate arity and parameter shape.
- Lazy backend registry and normalized execution result.
- Qiskit and Cirq adapters when their packages are installed, including statevector and sampled measurement paths with normalized bit ordering.
- Optional QuEST v4 statevector adapter through the WENGOLD pybind11 bridge; terminal measurements are sampled in Python. It remains unavailable until the native extension is compiled.
- PyQt6 drag-and-drop editor with backend selector, shot control and QThread simulation execution.
- Bloch-sphere reduced-state vectors, Q-sphere probability/relative-phase points and measurement histograms.
- Optional QuEST v4.2.0 pybind11 CPU bridge (20-qubit desktop safety cap); terminal measurements only.

## Project persistence

Use `quantum.core.project.save_project(path, circuit, metadata=...)` and `load_project(path)` for atomic `.wqproj` persistence. Writes use a temporary file in the destination directory followed by `os.replace`; project and circuit schema versions are checked on load.

## OpenQASM 3 interchange

Use `import_openqasm3(source)` and `export_openqasm3(circuit)` from
`quantum.core.openqasm3`. The strict supported subset includes indexed
single-qubit gates, RX/RY/RZ numeric expressions using `pi`, CX/CNOT, CZ,
SWAP, CCX, CSWAP, measurement, reset and barriers. Unsupported syntax such as
custom gate declarations, control flow, whole-register broadcast operations,
timing and opaque pragmas raises a validation error; it is never silently
discarded. Operation IDs are regenerated on import because OpenQASM does not
carry WENGOLD operation IDs.

## Running and inspecting a circuit

Launch with `python -m quantum_app`. Drag gates onto the circuit wires, choose
Qiskit, Cirq or QuEST, set the shot count, and select **Run simulation**. Runs
execute in a Qt worker thread. A statevector result updates the reduced-state
Bloch spheres and Q-sphere; a sampled result updates the measurement histogram.
The Q-sphere limits rendering to the 2,048 highest-probability populated basis
states so large statevectors do not create an unbounded number of plot objects.
The QuEST selector only works when the optional native extension is compiled.

## Verification boundary

A successful simulation is not proof of circuit equivalence. Measurement-only runs do not expose a statevector. Cross-backend comparisons must account for global phase, endianness, supported gate sets, floating-point tolerances, and sampling uncertainty. No backend is labelled verified until actual tests execute in CI.
