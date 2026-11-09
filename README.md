<p align="center"><img src="docs/assets/wengold-logo-dark.png" width="520" alt="WENGOLD"></p>

# WENGOLD

**Workflow ENgine for Graph-Oriented Logic Design** — an open validity kernel for
silicon verification.

WENGOLD keeps a dependency graph of a design and answers one question after every
change:

> *Which of my previous verification results still hold?*

It does that with three things:

| Component | What it is |
|-----------|------------|
| **`wengold-graph`** | One continuously updated dependency graph of the design, the verification environment and the runs. |
| **`wengold-kernel`** | The *validity kernel*: on each change it classifies every prior result **valid / invalidated / unknown** and computes the minimum new evidence needed. |
| **`wengold-ledger`** | An append-only, content-addressed record of every run, revision, verdict and waiver, tied to its source. |

Everything above is dual-licensed under MIT or Apache-2.0. Commercial tools plug
in through adapters; the open stack (Verilator, Icarus, cocotb, Yosys,
SymbiYosys, Z3, GTKWave) is first-class.

## Why

A late change to RTL, a register map or a clock tree puts earlier results in
doubt, and the usual answer is to rerun the regression. Most of those reruns
re-establish conclusions that the change could not have touched. WENGOLD keeps the
results that still hold and reruns only what the change could have reached — and
when it cannot tell, it says `unknown` rather than guessing.

## Install

WENGOLD needs **Python 3.11 or newer and nothing else**. No pip, no root, no package
manager:

```bash
git clone https://github.com/thejas235689/wengold.git
cd wengold
sh wengold.sh --version
sh wengold.sh index ./rtl
```

(`sh wengold.sh` rather than `./wengold.sh`: the script is committed as mode 644, so
`./` gives "Permission denied". `chmod +x wengold.sh` if you prefer `./`.)

`wengold.sh` finds a suitable interpreter itself (`python3.13`, `python3.12`,
`python3.11`, then `python3`) and, if none is new enough, prints the exact `dnf` line
instead of a traceback. It runs from `PYTHONPATH`, so nothing is written and removing
the checkout removes every trace.

```bash
sh wengold.sh --where      # which interpreter, and which extras are present
```

Every optional package is listed with **what its absence costs**, never as a failure:

| optional | what it enables | without it |
| --- | --- | --- |
| `pyslang` | a real SystemVerilog parse | bounded regex front-end; fewer modules found, and it says so |
| `z3-solver` | the formal loop | `wengold formal` is unavailable |
| `numpy` | `learn`, `spec-from-text` | those two commands are unavailable |
| `PyQt6` | the native window | `wengold desktop` falls back to a browser |

`pyproject.toml` lists numpy, but `import wengold` works without it — verified, and
pinned by `tests/test_no_install.py`, which runs the CLI with all four blocked.

For a desktop install (launcher, menu entry, icon):

```bash
sh linux/install.sh              # per-user, ~/.local, no root
```

On Rocky/RHEL see [`docs/INSTALL-ROCKY.md`](docs/INSTALL-ROCKY.md) — the trap there is
that Rocky 9 ships Python 3.9, and replacing the system `python3` breaks `dnf`.

## What is implemented

- **Elaboration, not regex.** `wengold.graph.elaborate` resolves `` `include ``
  chains, `` `define `` macros, `package`/`import`, `parameter`s, `generate` blocks
  and `.f` file lists, and reports anything it cannot resolve.
- **A real SystemVerilog front-end** (`pyslang`) and a **VHDL front-end**, both
  structural. `wengold index` picks the best available and **says so when it falls
  back** — the bounded regex elaborator finds a fraction of the modules, and the
  block count from it is an under-estimate, not the design.
- **Conservative kernel.** The kernel returns `VALID` only when it can prove a
  result is unaffected. An empty dependency set, a dependency on an unresolved
  node, or a graph built without full elaboration all yield `UNKNOWN` — never a
  false pass.
- **Rerun propagation.** `minimum_new_evidence()` closes over the result graph, so
  anything derived from a re-run result is re-established too.
- **Reproducible evidence.** Every result is bound to the RTL, testbench,
  assertions and constraints it consumed, the tool, version, arguments, seed and
  working directory, and an environment fingerprint — as a single `repro` hash.
- **Honest tool outcomes.** Missing tool, timeout, crash, failed check and
  inconclusive proof are distinct; formal results are parsed from sby's own
  status, not its exit code.
- **A hardened ledger.** Concurrent-write locking, sequence and chain validation,
  malformed-record handling, and a trusted checkpoint that catches truncation.
- **A working MCP server.** `wengold serve` speaks JSON-RPC over stdio so any
  MCP-capable agent can query the graph, classify results and append to the ledger.

## What a result establishes, and when it may be reused

A stored "PASS" is ambiguous. Every result can carry a **contract** — what it
claims, over what scope, by what method, under what assumptions, with what
evidence, and within what limits:

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
separately from `accepted_for_use`.

**Reuse is an auditable decision.** `decide()` evaluates explicit obligations
(evidence current, established at the required level, not rejected, contract in
scope, assumptions discharged, supporting evidence not withdrawn) and exports a
`DecisionRecord` that `verify_decision()` re-derives independently.

## Front-ends: how the graph is built

`wengold index` has two backends and picks the best available:

- **`slang`** — a real SystemVerilog front-end (`pyslang`). A preprocessor
  resolves `` `include ``, `` `define `` and `` `ifdef `` against the project's
  defines, and the source is then *parsed*. This is what makes the graph usable on
  a real codebase.
- **`regex`** — a bounded elaborator, used when slang is not installed. It is a
  fallback, not a parser: on real RTL it mistakes prose for instantiations and
  cannot see through `` `ifdef ``.

