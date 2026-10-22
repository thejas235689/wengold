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

## What a result establishes, and when it may be reused

A stored "PASS" is ambiguous. Every result can carry a **contract** — what it
claims, over what scope, by what method, under what assumptions, with what
evidence, and within what limits — so the conclusion cannot be read more broadly
than the check supports:

```python
Contract(
  claim="The secure key store is never written by a non-secure transaction.",
  scope=Scope.make(files=["rtl/sec_firewall.sv"], config={"KEYS": 2}),
  method=Method.make(MethodKind.PROOF, engine="sby"),
  assumptions=Assumptions.make([...], discharged=[...]),
  evidence=EvidenceRef.make(fingerprints={...}, proof_status="PASS"),
  limits=Limits.make(supported_config={"KEYS": [1, 2, 4]}, gaps=[...]),
)
```

**Four questions, kept separate** — never collapsed into one bit:

| Question | Values |
|---|---|
| What happened during execution? | `passed` · `failed` · `timed_out` · `crashed` · `tool_missing` |
| Is the evidence current? | `current` · `stale` · `unknown` · `withdrawn` *(computed by the kernel)* |
| What does it establish? | `none` · `observation` · `bounded_check` · `proof` |
| Has engineering accepted it? | `pending` · `accepted` · `rejected` · `waived` |

A current simulation pass is limited evidence. A **waiver records an engineering
decision and never becomes a technical pass** — `decide()` reports `reusable`
(the technical decision) separately from `accepted_for_use` (reusable *or* waived).

**Reuse is an auditable decision.** `decide()` evaluates explicit obligations
(evidence current, established at the required level, not rejected, contract in
scope, assumptions discharged, supporting evidence not withdrawn) and exports a
small `DecisionRecord` that `verify_decision()` re-derives independently.

**Deeper capabilities, all implemented:**

- **Typed dependencies** — compilation, elaboration, behavioral, assumption,
  configuration and requirement dependencies, each with its own reassessment rule.
- **Claim dependencies** — requirements trace to properties, tests and runs, so a
  changed requirement invalidates a conclusion even when the RTL is unchanged.
- **Composition contracts** — blocks carry assumptions and guarantees; integration
  is checked so a proven block is not promoted into a proven subsystem.
- **Configuration coverage** — results record the configuration they were
  established over, and `Limits.covers()` says whether a given config is inside them.
- **Evidence withdrawal** — a checker bug, bad assumption or tool issue retracts a
  conclusion, and reuse of anything that leaned on it is re-assessed.
- **Independent decision checking** — the decision record is validated by a
  separate implementation of the rule.


## Formal verification

A real proof loop, with no external tool required:

- **Property IR** (`wengold/formal/ir.py`) — one description of a claim, compiled to
  SystemVerilog assertions for SymbiYosys *and* consumed by the in-process engines.
- **A bounded RTL front-end** (`wengold/formal/rtl_model.py`) — a documented
  SystemVerilog subset (parameters, `assign`, clocked `always_ff` with non-blocking
  assignments and `if`/`else`, the usual expression grammar) turned into an
  executable transition function. Anything outside the subset raises
  `UnsupportedConstruct`, and the property is reported UNKNOWN — never guessed.
- **Two engines** (`wengold/formal/engine.py`):
  - *explicit* — explicit-state reachability. Proves a property when it reaches a
    fixpoint, reports BOUNDED if it stops early or the input space is incomplete.
  - *z3* — symbolic BMC plus k-induction over bit-vectors (optional `z3-solver`).
    k-induction proves the property for all reachable states when it closes.
- **Counterexample-guided repair** (`wengold/formal/loop.py`) — check, diagnose,
  propose a repair, apply it and check again, bounded by a budget. Each property
  leaves a `Contract` whose method is `proof` only when it really was proven.

```bash
wengold formal examples/formal/counter.sv --property "count <= MAX" --reset rst_n --sva
wengold formal examples/formal/counter_bad.sv --property "count <= MAX" --reset rst_n
```

## Register maps and clock domains

- **SystemRDL and IP-XACT** (`wengold/graph/regmap.py`) parse into a normalised
  address map of registers and fields — addresses, widths, `sw`/`hw` access, reset
  values — and add register/field nodes to the graph. Address collisions and
  overlapping fields are reported, not ignored.
- **CDC detection** (`wengold/graph/cdc.py`) finds the clock domains in a module and
  reports every signal read in one domain but written in another, directly or
  through combinational logic. Where a signal's domain cannot be determined it says
  so and marks the module unresolved, so the kernel refuses to call anything
  downstream VALID.

```bash
wengold regmap examples/soc_top/spec/registers.rdl
wengold cdc examples/cdc/mixed_clocks.sv
```

## Verifying WENGOLD's own invalidation logic

The kernel's reasoning is itself tested, not just its code paths. Five invariants
are checked against generated graphs, mutation and an independent reference
implementation (`wengold/kernel/reference.py`, which enumerates upstream paths
rather than computing a closure):

1. Adding uncertainty must not upgrade an affected result to reusable.
2. A known changed input must invalidate evidence that consumed it.
3. Removing graph information must not increase confidence.
4. Identical recorded inputs must produce deterministic classifications.
5. Reassessment must propagate when supporting evidence is withdrawn.

```python
from wengold.kernel import invariants
violations = invariants.fuzz(range(400))   # 0
```

## CLI

```bash
wengold index ./rtl                       # build the dependency graph
wengold completeness ./rtl                # report unresolved nodes
wengold classify ./rtl --changed sec_firewall --results results.json
wengold formal ./counter.sv --property "count <= MAX" --sva
wengold regmap ./registers.rdl            # SystemRDL or IP-XACT
wengold cdc ./mixed_clocks.sv             # clock-domain crossings
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

v0.4. The graph, kernel and ledger are implemented and tested (125 tests); the
agents run a real loop; the MCP server works; the formal loop proves, finds
counterexamples and repairs; the register-map and CDC front-ends are in. Analog and mixed-signal
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
