# WENGOLD QuEST native bridge

This is an optional QuEST **v4** bridge. It uses the public `quest.h` API
rather than reading QuEST internal state buffers.

## Build prerequisites

- QuEST v4 installed with `quest.h` and its library discoverable through
  `CMAKE_PREFIX_PATH`, `CMAKE_INCLUDE_PATH` and `CMAKE_LIBRARY_PATH`.
- CMake >= 3.18, a C++17 compiler, Python >= 3.11, and pybind11.
- WENGOLD quantum extra for NumPy.

Example:

```sh
python -m pip install -e '.[quantum,quantum-native]'
cmake -S quantum/native -B build/quest \
  -Dpybind11_DIR="$(python -m pybind11 --cmakedir)" \
  -DCMAKE_PREFIX_PATH="$HOME/.local/quest"
cmake --build build/quest --config Release
cmake --install build/quest --prefix .
```

The bridge serializes calls with a process mutex because QuEST environment
initialization/finalization is process-global. Each invocation owns and frees
its Qureg before finalizing the environment.

## Supported contract

The initial bridge implements statevector execution for I/H/X/Y/Z/S/SDG/T/TDG,
RX/RY/RZ, CX/CNOT, CZ, SWAP, CCX/Toffoli and CSWAP. S/T-family gates use
phase-shift operators; their global phase convention is physically equivalent.
Terminal measurements are sampled from the returned statevector in Python.
Mid-circuit measurement, reset, density matrices, noise channels, GPU/MPI
specific configuration and large-circuit resource scheduling are not yet
implemented by the WENGOLD adapter.

The extension is optional. If absent, backend discovery reports QuEST as not
built and constructing `QuESTBackend` raises `BackendUnavailable`.