```bash
wengold index ./hw/ip --include ./hw/ip/prim/rtl --backend slang --define SYNTH
```

Anything a file does not resolve — a parse error, or an instantiation of a module
that is not in the file set — marks the module unresolved, and the kernel then
refuses to call anything downstream VALID.

## Formal verification

A real proof loop, with no external tool required:

- **Property IR** (`wengold/formal/ir.py`) — one description of a claim, compiled to
  SystemVerilog assertions for SymbiYosys *and* consumed by the in-process engines.
- **A bounded RTL front-end** (`wengold/formal/rtl_model.py`) — a documented
  SystemVerilog subset (parameters, `assign`, clocked `always_ff` with non-blocking
  assignments and `if`/`else`, the usual expression grammar) turned into an
  executable transition function. Anything outside the subset raises
  `UnsupportedConstruct`, and the property is reported UNKNOWN — never guessed.
- **Two engines** (`wengold/formal/engine.py`): an *explicit* state-space engine and
  a *z3* engine doing symbolic BMC plus k-induction over bit-vectors.
- **Counterexample-guided repair** (`wengold/formal/loop.py`) — check, diagnose,
  propose a repair, apply it and check again, bounded by a budget.

```bash
wengold formal examples/formal/counter.sv --property "count <= MAX" --reset rst_n --sva
```

**The honest limit.** This front-end covers the subset above — register-level RTL.
It does not accept a full core: on CV32E40P it covers 2 files of 125, and on
OpenTitan 0 of 165. Everything outside the subset is reported UNKNOWN, which is why
that limit is stated here rather than buried.

## Root cause, waveforms and the IDE

```bash
wengold rootcause ./rtl --changed cv32e40p_alu    # name the unvendored dependency and the path to it
wengold ide ./rtl --vcd wave.vcd                  # one self-contained HTML: tree, RTL, diff, waveform
```

`wengold rootcause` names the dependency that is not vendored, the causal path to
the result it puts in doubt, and declines when no change reaches a result.

`wengold ide` writes a single self-contained HTML page: file tree marked
clean/changed/pending, RTL with line numbers, a unified diff, a block table
(block | file | depends on | consumed by | cluster | verdict), and a **waveform
panel** from a VCD or a formal counterexample, with the failing cycle marked.

## Register maps and clock domains

- **SystemRDL and IP-XACT** (`wengold/graph/regmap.py`) parse into a normalised
  address map of registers and fields and add register/field nodes to the graph.
  Address collisions and overlapping fields are reported, not ignored.
- **CDC detection** (`wengold/graph/cdc.py`) reports every signal read in one clock
  domain but written in another. Where a domain cannot be determined it says so and
  marks the module unresolved.

```bash
wengold regmap examples/soc_top/spec/registers.rdl
wengold cdc examples/cdc/mixed_clocks.sv
```

## Standards conformance

Two Accellera standards are implemented, both as *checkers that never claim more
than they checked*. Each is verified against the standard rather than against my
reading of it: a copy of the standard's own material lives in `tests/fixtures/` and
a test compares the code to it. The two are not equally strong evidence — the FSL
syntax tables are extracted verbatim from the standard's Tables 3–33, while the CDC
attribute list comes from its clause text and worked examples, which is weaker. The
registry in `tests/fixtures/input_formats.json` records which is which.

**CDC/RDC Interface Standard v1.0** (`wengold cdc`) — reads and writes the
`accellera_cdc::` Tcl format, and checks the collateral against itself and against
the RTL: every referenced name must be declared, mandatory attributes must be
present, port types must come from the defined set, and the declared port set must
match the design. **It never says "CDC clean"** — deciding whether a crossing is
safe needs the synchroniser structure, which the standard leaves to the tool.

**Functional Safety Language v1.0** (`wengold fsl`) — sixteen Tcl commands that
create FMEDA objects. Checked against the standard's clause numbers:

| clause | rule |
| --- | --- |
| §5.4 | known command, no unknown arguments, required arguments present, no argument twice, enumerations matching **exactly** |
| §5.5 | every referenced object already created; no object created twice |
| §5.5.1 | the ISO 26262 and IEC 61508 argument sets are not interchangeable |
| §5.5.2 | `create_fmeda` needs exactly one of `-asil`/`-sil` non-`none` |

Plus one check no standard can specify: **if an FMEDA names an element that is not
a block in the RTL, the analysis is describing a design that does not exist.** That
is `--design`, and it is why this belongs in WENGOLD rather than in a standalone
linter.

```bash
wengold cdc collateral.tcl --design rtl/
wengold fsl design.fsl --design rtl/
```

Neither computes safety metrics. SPFM, LFM, PMHF and SFF are arithmetic over
failure rates the FMEDA supplies; WENGOLD collects and range-checks the declared
values and says so in every report. **A clean report is not a safety case.**

## Generating RTL from a spec, and reviewing the result

`wengold vibe` takes a sentence or a spec file, emits synthesizable RTL and a
self-checking testbench, simulates it, and reports a verdict:

```
timer  —  pass (iverilog), 132 lines (timer.sv 72, timer_tb.sv 60)
```

It writes `manifest.json` next to the RTL — module, spec source, per-file line
counts, tool and verdict — so a run leaves a record rather than only a transcript.
**A failed run writes no manifest**: recording a verdict for a run that never
reached one is the same error as a test count nobody checked.

`wengold review` suggests a fix only from checks that actually ran — a flop that
simulated as `X` gets a reset, an unsynchronised crossing gets a 2-FF synchroniser,
and a multi-bit bus is told not to be given one. Applying the suggestion turns the
failing check into a passing one. When no check ran, it produces nothing rather
than a generic list.

## Machine learning, and what it is worth

