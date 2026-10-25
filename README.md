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

```bash
git clone https://github.com/thejas235689/wengold.git
cd wengold
python -m pip install -e ".[open]"     # open toolchain only
python -m wengold.cli --help
```

`numpy` is required by `wengold learn` and `wengold spec-from-text` and by nothing
else. The graph, the kernel, the front-ends and the CLI are standard library only.

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
wengold learn dbscan ./rtl                # clustering, triage, RL, regression
wengold spec-from-text "..." --arch transformer
wengold serve                             # run the MCP server over stdio
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

Every number below came from running the tool on the project named. The full runs
are in [`docs/measurements/`](docs/measurements/).

| project | blocks | edges | unresolved | complete |
| --- | --- | --- | --- | --- |
| OpenTitan `hw/ip` | 879 | 10,743 | 78 | false |
| cva6 | 458 | 3,260 | 32 | false |
| ibex | 345 | 2,079 | 17 | false |
| CV32E40P | 154 | 872 | 8 | false |
| qeciphy_riverlane | 83 | 269 | 3 | false |
| neorv32 | 86 | 1,262 | 0 | **true** |
| lxp32-cpu (VHDL) | 34 | 163 | 0 | **true** |
| minerva (generated) | 51 | 50 | 0 | **true** |

Waveforms in those runs are real: modules were simulated with Icarus Verilog and
the VCDs rendered by `wengold ide`. `tools/wave_harness.py` is the harness that
does it — it generates a testbench from a module's own port list.

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

## Status

**v0.17.1 — 311 tests passing.** The graph, kernel, ledger, MCP server, formal
loop, register-map and CDC front-ends, the VHDL front-end, root cause, the IDE with
waveforms, the ML methods and the text-to-spec front-end are all implemented and
tested. See [`docs/roadmap.md`](docs/roadmap.md).

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
