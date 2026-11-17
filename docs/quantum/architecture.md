# WENGOLD Quantum Design Studio — Architecture and delivery plan

## Product topology

Two front ends share one Python package: (1) the WENGOLD native workspace and (2) the standalone Quantum Designer launcher. Both use the same versioned circuit IR, validation, simulator adapters, verification utilities and artifact model. Keep quantum packages optional so the silicon verification CLI and existing desktop remain usable without Qiskit/Cirq/QuEST.

## Architecture

```text
WENGOLD native workspace        Standalone Quantum Designer
            \                       /
             Shared Qt components / project APIs
                         |
                  Quantum circuit IR
                         |
              validation + compiler layer
               /          |           \\
           Qiskit        Cirq       QuEST bridge
               \          |           /
                simulation result contract
                         |
           verification + trace + visualization
                         |
              project artifacts / AI agents
```

## Canonical IR

The first version lives in `quantum/core/circuit_ir.py`. It uses zero-based logical qubit IDs, unique operation IDs, explicit targets/controls, parameters and classical bits. OpenQASM 3 import/export, timing, noise operations, control-flow, physical layout and source spans are follow-up IR extensions; do not silently discard unsupported constructs. The IR schema is versioned and must have migration tests before incompatible changes.

## Backend contract and reality

- Qiskit adapter uses Qiskit and Aer sampling; Aer is an optional dependency and the adapter must remain isolated.
- Cirq adapter implements the initial common unitary gate subset and sampling/statevector paths.
- QuEST is native C/C++ software. This repository currently has an explicit disabled adapter, not a working QuEST binding. Build a WENGOLD-owned pybind11 bridge or documented subprocess protocol, pin the QuEST version/ABI, and add CPU CI before enabling it. GPU and MPI are later opt-in profiles.
- Capability discovery is runtime-based. Unsupported gates and missing dependencies must fail explicitly, never fabricate results.

## Verification rules

1. Validate IR before compilation.
2. Check state normalization and unitary residuals for available matrices.
3. Compare pure states with global-phase-invariant fidelity.
4. Compare measurement results statistically (confidence intervals / goodness-of-fit), not by requiring identical random samples.
5. Normalize endianness and qubit ordering before comparing adapters.
6. Keep backend, version, seed, shots, elapsed time and compiler metadata with every result.
7. A successful execution is not a proof of equivalence. Hardware provider execution is not included in the initial scope.

## Desktop integration

The existing native app uses PyQt6 and builds workspace tabs in `wengold/native_studio.py`. Integrate the Quantum Studio tab through a lazy import so systems without quantum extras continue to launch. The standalone app is `python -m quantum_app`. GUI simulations must execute in a worker thread/process with cancellation and resource limits; never run large simulations on the Qt event loop.

## Linux dependencies

Base: Python >=3.11, existing WENGOLD native extra (PyQt6), NumPy. Quantum optional extra: Qiskit, Qiskit Aer, Cirq, SciPy, Matplotlib and PyQtGraph. Native QuEST bridge: CMake, Ninja, C/C++ compiler, pybind11 and QuEST source. GPU/MPI are optional and must be detected rather than assumed. Keep simulator dependencies in an isolated environment when version constraints conflict with the core application.

## Engineering phases and acceptance

1. IR, validation, serialization, tests.
2. Drag/drop canvas, gate palette, undo/redo, project save/load.
3. Qiskit and Cirq adapters; backend capability reporting.
4. QuEST native bridge and CPU CI; GPU/MPI optional profiles.
5. OpenQASM import/export with unsupported-feature diagnostics.
6. Statevector, density matrix, Bloch sphere, Q-sphere and measurement visualizers.
7. Differential and statistical verification, regression artifacts.
8. AI circuit generation/optimization/debug agents with parser + simulator + verifier evidence.
9. Native WENGOLD tab, standalone packaging, Rocky Linux and Ubuntu CI.

Release gate: clean install, IR tests, GUI offscreen tests, Qiskit/Cirq smoke tests when extras are installed, QuEST bridge tests only when compiled, and no claims of backend parity without executed evidence.

## Result and bit-order contract

WENGOLD result bit strings use most-significant-to-least-significant display order: `q[n-1]...q[0]` for quantum basis-state probabilities and `c[n-1]...c[0]` for classical measurement strings. Backend adapters must translate native simulator indexing into this convention before returning results. Qiskit uses little-endian statevector indexing; Cirq's explicit `qubit_order` places the first listed qubit at the most-significant end, so the Cirq adapter reverses the formatted basis index. Measurement results are remapped through each IR operation's explicit `classical_bits` list.

## Project file contract

`.wqproj` is a JSON document with `format = wengold.quantum-project`, `project_version = 1`, project metadata, and the versioned circuit IR. `save_project` writes to a temporary file in the destination directory and atomically replaces the destination. `load_project` rejects unknown project or circuit schema versions instead of silently coercing them.