`wengold learn` ships five methods over the graph: clustering, supervised triage,
Q-learning for check ordering, regression and DBSCAN. **They are not equal, and the
tool says which is which** — every method prints its own honest reading.

The one that earns its place is DBSCAN's outlier flag, which points at blocks whose
dependency signature resembles nothing else. Tested against the kernel's own
unresolved set with a permutation test (2,000 shuffles):

| project | blocks | unresolved | flagged | hits | by chance | lift | p |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cva6 | 458 | 32 | 33 | 16 | 2.31 | **6.94×** | **0.000** |
| ibex | 345 | 17 | 28 | 8 | 1.38 | **5.80×** | **0.000** |
| OpenTitan | 879 | 78 | 55 | 14 | 4.88 | **2.87×** | **0.000** |
| cv32e40p | 154 | 8 | 7 | 1 | 0.36 | 2.75× | 0.300 |
| neorv32 | 86 | 0 | 8 | 0 | 0.00 | — | 1.000 |

On the projects with 17 or more unresolved blocks the flag is strongly enriched and
cannot be chance. On small ones the test has no power to show anything, and the
tool reports the p-value rather than the lift alone.

**`wengold learn supervised` does not read your project.** It trains on generated
register designs labelled by the real formal engine, and its features describe
generated spec fields. The command says so when given a path.

**RL loses to a two-line greedy heuristic** on every project tested, and prints
that conclusion instead of hiding it. The generative models are scored the same
way — see the section below.

### Does ML work with design and verification? Measured against simulation: no.

With `cocotb`, Icarus, Verilator and GHDL installed, the question was tested on
real RTL rather than on the graph alone. Mutation testing on `picosoc/simpleuart.v`
and `spimemio.v`: inject a fault, simulate, compare the output trace.

| framing | samples | positives | result vs majority baseline |
| --- | --- | --- | --- |
| run-level: "is this run faulty?" | 33 | 6 | 82% vs 82% — ties |
| run-level, per-signal features | 33 | 6 | 76% vs 82% — worse |
| signal-level: "will this signal diverge?" | 1,338 | 9 | 92.7% vs 99.3% — worse |

**Three framings, three failures to beat guessing.** The waveform features do carry
signal — `wengold learn waveform` separates clocks from data buses from tied-off
nets at 18/19 correct with no labels — but that signal does not predict faults.

The structural reason is worth stating: a fault injected into RTL is present from
time zero, so there is no "before" to warn from. Early-warning localisation assumes
a degradation that develops over time, and mutation testing cannot manufacture one.

**What this means for the product:** the kernel's exact machinery is the product.
ML sits beside it, and every measurement has either tied, lost, or detected a
proxy. The honest description of `wengold/learn/` is a correct little deep-learning
library that the product does not depend on.

## The agent layer: six stages, and the one that has nothing to win

```bash
wengold agent ./rtl --change sec_firewall --episodes 6
```

An agent that acts on a verification flow needs six things. All six are here, and
each is wired to real data rather than to a prompt:

| stage | what it does | what it reads |
| --- | --- | --- |
| **Perceive** | assemble the context | the graph, its completeness, the unresolved nodes, the kernel's verdicts, and **a live probe of which tools are installed** |
| **Reason** | a chain of thought per result | the nodes and results each claim rests on — every step is checkable against the graph |
| **Plan** | order the minimum new evidence | three strategies, compared rather than assumed |
| **Act** | execute the plan | the same runner the orchestrator uses, so a missing tool is `tool_missing`, never a pass |
| **Reflect** | compare outcome to goal, revise | re-perceives after each iteration and **stops when an iteration settles nothing** |
| **Adapt** | learn which strategy to use | a UCB bandit over the strategies, rewarded by results settled per check |

**The reasoning trace cannot say what the graph does not support.** It is generated
from the graph, not recalled — so when a coverage result was invalidated *through a
result it summarises*, the first version printed "the change touches 0 nodes, so it
cannot hold", which is a contradiction. That is fixed: it now names the invalidated
results, and when it genuinely cannot explain a verdict it says so instead of
inventing a reason.

**The honest negative result: planning has nothing to win here.** Three strategies
— cheapest-first, greedy-by-ratio, and best-first with re-scoring after every pick
— settle **identical** numbers of results at every budget:

| changed | budget 1 | budget 2 | budget 3 | budget 4 |
| --- | --- | --- | --- | --- |
| 1 block | 17 (all three) | 17 | 17 | 17 |
| 3 blocks | 0 (all three) | 0 | 19 | 19 |

One check at the base of the dependency tree cascades: settling the base settles
what rests on it, so almost any order reaches the same place. The kernel's minimum
evidence is already minimal. **The ordering problem is not a search problem** — which
is also why the earlier Q-learning attempt lost to a two-line heuristic. The bandit
reports a tie rather than inventing a preference, and a test pins that.

Where ordering *does* matter is when checks fail, and that is reflection's job: a
failing check stops the iteration rather than retrying the same plan.

**What is modelled and what is measured.** The dependency structure, the
classification and the minimum evidence are the real kernel's. Whether a check
*settles* a result is modelled, because no simulator or prover is installed in this
environment — the command prints that limit rather than dressing a model up as a
measurement.

## ReAct, test-time search, and multiple agents

```bash
wengold agent ./rtl --mode react        # thought -> action -> observation
wengold agent ./rtl --mode search       # test-time scaling
wengold agent ./rtl --mode orchestrate  # planner -> reviewer -> executor
```

**ReAct** is a real interleaved loop, not the batch planner above: there is no
up-front plan, and each step is chosen from the **last observation**. A failing
check changes the next action from "continue" to "diagnose", and a pass changes it
to "take what that unblocked".

