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

Everything above is dual-licensed under MIT or Apache-2.0, at your option.
Commercial tools plug in through adapters; the open stack (Verilator, Icarus,
cocotb, Yosys, SymbiYosys, Z3, GTKWave) is first-class and works out of the box.

## Why

Verification is the largest cost in a chip program — 40–50% of the budget today,
heading toward 60–70% of engineering hours. Most of it is *iteration*: a late
change to RTL, a register map or a clock tree puts earlier results in doubt, so
teams rerun whole regressions and re-close coverage they already closed. WENGOLD
keeps the results that still hold and reruns only what the change could have
affected.

## Install

```bash
git clone https://github.com/wengold/wengold.git
cd wengold
python -m pip install -e ".[open]"     # open toolchain only
wengold demo                            # run the bundled SoC walkthrough
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

Pre-alpha. The kernel, graph and ledger are implemented; agent roles are being
filled in. See [`docs/roadmap.md`](docs/roadmap.md).

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
