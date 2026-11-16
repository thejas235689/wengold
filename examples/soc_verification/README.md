# Wengold SoC Verification Preview

This runnable example checks one synchronous subsystem. A two-beat DMA transfer
and a CPU-style requester contend for a single write port. The bench stalls
the memory, then checks the accepted writes, readback and completion interrupt.
The launch scenario uses fixed DMA data and addresses, a behavioral memory and
a single clock. It is not a production DMA IP or a whole-SoC signoff flow.

From the repository root, with Python 3.11+ and [Xezim 0.11.6](../../docs/XEZIM.md)
on PATH, run:

```sh
PYTHONPATH=. python3 examples/soc_verification/run.py --output soc-preview-evidence
```

Use a new output directory for each run. Add `--xezim /path/to/xezim` if needed.
The directed recipes use seed 1. A different Xezim version can be tried, but
does not satisfy the pinned preview check. A missing or failed tool does not
count as a detected RTL fault. No UVM library is required for this example.

| Scenario | Expected evidence |
| --- | --- |
| CPU-first baseline | All six subsystem checks exercised on a passing run |
| No backpressure | Simulation passes, but the hold-under-stall check is unexercised |
| Dropped second write | Expected memory readback fails |
| Early interrupt | Completion checker reports the first failing cycle |
| Isolated memory bench | Passes without compiling the DMA or arbiter |
| Changed priority with old checker | Original subsystem result invalidated and old CPU-first expectation fails |
| Changed priority with updated checker | DMA-first behavior exercised on a passing rerun |

`report.json` lists named requirements, testbench hits, observed failure cycles,
actual simulator arguments, input hashes and transcript hashes. The runner
changes the priority only on a temporary copy. The Wengold validity kernel
classifies the prior subsystem result as invalidated, the independently compiled
memory test as valid, and an example of unmapped external evidence as unknown.
These classifications use the reviewed file dependencies of the bundled runs.
They are not automatic dependency discovery or per-property reuse for arbitrary
SoCs. Testbench hit counts are directed scenario evidence, not coverage closure.

## Replay saved evidence

The evidence directory contains each run's exact source snapshot, including the
modified arbiter for the DMA-first runs. The paths in the replay recipe are
relative to the bundle, so you can move or download the whole directory.

From the Wengold checkout, with Xezim 0.11.6 on PATH:

```sh
PYTHONPATH=. python3 examples/soc_verification/run.py \
  --replay soc-preview-evidence/report.json --run reverified_dma_first
```

Replay verifies input and original transcript hashes and reruns the selected
scenario. It compares simulator version, execution verdict, check hits and failing
cycle. `replay_matched` means the saved outcome was reproduced. For example, a
matching replay of `dropped_write` reproduces an expected simulation failure.
The original evidence is not overwritten. Use evidence bundles from sources you
trust, since replay compiles and executes their SystemVerilog testbenches.