**Test-time scaling, measured.** Last release showed ordering does not matter when
every check passes. It matters when checks **fail** — so that is where this is
measured, on groups of simulations where a coverage result needs *all* of them (so
spreading across groups is worth nothing). Twelve namings, 100 rollouts each, 15%
per-check failure rate:

| budget | greedy | beam search | best-of-32 random | beam vs greedy |
| --- | --- | --- | --- | --- |
| 3 checks | 2.21 | 2.41 | 2.21 | **+9.0%** (wins 4/12) |
| 4 checks | 2.89 | 3.08 | 2.76 | **+6.6%** (wins 7/12) |
| 6 checks | 3.79 | 4.07 | 3.74 | **+7.5%** (wins **11/12**) |

**Structured search helps; brute force does not.** Beam search beats the structural
heuristic by 6–9% and wins 11 of 12 at the larger budget. **Best-of-32 random
sampling is no better than greedy** — drawing more orderings and keeping the best
one recovers nothing, which is the difference between *scaling compute* and
*scaling a search*.

**Then I ran it on real designs, and the gain vanished.** On neorv32 (86 blocks,
90 results, 14 invalidated) and picorv32 (31 blocks, 27 in doubt), beam search
beats greedy by **exactly 0%** — it wins 0 of 8 seeds on both, and all three
strategies tie at every budget:

| budget | neorv32: cheapest / greedy / best_first | picorv32: same three |
| --- | --- | --- |
| 1 | 77.86 / 77.86 / 77.86 | 8.93 / 8.93 / 8.93 |
| 3 | 79.84 / 79.84 / 79.84 | 10.25 / 10.25 / 10.25 |
| 8 | 81.74 / 81.74 / 81.74 | 12.16 / 12.16 / 12.16 |

**The reason is symmetry.** On these designs every invalidated simulation unblocks
exactly one coverage result, at the same cost as every other. When the work is
symmetric no ordering is better than any other, so there is nothing for a search
to find. The all-or-nothing groups where beam won were a structure I built; these
designs do not produce it.

**So the honest reading is narrower than the table above:** structured search beats
a structural heuristic *on asymmetric structures*, and gains nothing on the real
designs tested here. I would not ship it, and the earlier number should not be
quoted without this paragraph next to it.

**Multi-agent orchestration** runs a planner, an executor and a **reviewer** — and
the reviewer is the point. It does not read the planner's reasoning; it re-derives
what the plan must satisfy from the context and checks it, then refuses to let a
bad plan run:

```
planner  -> reviewer  plan proposed  (4 step(s))
reviewer -> planner   REJECTED: step 1 (dma_sim) needs cocotb, which is not installed
orchestra -> executor refusing to execute an unreviewed plan
executed: False  revisions: 2  outcomes: 0
```

It catches three things a planner happily produces: a plan that **misses an open
result**, a plan that relies on a **tool that is not installed**, and a plan that
schedules a step **before something it depends on**. That is the same separation of
duties the kernel applies to evidence, applied to the agent's own plan — and on
this machine it stops every run before a single check is spent, which is correct:
nothing here is installed.

## Belief, memory, MCTS and hierarchy — and the first thing that actually wins

```bash
wengold agent ./rtl --mode stages     # the six stages, now memory-backed
```

Four components from the standard agentic taxonomy, each measured rather than
demonstrated.

**The POMDP belief is worth having, but not for the reason the textbook says.**
`Belief` holds P(check passes) per open result; `Memory` supplies those priors from
history, in two streams — episodic runs and semantic facts. Ranking checks by
**value of information** (entropy per unit cost) is the textbook answer and it
**loses to plain greedy by 4–8% here**, because VOI assumes a negative observation
is information you can act on and keep going. In this flow a failed check **halts
the run**, so putting the flakiest check first spends the budget discovering the
thing most likely to stop you.

Inverting the same belief works. Ordering by probability of passing — the safest
check first — maximises expected progress before the halt:

| project | budget | greedy | safest first | gain | wins |
| --- | --- | --- | --- | --- | --- |
| neorv32 | 4 | 79.55 | 80.28 | +0.9% | 6/10 |
| neorv32 | 8 | 80.42 | 82.56 | +2.7% | 9/10 |
| neorv32 | 12 | 80.77 | 83.88 | **+3.9%** | **10/10** |
| picorv32 | 4 | 10.37 | 11.27 | +8.7% | 9/10 |
| picorv32 | 8 | 11.09 | 13.65 | **+23.1%** | **10/10** |
| picorv32 | 12 | 11.41 | 15.38 | **+34.8%** | **10/10** |

**And on OpenTitan it is far larger.** 1,849 HDL files, 879 blocks, 10,730 edges,
2,553 nodes, 79 unresolved; 882 results of which 381 are unknown. Measured on
results settled **from the open set** (the honest metric — counting 488 already-valid
results against 394 open ones dilutes everything to +1.8%):

| budget | greedy | safest first | VOI | gain | wins |
| --- | --- | --- | --- | --- | --- |
| 10 checks | 3.3 | 6.8 | 0.9 | **+107%** | 6/6 |
| 25 checks | 3.4 | 10.9 | 1.0 | **+218%** | 6/6 |
| 50 checks | 3.4 | 12.2 | 1.0 | **+255%** | 6/6 |

Value-of-information collapses to **0.9 against greedy's 3.3** — it runs the
flakiest check first and the run halts immediately. The theory said it would be
wrong; on the largest design it is not merely wrong but catastrophic.

Ten independent worlds per row, 200 rollouts each, a quarter of the checks flaky.
This is the **first component in the agent layer that measurably beats the two-line
heuristic** — and it beats it because of a signal no graph-shape heuristic can see:
two results with identical dependency structure can differ tenfold in how likely
they are to pass, and only history knows which.

