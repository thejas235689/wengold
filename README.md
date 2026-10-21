<p align="center"><img src="docs/assets/wengold-logo-dark.png" width="520" alt="WENGOLD"></p>

# WENGOLD

**Workflow ENgine for Graph-Oriented Logic Design** — the open-source validity
kernel for silicon verification.

WENGOLD is an open, terminal-native harness that lets AI agents verify a digital
SoC end to end on an entirely open toolchain, and — the part nobody has open
sourced — answers one question after every change:

> *Which of my previous verification results still hold?*

It does that with three things:

| Component | What it is |
|-----------|------------|
| **`wengold-graph`** | One continuously updated dependency graph of the design, the verification environment and the runs. |
| **`wengold-kernel`** | The *validity kernel*: on each change it classifies every prior result **valid / invalidated / unknown** and computes the minimum new evidence needed. |
| **`wengold-ledger`** | An append-only, content-addressed record of every run, revision, verdict and waiver, tied to its source. |

Everything above is dual-licensed under MIT or Apache-2.0. Commercial tools plug
in through adapters; the open stack (Verilator, Icarus, cocotb, Yosys,
SymbiYosys, Z3, GTKWave) is first-class and works out of the box.

## Why

Verification is the largest cost in a chip program — 40–50% of the budget today,
heading toward 60–70% of engineering hours. Most of it is *iteration*: a late
change to RTL, a register map or a clock tree puts earlier results in doubt, so
teams rerun whole regressions and re-close coverage they already closed. WENGOLD
keeps the results that still hold and reruns only what the change could have
affected.

## Install

```bash
git clone https://github.com/thejas235689/wengold.git
cd wengold
python -m pip install -e ".[open]"     # open toolchain only
python -m wengold.demo                  # run the bundled SoC walkthrough
```

## What is implemented

- **Elaboration, not regex.** `wengold.graph.elaborate` resolves `include` chains,
  `define` macros, `package`/`import`, `parameter`s, `generate` blocks and `.f`
  file lists, and reports anything it cannot resolve.
- **Conservative kernel.** The kernel returns `VALID` only when it can prove a
  result is unaffected. An empty dependency set, a dependency on an unresolved
  node, or a graph built without full elaboration all yield `UNKNOWN` — never a
  false pass.
- **Rerun propagation.** `minimum_new_evidence()` closes over the result graph, so
  anything derived from a re-run result is re-established too.
- **Reproducible evidence.** Every result is bound to the RTL, testbench,
  assertions and constraints it consumed, the tool, version, arguments, seed and
  working directory, and an environment fingerprint — as a single `repro` hash.
- **A real simulation flow.** `CocotbAdapter.run()` builds the environment,
  compiles and runs through the project Makefile, parses `results.xml` and
  collects waveforms and logs.
- **Honest tool outcomes.** Missing tool, timeout, crash, failed check and
  inconclusive proof are distinct; formal results are parsed from sby's own
  status, not its exit code.
- **A hardened ledger.** Concurrent-write locking, sequence and chain
  validation, malformed-record handling, and a trusted checkpoint that catches
  truncation of trailing records.
- **Operational agents.** Deterministic testbench and SVA generation, log-based
  diagnosis, repair proposals with an apply path, and `Orchestrator.run_loop()`
  that drives a complete classify → run → evidence → diagnose → repair loop.
- **A working MCP server.** `python -m wengold.mcp.server` speaks JSON-RPC over
  stdio so any MCP-capable agent can query the graph, classify results and append
  to the ledger.

## CLI

```bash
wengold index ./rtl                       # build the dependency graph
wengold completeness ./rtl                # report unresolved nodes
wengold classify ./rtl --changed sec_firewall --results results.json
wengold serve                             # run the MCP server over stdio
wengold demo                              # the bundled walkthrough
```

## Tool coverage

WENGOLD drives the tools your team already uses, in three groups — see
[`wengold/tools/registry.py`](wengold/tools/registry.py):

**01 · Simulation, debug and testbench** — VCS, Xcelium, Questa, Verilator,
Verdi, SimVision, Verisium, GTKWave, cocotb, UVM.

**02 · Formal, emulation and FPGA** — JasperGold, VC Formal, OneSpin, ZeBu,
Palladium, Veloce, Vivado, Quartus, Yosys, vManager.

**03 · Around the flow** — Git, GitHub, GitLab, Jira, Slack, Tcl, Python, Make.

## Status

v0.2. The graph, kernel and ledger are implemented and tested (69 tests); the
agents run a real loop; the MCP server works. Analog and mixed-signal
verification and physical signoff are out of scope. See
[`docs/roadmap.md`](docs/roadmap.md).

## Documentation

- [Architecture specification](docs/WENGOLD-Architecture-Spec.pdf) — the graph, the validity kernel and the ledger, in full.
- [Open-core strategy](docs/WENGOLD-OpenCore-Strategy.pdf) — the model, the market and the boundary.
- [Pitch deck](docs/WENGOLD-Pitch-Deck.html) — open it in any browser.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/roadmap.md`](docs/roadmap.md) — short reference and plan.

## License

Dual-licensed under either of

- the MIT License ([`LICENSE-MIT`](LICENSE-MIT))
- the Apache License, Version 2.0 ([`LICENSE-APACHE`](LICENSE-APACHE))

at your option. Contributions are accepted under the same terms unless you state
otherwise.
