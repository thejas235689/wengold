# Xezim simulation in WENGOLD

Use Xezim as an optional external SystemVerilog simulator. WENGOLD's reference
release for this adapter is **0.11.6**. WENGOLD does not download or bundle the
simulator or the UVM library, and the existing Icarus workflow is unchanged.

## Install the reference release

The upstream tag requires Rust 1.100+, Clang and the LLVM archive tools.
The upstream repository pins the matching SystemVerilog front-end commit.

```bash
git clone --depth 1 --branch 0.11.6 https://github.com/aionhw/xezim.git
cd xezim
cargo build --release --bin xezim
export PATH="$PWD/target/release:$PATH"
xezim -V
```

See the pinned [release notes](https://github.com/aionhw/xezim/releases/tag/0.11.6)
and [build requirements](https://github.com/aionhw/xezim/blob/0.11.6/docs/building.md).
The adapter records the version it actually ran. Versions other than the
reference version are not covered by this integration's release test.

## Run a self-checking RTL test

From the WENGOLD checkout, with WENGOLD and Xezim on your PATH:

```bash
wengold xezim --project examples/dv_workflow --top counter4_tb \
  --seed 1 --pass-marker REGRESSION_PASS --log results/xezim.log \
  rtl/counter4.sv tb/counter4_tb.sv
```

For Linux Silicon Studio, open `examples/dv_workflow` as the project. Under
**Local AI → EDA manifest**, inspect and run `flows/xezim.json`. The same manifest
also works in **DV Workflow → Testcases + Regression**. It collects the raw
simulator log. It does not produce a measured coverage report.

## Run the UVM smoke test

Use a local copy of the [Accellera UVM reference implementation](https://github.com/accellera-official/uvm-core/tree/2020.3.1).
The release root or its `src` directory can be passed as `--uvm-dir`.
WENGOLD inserts `uvm_pkg.sv` before your ordered source list and supplies the
include directory. Do not also list `uvm_pkg.sv` yourself.

```bash
wengold xezim --project examples/dv_workflow --top counter4_uvm_tb \
  --uvm-dir /path/to/uvm-core --uvm-test counter4_test \
  -D UVM_NO_DPI -D UVM_REPORT_DISABLE_FILE_LINE \
  --pass-marker COUNTER4_UVM_PASS --log results/xezim-uvm.log \
  rtl/counter4.sv tb/counter4_uvm_tb.sv
```

The test exercises UVM factory registration, configuration DB, objections and
self-checks for reset, increment and hold. Repeat with `-D INJECT_FAILURE` to
verify that an intentional mismatch fails the run.

## Read the result

- The JSON includes the version, seed, exact simulator arguments, exit code,
  transcript and WENGOLD verdict. Outside a reviewed recipe, the CLI does not
  build a dependency manifest or discover all included sources.
- An RTL pass needs the exact requested marker on its own line and an explicit
  finish. UVM needs an explicit finish and a complete zero-error, zero-fatal
  report summary. Supply a UVM pass marker to also require your own scoreboard
  completion. WENGOLD uses Xezim's `--error-exit` so a SystemVerilog `$error`
  cannot silently count as success.
- WENGOLD exits 0 for a passing test, 1 for a failed test, 2 for invalid input,
  a missing tool or execution errors, and 3 for timeouts or inconclusive
  evidence. An exit-zero simulator run without the expected evidence is
  inconclusive.
- The adapter runs a selected test with ordered sources, `-I` includes,
  `-D` defines and an optional UVM library. It does not qualify the simulator
  for full UVM, formal, UPF, gate-level timing or tapeout signoff.

## Run a subsystem example

[SoC Verification Preview](../examples/soc_verification/README.md) uses the same
runner to verify DMA, arbiter, and memory interaction, distinguish caught faults
from unexercised checks, and demonstrate evidence invalidation after a change.