**MCTS with UCB1** (`mcts.py`) is implemented properly — selection, expansion,
rollout, backpropagation, with `c=0` degenerating to pure exploitation so the
exploration term's contribution is visible. On the real designs it **does not beat
greedy** (79.08 vs 79.82 on neorv32; equal on picorv32). On a small synthetic world
it sometimes does. Since the sign is structure-dependent, no test pins it either
way — that is the mistake the beam-search number made in v0.20.0.

**Hierarchical decomposition** (`hierarchy.py`) implements both shapes. *GoalAct* —
a global milestone order with local execution — **beats flat planning on picorv32**
(0.28 vs 0.00 milestones at budget 8) and **loses on neorv32** (1.42 vs 1.56).
*ReAcTree* — the recursive variant — is **worse than GoalAct on both**, which is the
honest answer: splitting a group and then checking its milestone spends a check on
something that could not have settled yet.

**A swarm, and the control experiment that killed its headline.** `swarm.py`
partitions the open set by IP, gives each worker a slice it alone acts on, and has
no scheduler object — `Swarm.step()` asks every living worker for its own move.

The first measurement looked like a win: **18.8 results settled vs the central
planner's 10.4** on OpenTitan at 20 checks. It was not decentralisation. A central
planner that simply **does not halt on the first failure** scores **18.5**. The
entire gain was the failure policy — one line, not an architecture — and the swarm
is marginally *worse* once that is matched.

The one property that is genuinely its own is surviving loss, and measuring it
taught me something about the metric. Under a **check** budget, killing workers
changes nothing: one survivor spends the whole budget itself, and 0, 2 or 3 dead
workers all settled 28.0. A swarm's resilience is a statement about **time**, not
work. Under a **round** budget — one check per living worker per round — losing 2
of 4 workers costs ~22% of output and losing 3 costs ~34%:

| rounds | 0 killed | 2 killed | 3 killed |
| --- | --- | --- | --- |
| 5 | 18.2 | 14.8 | 12.8 |
| 10 | 37.2 | 27.8 | 23.0 |
| 15 | 55.2 | 43.0 | 36.2 |

Graceful degradation, never collapse — and a central planner killed mid-run settles
nothing further by construction. That is real, and it is the only part of the swarm
claim that survives contact with a measurement.

**Calibration, escalation, and the human interface.** Everything above states
probabilities — `belief.py` says P(this check passes) = 0.92, and every planner acts
on it. **Nothing had checked whether that number is true.** On OpenTitan, over 395
results:

**ECE = 0.046 — well calibrated.** The 0.8–1.0 bin predicts 0.95 and observes 0.94
across 270 results. The worst bin is 0.0–0.2, predicting 0.15 and observing 0.41:
the model is **too pessimistic about the flakiest checks** — the safe direction, but
still an error worth naming.

That calibration is what makes escalation meaningful. The Moravec split, made
operational: the machine counts (dependents, cost, history) and a person is asked
only where the machine is genuinely unsure or where being wrong is dear.

| threshold | checks sent to a human | failures caught | precision |
| --- | --- | --- | --- |
| 0.0 | 6% | 17% | 59% |
| 0.2 | 24% | 54% | 44% |
| 0.4 | 52% | 80% | 30% |

**Augmentation has a price and it is payable in human attention.** A policy that
escalates everything catches every failure and is useless; one that escalates
nothing is the status quo. That table is the honest curve between them, and it is
the first number here a design team could take to a resourcing conversation.

Human decisions — accept, waive, override, escalate — are written back into
`Memory`, so the next run's priors reflect the person's call. Without the write-back
it would be a log; with it, it is the loop.

**The cognitive scorecard.** `evaluate()` scores the agent against a list of
abilities and gives each one of three answers: a number, **failed**, or **not
measurable here** with the reason. No "partial".

| ability | status | score |
| --- | --- | --- |
| perception | measured | correct — 16 results, 0 unresolved |
| attention | measured | 100% of the top third are the high-prior items |
| memory | measured | two streams, round-trips |
| reasoning | measured | 20/20 traces sound |
| planning | measured | covers the whole open set |
| metacognition | measured | **ECE 0.049 — well calibrated** |
| learning | measured | priors move with evidence |
| tool use | measured | 0/2 available — reported, not assumed |
| language | measured | 100% trained, **0% held-out** |
| open-ended generation | **failed** | no model reaches the missing state |
| social cognition | not measurable here | no peers, no users |
| embodied control | not measurable here | no robot |
| continual learning | not measurable here | no corpus, no compute |
| neuromorphic / neuroevolution | not measurable here | not implemented |

**10 of 14 measurable; 1 measured and failed; 4 untestable here.** The failed row
is the point of the exercise: a scorecard that only reports passes is a brochure.

### What is not here, and why

| from the taxonomy | status |
| --- | --- |
| POMDP belief, dual-stream memory | **implemented**, one of them measurably wins |
| MCTS with UCB1 | **implemented**, no gain on real designs |
| Hierarchical decomposition (GoalAct, ReAcTree) | **implemented**, mixed |
| PPO / actor-critic | **not implemented** |
| CTDE for multi-agent | **not implemented** |
| DRL, meta-DRL | **not implemented** |
| Internalised planning (o1-style RL fine-tuning) | **not implementable here** |
| Swarm: decentralised, local, fault-tolerant | **implemented**, resilience only |
| MARL / IPPO | **not implemented** |
| NAS, HyEvo, SAGE, SelfEvolve, GNN adaptation | **not implemented** |
| A2A / ANP protocols | **not implementable here** (no peers) |

