# Changelog

Every version of WENGOLD, newest first. Formats follow [Keep a Changelog](https://keepachangelog.com/);
versions follow [Semantic Versioning](https://semver.org/).

**A note on v0.5.1 – v0.17.0.** Those fourteen versions were developed and their
code shipped on `main`, but no tag or release was cut for any of them — the work
accumulated from v0.5.0 to v0.17.1 without a single checkpoint. The tags were
**backfilled** on 2026-10-25: each points at the commit whose `pyproject.toml`
carries that exact version, verified one by one. They have no release notes
attached, because writing them now would be inventing a chronology that did not
happen; this file is the record instead. `git checkout v0.9.0` works, and that is
what the tags are for.

---

## [0.21.1] — 2026-10-25

### Run on OpenTitan (1,849 HDL files, 879 blocks, 10,730 edges)
- 2,553 nodes, 79 unresolved, 505 issues; 882 results — 488 valid, 13 invalidated,
  **381 unknown**, 394 need new evidence.
- **Safest-first wins again, and by far more**: measured on results settled from the
  open set, +107% at budget 10, +218% at 25, **+255% at 50**, winning 6/6 worlds.
  Value-of-information ordering collapses to 0.9 against greedy's 3.3 — it runs the
  flakiest check first and the run halts immediately.

### Fixed
- **The reasoning trace contradicted itself on 381 results.** Each unknown result
  was explained as "0 of its dependencies are unresolved in the graph, so its
  currency cannot be decided" — a count of zero explaining nothing. The agent's
  check looked only at *direct* dependencies, but the kernel tests the whole
  upstream closure: `adc_ctrl_core_sim` was unknown because `prim_flop` and
  `prim_sync_reqack` sat deeper in its closure. The trace now quotes the kernel's
  own reason instead of re-deriving it, and a test asserts no unknown trace states
  something the kernel does not support.
- `Context` now carries `approximate`, so a graph built without a full elaboration
  is named as the reason rather than silently folded into a wrong one.

## [0.21.0] — 2026-10-25

### Added
- **`Belief`** — a POMDP belief over P(check passes) per open result, with entropy
  and value-of-information.
- **`Memory`** — dual-stream: episodic runs and semantic facts, persisted to disk.
  Supplies the belief's priors.
- **`mcts`** — MCTS with UCB1 (selection, expansion, rollout, backpropagation).
- **`hierarchy`** — GoalAct (global milestones, local execution) and ReAcTree
  (recursive decomposition), measured on milestones completed.

### Results
- **Value-of-information ordering loses to greedy by 4–8%** — VOI assumes a
  negative observation is actionable, but a failed check halts the run here.
- **Inverting the same belief wins**: safest check first beats greedy by **+3.9%
  on neorv32** and **+34.8% on picorv32** at budget 12, winning 10/10 worlds. The
  first component in the agent layer to beat the two-line heuristic.
- MCTS gains nothing on the real designs (79.08 vs 79.82 on neorv32).
- GoalAct wins on picorv32 (0.28 vs 0.00 milestones) and loses on neorv32 (1.42 vs
  1.56); ReAcTree is worse than GoalAct on both.

### Not implemented, deliberately
- PPO/actor-critic, CTDE, DRL, meta-DRL, internalised planning. The reasons are in
  the README — the short version is that the first four are further RL attempts at
  a problem a one-line belief heuristic now wins by 35%, and the last is not
  possible without a model, a corpus and training compute.

### Fixed
- `reactree` emitted synthetic sub-goal names (`cov56/a`) that nothing could
  settle, and placed a milestone after only half its members.

## [0.20.3] — 2026-10-25

### Documentation
- Recorded the **v0.3.0 defect** accurately: no commit in the history ever
declares version 0.3.0 — the code went 0.2.0 → 0.4.0 and the v0.3 work shipped
under the old version. The tag is left in place rather than rewritten.
- Added the missing 0.20.2 and 0.20.3 entries to this file.

## [0.20.2] — 2026-10-25

### Added
- **`CHANGELOG.md`**, documenting every version v0.3.0 onward.
- **Fourteen backfilled tags** (v0.5.1 – v0.17.0), each verified to point at the
commit whose `pyproject.toml` carries that exact version. No releases attached.
- Three roadmap entries filled: v0.11, v0.13 and v0.17 were absent entirely.

## [0.20.1] — 2026-10-25

### Changed
- The agent layer checked against real designs (neorv32, picorv32), which
  **corrected v0.20.0's headline**: beam search gains **exactly 0%** on real
  projects (0 of 8 seeds on both, all strategies tie at every budget). The
  invalidated work is symmetric — every simulation unblocks one coverage result at
  the same cost — so no ordering is better. The +6–9% was measured on an
  all-or-nothing structure that these designs do not produce.

### Fixed
- The report said `0 need new evidence` beside a 14-step plan: `ctx.todo = []` at
  the end of a run mutated the object the report read from.
- A ReAct step budget of 40 truncated picorv32's run; it now scales with the open
  work and says when the budget, not the work, ended it.
- A budget check placed inside the loop without a `break` hung the run.
- The reviewer reported a missing tool once per step instead of once per tool.

## [0.20.0] — 2026-10-25

### Added
- **ReAct** (`agent --mode react`): thought → action → observation, each step
  chosen from the last observation. A failing check changes the next action from
  continue to diagnose.
- **Test-time scaling** (`agent --mode search`): beam search over plan orderings,
  measured under check failures. Beam beats greedy by 6–9% on all-or-nothing
  groups; best-of-32 random sampling is no better than greedy.
- **Multi-agent orchestration** (`agent --mode orchestrate`): planner → reviewer →
  executor. The reviewer re-derives the plan's obligations and refuses a plan that
  misses an open result, relies on an uninstalled tool, or schedules a step before
  its dependency.

## [0.19.0] — 2026-10-25

### Added
- **The agent layer**: perceive, reason, plan, act, reflect, adapt. Each stage is
  wired to real data — the graph, the kernel's verdicts, a live tool probe, the
  ledger.
- A reasoning trace generated **from the graph**, so it cannot assert what the
  graph does not support.

### Fixed
- A coverage result invalidated *through a result it summarises* was explained as
  "the change touches 0 nodes, so it cannot hold" — a contradiction.

### Known limits
- Planning order buys nothing on the structures tested: the kernel's minimum
  evidence is already minimal and settling the base cascades.

## [0.18.0] — 2026-10-25

### Added
- **VAE, GAN and diffusion** (`learn generative`), written on the autodiff tape,
  generating *stimulus* and scored against the engine's own reachable-state set.
- Five gradient-checked ops: `binary_cross_entropy`, `gaussian_kl`, `concat_cols`,
  `split_cols`, `reparameterise`.

### Results
- Diffusion reaches the deep state **4.4× as often as random**; the VAE and the GAN
  land at or below random; none reproduces its corpus.

### Fixed
- The VAE's reparameterisation had no gradient path to `logvar`.
- The stimulus corpus leaked the completing symbol and completed the chain itself.

## [0.17.1] — 2026-10-25

The first release since v0.5.0 — it carries everything from v0.5.1 to v0.17.0.

### Added
- **`rootcause`**, **`ide`** (self-contained HTML: tree, RTL, diff, block table,
  waveform panel), **`regmap`** and **`cdc`** front-ends, **`learn`** (clustering,
  supervised triage, RL, regression, DBSCAN), **`spec-from-text`** (transformer and
  LSTM), the **VHDL front-end**, and **`tools/wave_harness.py`**.

### Fixed
- **One stray VHDL file silently dropped every SystemVerilog file**: cva6 has one
  `.vhd` and 477 `.sv`, and the single VHDL unit made the builder return early —
  4 blocks instead of 458.
- **The z3 engine discarded the slice range** on non-blocking assignments, so
  `q[3:0] <= e` became `q <= e`, and it **proved false properties**.
- VCD signal names were not scope-qualified, so a testbench and its children
  reported two signals both called `q`.
- The README claimed "verify a digital SoC end to end" while the formal front-end
  covers register-level RTL (2 of 125 CV32E40P files, 0 of 165 OpenTitan files).

## [0.17.0] — 2026-10-25 *(tag backfilled)*

Whole-project elaboration groundwork and the accumulated v0.15–v0.16 work; folded
into the v0.17.1 release notes rather than described separately.

## [0.16.0] — 2026-10-25 *(tag backfilled)*

### Added
- An **LSTM encoder-decoder** at the same interface as the transformer, so the two
  are compared on one corpus, one split and one metric.
- `spec-from-text --arch lstm`.

### Results
- The LSTM was given **more** training and reaches 5% exact against the
  transformer's 100% — the fixed-size bottleneck attention was invented to fix.

## [0.15.0] — 2026-10-25 *(tag backfilled)*

### Added
- A **transformer**, written out: multi-head attention, encoder/decoder blocks,
  learned positional embeddings, on a small reverse-mode autodiff tape, with every
  backward pass verified against finite differences.
- `wengold spec-from-text`: a sentence becomes a register spec, which the parser,
  validator, conformance checker and proof engine then check.

### Results
- 100% exact on unseen *combinations* of trained words; **0% on held-out
  vocabulary**. A grammar reader, not a language model.

## [0.14.0] — 2026-10-25 *(tag backfilled)*

### Added
- **Regression** (linear, CART, random forest, gradient boosting) and **DBSCAN**,
  scored against each other and a mean baseline on an exact kernel-computed label.

### Not added, deliberately
- CNNs and Transformers — no image data, and a transformer belongs at a spec
  front-end WENGOLD would then have to check. *(The Transformer half of this
  decision was reversed in v0.15.0 at the maintainer's request.)*

## [0.13.0] — 2026-10-25 *(tag backfilled)*

### Added
- An IDE **summary row** (blocks / packages / parameters / edges / unresolved /
  complete / files / changed / pending) and a **block table** (block | file |
  depends on | consumed by | cluster | verdict), clickable to open the source.

### Fixed
- Block rows carried absolute graph paths while the tree and sources were
  relative, so clicking did nothing.

## [0.12.0] — 2026-10-25 *(tag backfilled)*

### Added
- A **VHDL front-end**: entities, architectures, instantiations, packages and
  `use` clauses. neorv32 (68 VHDL files, no SystemVerilog) gives 86 blocks /
  1,262 edges / 0 unresolved. Structural only — no ports, no signal references.

### Fixed
- The IDE's file filter did not know `.vhd`, so it showed 8 files of 76.
- ML features counted PARAM nodes as blocks (664 parameters against 86 blocks on
  neorv32), so "depends on N blocks" was measuring parameters.

## [0.11.0] — 2026-10-25 *(tag backfilled)*

### Added
- OpenTitan `hw/ip` indexed end to end: 1,857 files, 2,561 nodes, 10,748 edges,
  884 blocks, 78 unresolved, in 26 s. ML run against it.

### Fixed
- **A 97× performance fix**: `in_edges` scanned the whole edge list — 41,527 calls
  against 10,710 edges was 21.8 s of a 22.4 s run. Adjacency maps plus a memoised
  ancestor/descendant cache took one RL instance from 29 s to 0.30 s.
- `rebuild_index()` added for code that mutates `edges` directly.

## [0.10.0] — 2026-10-25 *(tag backfilled)*

### Added
- **Machine learning, three methods with honest evaluations**: unsupervised
  clustering by dependency signature (with reuse candidates), supervised failure
  prediction labelled by running the real formal engine, and Q-learning for
  budgeted check ordering — which does **not** beat greedy-by-ratio, and says so.

### Fixed
- **The z3 engine discarded the slice range** on a non-blocking assignment, so
  `q[3:0] <= e` became `q <= e` and it **proved false properties** on any register
  block.
- `str(EdgeKind.INSTANTIATES).endswith("instantiat")` never matched, so depth and
  edge counts were always zero; `_depth` walked the wrong direction.

## [0.9.0] — 2026-10-25 *(tag backfilled)*

### Added
- **Waveforms in the IDE**: a failing property's counterexample is drawn below the
  panes with the failing cycle marked, and a simulator's VCD renders the same way.
- `wengold/wave.py`: `from_trace`, `parse_vcd`, `from_formal`.

### Fixed
- A VCD off-by-one (the snapshot was taken before applying that timestamp's
  changes).
- The emitter wrote `import <module>::*;` in the properties file, and that bogus
  package name overwrote the module's graph node — silently dropping the block.
- Path normalisation, so a changed block is never silently unmatched.

## [0.8.0] — 2026-10-25 *(tag backfilled)*

### Added
- **A project IDE** (`wengold ide`): one self-contained HTML file with the file
  tree (clean / changed / pending), the RTL, a line-level diff, the blocks the
  change puts in doubt, and the root cause and dependency path for each.

### Fixed
- Root selection picked the wrong node (by descendant count).
- A zip `-x` pattern silently dropped `docs/WENGOLD-Pitch-Deck.html`.

## [0.7.0] — 2026-10-25 *(tag backfilled)*

### Added
- **Root-cause analysis** (`wengold rootcause`): why a node is unresolved (the
  construct, the file, whether the missing module comes from a declared but
  unvendored dependency), why a result is invalidated (which changes reach it,
  ranked, with the dependency path), and why a verdict is unknown (the modelling
  gaps in its closure). Unresolved reasons are recorded structured, not as prose.

### Fixed
- The transitive `descendants()` walk.
- `str(e.kind).endswith("instantiates")` never matching.

## [0.6.1] — 2026-10-25 *(tag backfilled)*

Patch on v0.6.0.

## [0.6.0] — 2026-10-25 *(tag backfilled)*

### Added
- **Spec-driven generation**: `wengold generate` reads a spec (YAML or JSON) and
  emits SystemVerilog, then re-reads the emitted code and checks it against the
  spec.
- The formal subset widened to accept what generated RTL contains: parameter port
  lists, localparams, partial register writes, backticks in comments,
  parameterised widths.

## [0.5.1] — 2026-10-25 *(tag backfilled)*

Patch on v0.5.0.

## [0.5.0] — 2026-10-22

### Added
- **A real front-end**: a preprocessor (`include`, `define`, `ifdef`) and a
  SystemVerilog parser (slang/pyslang) behind `index --backend`, with the regex
  elaborator as fallback.
- Interfaces recognised as design units.
- Tool adapters verified against verilator, yosys, sby and cocotb; measured on
  OpenTitan and CVA5.

## [0.4.0] — 2026-10-22

### Added
- **Formal loop with counterexample-guided repair**: property IR, a bounded RTL
  front-end, explicit-state and z3 engines, CEGAR.

## [0.3.0] — 2026-10-21

### Added
- **Register-map and CDC front-ends**: SystemRDL and IP-XACT.

### Known defect — the version was never bumped

`pyproject.toml` at this tag says **0.2.0**, not 0.3.0. The v0.3 work landed in
commit `b91dea23f3` ("v0.3 — result contracts, reuse obligations, …") without a
version bump, and the tag was placed one commit later, on `c0e3120531` (the
Pages landing page), which still said 0.2.0. The next bump went straight to
0.4.0 in `1335f2cbb8`.

**No commit in the history ever declares version 0.3.0**, so this cannot be
fixed by retagging — there is no correct commit to move the tag to. It is left
as it is, and recorded here, rather than rewritten: rewriting a published tag
breaks anyone who has already fetched it, and it would not make the code say
something it never said. `v0.4.0` onwards are all correct.

---

## How to read the tags

```bash
git tag -l 'v0.*' | sort -V      # every version, including the backfilled ones
git checkout v0.9.0              # the waveform work, as it stood
```

Releases (with notes) exist for v0.3.0, v0.4.0, v0.5.0 and v0.17.1 onward. The
fourteen backfilled tags deliberately have no releases attached: a release page
that lists 2026-10-25 as the date for twelve different historical versions would
be a worse record than an honest gap.