**PPO** would be a fourth RL attempt at the ordering problem, and the first three
lost to a two-line heuristic (Q-learning in v0.10.0, the bandit in v0.19.0, and now
the belief signal beats them all by 35%). A policy that had to *learn* what the
memory already knows is not obviously worth training. **CTDE and meta-DRL** need a
population of tasks to generalise across; there is one machine and two designs.
**Internalised planning** is not implementable at all in this environment: it means
fine-tuning a language model's weights with RL, and there is no model, no corpus and
no training compute here. Claiming otherwise would be the single most dishonest
thing this repository could do — so the taxonomy is answered by a component that
computes, not by one that is named.

## Generative models, and the one that earns its place

Four families are in the tree: **transformer with autoregressive decoding** (the
encoder-decoder in `wengold/learn/transformer.py`), a **VAE**, a **GAN** and a
**diffusion model**. The last three have one job — generate *stimulus* — and one
yardstick, because a generative model that cannot be scored is a demo:

```bash
wengold learn generative --instances 300 --epochs 150
```

The design is a passcode chain. The corpus reaches stage 2 and never stage 3, and
the symbol that would finish it (`9`) appears **nowhere** in the data. Ground
truth is the engine's own reachable-state set, enumerated by breadth-first search
over the parsed transition function — not a coverage proxy.

| model | states reached | reached stage 2 | unlocked |
| --- | --- | --- | --- |
| corpus (the data itself) | 3/7 | 95% | 0% |
| random sampling | 5/7 | 5% | 0.7% |
| VAE | 6/7 | 3.7% | 0.3% |
| GAN | 5/7 | 3.7% | 1.3% |
| **diffusion** | 5/7 | **22%** | 0.7% |

**Diffusion is the only one that works**: it reaches the deep state **4.4×** as
often as random sampling. The **VAE and the GAN land at or below random** — at
this size they learn nothing usable, and the tool says so instead of reporting a
loss curve and calling it success. **None of them reproduces the corpus** (95%):
all three are far weaker than the data they were shown.

And nobody unlocks. Every unlock rate — including random's — sits at 0.3–1.3%,
which is bits landing on `9` by chance, not a model discovering the completion.
The honest conclusion is the useful one: **a generative model can extend a pattern
it was shown, and cannot invent the thing that is missing from its corpus.**

## Text to spec, and the checker that decides

```bash
wengold spec-from-text "a register r0 at address 4 with a read only field \
  status at bits 3 to 0 , resets to zero"
```

```
draft: register r0 @ 0x04, field status bits 3:0, ro, reset 0
validation: accepted — access mode, bit range, alignment and reset all check out
rtl       : drafted: 13/13 checks passed
formal    : `r0_status_q == 0` -> proof  (k-induction closed at k=8)
```

A transformer and an LSTM are written out in `wengold/learn/` — scaled dot-product
multi-head attention, encoder/decoder blocks, an LSTM with gates and a cell state —
on a small reverse-mode autodiff tape, with **every backward pass checked against
finite differences**. `--arch lstm` selects the other model.

**The model drafts; the checker decides.** Measured honestly, on a generated
grammar: **100% exact on unseen combinations** of trained words, **0% on held-out
vocabulary**. It is a grammar reader, not a language model, and it refuses a
sentence whose words are mostly unknown rather than decoding a spec out of noise.
The transformer beats the LSTM by 100% to 5% with *less* training.

The formal run verifies that *this spec* yields correct RTL. It cannot verify that
the spec is what the sentence meant — and a misread sentence passes every
downstream check, which is pinned in the tests.

## Verifying WENGOLD's own invalidation logic

Five invariants are checked against generated graphs, mutation and an independent
reference implementation (`wengold/kernel/reference.py`):

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
wengold rootcause ./rtl --changed cv32e40p_alu
wengold formal ./counter.sv --property "count <= MAX" --sva
wengold ide ./rtl --vcd wave.vcd
wengold regmap ./registers.rdl            # SystemRDL or IP-XACT
wengold cdc ./mixed_clocks.sv             # clock-domain crossings
wengold cdc collateral.tcl --design rtl/  # check CDC collateral against the RTL
wengold fsl design.fsl --design rtl/      # Accellera Functional Safety Language
wengold vibe "an 8-bit timer with a match output"   # spec -> RTL -> testbench -> sim
wengold review ./rtl --changed timer      # fix what a failed check actually showed
wengold learn dbscan ./rtl                # clustering, triage, RL, regression
wengold spec-from-text "..." --arch transformer
wengold agentic ./rtl --goal "make this elaborate"   # act on what the kernel can justify
wengold desktop                           # native Linux window
wengold serve                             # run the MCP server over stdio

# environment
wengold doctor                            # front-end, parse cache, local model
wengold doctor --presets                  # the local models this project knows
wengold doctor --llm                      # probe the model and round-trip one request
```

## Tool coverage

WENGOLD drives the tools a verification team already uses, in three groups — see
[`wengold/tools/registry.py`](wengold/tools/registry.py):

**01 · Simulation, debug and testbench** — VCS, Xcelium, Questa, Verilator,
Verdi, SimVision, Verisium, GTKWave, cocotb, UVM.

**02 · Formal, emulation and FPGA** — JasperGold, VC Formal, OneSpin, ZeBu,
Palladium, Veloce, Vivado, Quartus, Yosys, vManager.

**03 · Around the flow** — Git, GitHub, GitLab, Jira, Slack, Tcl, Python, Make.

## Measured on real projects

**33 repositories attempted, 30 indexed.** Every number below came from running the
tool on the project named; the full table is in [`RESULTS.md`](RESULTS.md).

> **These were measured at v0.27.1 and have not been re-run since.** That is 27
> releases ago, and the front-ends have changed substantially in the meantime —
> whole-project elaboration, `.f` filelists, a VHDL front-end, the formal subset
> widened from 2 to 11 of 27 files, and a fix for one bad module poisoning every
> module in its file. Some of these numbers are therefore likely to be pessimistic,
> and at least one (coverage) is a ratio of files that contained a design unit
> rather than anything to do with testing. They are left as measured rather than
> refreshed, because a number I have not re-taken is not one I should present as
> current.

### Complete and clean (unresolved = 0)

| project | blocks | edges | coverage |
| --- | --- | --- | --- |
| 2D-systolic-array | 2 | 7 | 100% |
| riscv-boom | 2 | 0 | 100% |
| neorv32 | 86 | 1,262 | 89% |
| Anvil-Pro | 19 | 107 | 76% |
| rustdv/rustdv | 7 | 5 | 62% |
| pyuvm | 7 | 38 | 30% |
| wave_rerunner | 10 | 34 | 22% |
| riscv-dv | 1 | 2 | 4% |
| lxp32-cpu (VHDL) | 34 | 163 | — |
| minerva (generated) | 51 | 50 | — |
| BorussCPU-Laibach | 8 | 20 | — |

### Not complete, with the reason

| project | blocks | unresolved | coverage | why |
| --- | --- | --- | --- | --- |
| OpenTitan `hw/ip` | 879 | 79 | — | unresolved primitives deep in closures |
| cva6 | 458 | 32 | 68% | vendor IP |
| ibex | 345 | 17 | — | vendor IP |
| rsd | 258 | 26 | 88% | vendor primitives |
| frost | 256 | 8 | **98%** | vendor IP |
| CV32E40P | 154 | 8 | — | vendor IP |
| Cores-VeeR-EL2 | 143 | 41 | 81% | one bad module poisons `beh_lib.sv` |
| riscduino | 304 | 169 | 62% | SkyWater PDK not vendored |
| verilog-pcie | 123 | 1 | 53% | one primitive; 8 duplicate board copies |
| qeciphy | 98 | 3 | 51% | FPGA IP in example wrappers |
| openCologne-PCIE | 77 | 12 | 81% | Xilinx hard blocks |
| litex_wr_nic | 39 | 11 | **100%** | LiteX wrappers to vendor IP |
| picorv32 | 31 | 16 | 39% | `picosoc` not in file set |
| pcievhost | 34 | 16 | — | vendor IP |
| fwrisc-s | 54 | 10 | — | — |
| difftest | 11 | 5 | 75% | C++/SV glue |

**Not indexable:** `logisim-cpu-project` (0 HDL files — Logisim `.circ`
schematics), `XiangShan` and `openPiton` (unreachable at `master`/`main`).

### Three things the table shows

**Coverage and completeness are independent.** `litex_wr_nic` is **100%
file-coverage and not complete** — all 22 files contributed a unit, but 11
instantiations are unresolvable vendor IP. Reporting either number alone misleads,
which is why both are printed.

**Coverage separates repositories into three bands**: real hand-written RTL lands
68–100% (frost 98%, neorv32 89%, rsd 88%, cva6 68%); mixed design+DV 30–62%;
verification libraries 4–22% (riscv-dv 4%, wave_rerunner 22%). Repository size
predicts nothing — riscduino has 232 files at 62%, riscv-dv has 89 at 4%.

**Half the famous cores are not RTL.** BOOM ships 2 Verilog files and rocket-chip
11; both are Chisel generators whose Verilog is build output. A structural RTL
indexer correctly has nothing to say about them, and saying so is the right answer
rather than a failure.

Waveforms in those runs are real: modules were simulated with Icarus Verilog and
the VCDs rendered by `wengold ide`.

**`complete: false` is the honest reading** for most of them: their file sets, as
collected, do not contain everything they instantiate, so results downstream of
those blocks are `unknown` by design.

## What this does not do

- **It does not verify a whole SoC end to end.** The formal front-end covers
  register-level RTL (above). The graph, the kernel and the IDE work at core scale;
  the prover does not.
- **It has no design partner yet.** Every number here is self-assessed, measured on
  public designs rather than on a team's real regression history.
- **The z3 encoding is not differentially tested** against a reference on a corpus
  of real files. The kernel's *invalidation* logic is fuzz-tested; the symbolic
  encoding is covered by unit tests, which is weaker.
- **Analog and mixed-signal verification and physical signoff** are out of scope.

## Reproducing a failure

A verification result is only useful if it can be re-created.

```bash
wengold repro capture ./rtl --result sim_uart --detail "assertion failed at cycle 21"
wengold repro replay  --bundle sim_uart.repro.json --root ./rtl
```

A bundle pins a **per-file content hash** of the design file set, the result id,
kind, status, the kernel's verdict at capture time, the tool and its version, and
the detail.

**A reproducer that reproduces everything reproduces nothing.** `replay` returns
`reproduced=False` the moment the file set has drifted, and names the files —
changed, missing and added reported **separately**, because they mean different
things:

```
  drift    changed: a.sv
  => NOT REPRODUCED — the inputs differ from the capture
     1 file(s) changed since capture: the result is about different code
```

Reporting "still fails" against changed RTL would be the most damaging bug this
feature could have, so three tests pin the refusals rather than the successes.

**Scope, stated plainly:** WENGOLD does not run simulators itself; it records what
a tool reported. `replay` re-establishes the *inputs* and re-checks the recorded
outcome. It does not re-invoke VCS, Verilator or Icarus.

## Singular configurations

```bash
wengold singularity ./rtl --damp
```

A kinematic singularity is where a Jacobian loses rank; the dependency analogue is
a block whose change voids an unbounded share of the evidence. `conditioning` is
worst blast radius over median; `damping` reports what isolating a block behind a
stub buys **and what it costs**. On neorv32: 86 blocks, condition number 2.78 —
well conditioned, with `neorv32_prim_fifo` the most load-bearing at 29% of the
design.

## Status

**v0.67.3 — 1014 tests passing**, 15 skipped, and CI runs them on every push. The
graph, kernel, ledger, MCP server, formal loop, register-map and CDC front-ends,
the VHDL front-end, root cause, the IDE with waveforms, the text-to-spec
front-end, failure reproduction, singularity analysis, the Accellera CDC/RDC
standard (Clauses 4, 5, 6, 7, 8 and the Annex C fixtures — all 34 findings from the
CDC audit are closed, each pinned by a test that fails without the fix), the
Accellera Functional Safety Language v1.0 with its ISO 26262 / IEC 61508 metrics,
spec-to-RTL generation (`vibe`), fix suggestion (`review`), the agentic loop
(`agentic`), and an optional local model for drafting and explanation
(`doctor --presets`) are all implemented and tested. There is also a native desktop
app (`wengold desktop`), a VS Code / Cursor extension, and a Linux installer
(`linux/install.sh`) with a `.deb`. See [`docs/roadmap.md`](docs/roadmap.md).

### How the numbers are checked

Every test count in this README was measured from a fresh checkout of the tag, not
from a working tree. That is not fussiness: two releases published counts from a
local tree that the branch did not match, and `tools/verify-release.sh` exists
because of it — it downloads a tarball to a temporary directory, runs the suite
with `PYTHONPATH` unset, and fails on a count mismatch.

The accepted-syntax tables for the two standards are generated from the standards'
own tables and compared against a checked-in copy of them
(`tests/fixtures/fsl_syntax_tables.json`, `tests/fixtures/cdc_attributes.json`).
That is also not fussiness: two releases shipped a parser that **rejected valid
input**, because the tables were written from memory and the tests used the same
invented tables. A green suite over a guessed specification proves the guesses are
self-consistent and nothing else. `tests/test_input_formats.py` now refuses to let a
format reject unknown input without saying what verifies its accepted set.

Thirty repositories have been indexed (table above). The defects that running
against real projects exposed are all fixed and pinned by tests, and each was a
**silent wrong answer rather than a crash** — the shape this project has had to
learn to look for:

| defect | how it was found |
| --- | --- |
| `complete: True` on 4.5% coverage | riscv-dv |
| one note printed six times | wave_rerunner |
| a transitive invalidation explained as "cannot explain it" | Anvil-Pro |
| duplicate module definitions merged silently | rustdv/rustdv |
| **one bad module marking every module in its file unresolved** | Veer EL2: 41 unresolved → 5 |
| the MCP server serving an empty graph and crashing on `[1,2,3]` | security audit |

### What is not done

Stated here rather than discovered by a reader:

- **The formal front-end accepts 11 of 27 files** on a modern UVM project. It
  refuses the rest rather than guessing: `` `ifdef ``, `generate` and multiple
  clock domains are out of scope.
- **The CDC work does not decide whether a crossing is safe.** It reads and writes
  the Accellera format and checks the collateral against the RTL; a passing
  assertion means the declared data stability held, not that the design is correct.
- **A safety metric is computed, but not judged.** `wengold fsl --metrics` computes
  SPFM, LFM, PMHF, SFF, PFH and PFD from the declared failure rates, printing the
  formula and its inputs. It **refuses on a partial sum** rather than reporting a
  ratio over missing rates, and it never compares a metric against an ASIL or SIL
  target — so a clean report is not a safety case. (This line used to say no metric
  was computed at all; that stopped being true at v0.57.0 and the README was not
  updated with it.)
- **One soundness test is not stable across toolchains.** `test_slice_write_soundness`
  reported `unknown` where it expects `fail` in one full-suite run that had the OSS
  CAD Suite on `PATH`, and did not reproduce without it. It is written down here
  rather than dropped, because a soundness check that changes answer with the
  toolchain is the kind of thing this project should not lose track of.
- **The generated testbench is checked, not proved.** `vibe` asserts reset values,
  write/read-back, write-1-to-clear and read-only behaviour, and simulates. It does
  not prove the RTL matches the spec — a passing run means the checks it generated
  held.
- **The ML layer does not beat a majority baseline** against simulation ground
  truth. It is measured, reported, and kept behind the CLI.
- **No design partner yet.** Every number here is self-assessed. This is the gap
  that matters most: the tool has been measured against public repositories and its
  own fixtures, never against a team's real signoff flow.
- **No commercial EDA tool has been run.** WENGOLD drives Verilator, iverilog/vvp,
  Yosys and GHDL when they are on `PATH`, and reports `tool_missing` — never a pass —
  when one is not. It has never driven VCS, Xcelium, Questa, Vivado or JasperGold,
  because none of them can be obtained here. The commercial-tool rows in the coverage
  table are claims about the interface, not about runs.
- **The local-model client is proven against a real model, but not against Sarvam.**
  `tools/verify-real-model.py` drives it with real weights over real HTTP (v0.66.1),
  which is how the markdown-fence defect was found. Sarvam-M is 24B and needs ~16 GB,
  so it has never been run here; `wengold doctor --llm` against a served copy is the
  remaining check.

## Documentation

- [Architecture specification](docs/WENGOLD-Architecture-Spec.pdf) — the graph, the validity kernel and the ledger, in full.
- [Open-core strategy](docs/WENGOLD-OpenCore-Strategy.pdf) — the model, the market and the boundary.
- [Pitch deck](docs/WENGOLD-Pitch-Deck.html) — open it in any browser.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/roadmap.md`](docs/roadmap.md) — short reference and plan.
- [`docs/measurements/`](docs/measurements/) — the real-project runs behind the numbers above.

## License

Dual-licensed under either of

- the MIT License ([`LICENSE-MIT`](LICENSE-MIT))
- the Apache License, Version 2.0 ([`LICENSE-APACHE`](LICENSE-APACHE))

at your option. Contributions are accepted under the same terms unless you state
otherwise.
