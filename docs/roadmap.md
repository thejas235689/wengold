# Roadmap

- **v0.1** — graph, kernel, ledger, tool registry, CLI, demo. DONE
- **v0.2** — elaboration-based dependencies; conservative kernel with graph
  completeness; rerun propagation; reproducible evidence; working cocotb flow;
  reliable tool outcomes; hardened ledger with checkpoint; operational agents and
  a working MCP server. DONE
- **v0.3** — register-map and CDC front-ends (SystemRDL, IP-XACT). DONE
- **v0.4** — formal loop with counterexample-guided repair: property IR, a bounded
  RTL front-end, explicit-state and z3 engines, CEGAR. DONE
- **v0.5** — a real front-end: a preprocessor (`include`, `define`, `ifdef`) and a
  SystemVerilog parser (slang/pyslang) behind `index --backend`, with the regex
  elaborator as fallback; interfaces recognised as design units; tool adapters
  verified against verilator, yosys, sby and cocotb; measured on OpenTitan and
  CVA5. DONE
- **v0.6** — spec-driven generation: `wengold generate` reads a spec (YAML or
  JSON) and emits SystemVerilog, then re-reads the emitted code and checks it
  against the spec; the formal subset widened to accept what generated RTL
  contains — parameter port lists, localparams, partial register writes,
  backticks in comments, parameterised widths. DONE (this release)
- **v0.7** — root-cause analysis: `wengold rootcause` explains why a node is
  unresolved (the construct, the file, and whether the missing module comes from
  a declared-but-unvendored dependency), why a result is invalidated (which
  changes reach it, ranked, with the dependency path), and why a verdict is
  unknown (the modelling gaps in its closure). Unresolved reasons are recorded
  structured, not only as prose. ✅ *(this release)*
- **v0.8** — a project IDE: `wengold ide` writes one self-contained HTML file with
  the file tree, the RTL, a line-level diff of the change, the blocks the change
  puts in doubt, and the root cause and dependency path for each. ✅ *(this release)*
- **v0.9** — waveforms in the IDE: a failing property's counterexample is drawn
  below the panes (the failing cycle marked), and a simulator's VCD renders the
  same way. Two bugs fell out of it: the emitter wrote `import <module>::*;` in
  the properties file, and that bogus package name overwrote the module's node in
  the graph, silently dropping the block. ✅ *(this release)*
- **v0.10** — machine learning, three methods with honest evaluations:
  unsupervised clustering of blocks by dependency signature (and reuse candidates),
  supervised failure prediction labelled by running the real formal engine, and
  Q-learning for budgeted check ordering — which does **not** beat greedy-by-ratio
  and says so. Found and fixed on the way: the z3 engine discarded the slice range
  on a non-blocking assignment, so `q[3:0] <= e` became `q <= e` and it **proved
  false properties** on any register block. ✅ *(this release)*
- **v0.11** — scale and speed: OpenTitan `hw/ip` indexed end to end (1,857 files,
  2,561 nodes, 10,748 edges, 884 blocks, 78 unresolved, 26 s), with the ML run
  against it. **A 97× performance fix**: `in_edges` scanned the whole edge list, so
  41,527 calls against 10,710 edges was 21.8 s of a 22.4 s run; adjacency maps and
  a memoised ancestor/descendant cache took one RL instance from 29 s to 0.30 s.
  `rebuild_index()` added for code that mutates `edges` directly. ✅ *(this release)*
- **v0.12** — a VHDL front-end: entities, architectures, instantiations, packages
  and `use` clauses, so a VHDL design indexes at all. neorv32 (68 VHDL files, no
  SystemVerilog) gives 86 blocks / 1,262 edges / 0 unresolved. Structural only —
  no ports, no signal references. Also fixed: the IDE's file filter did not know
  about `.vhd`, so it showed 8 files of 76, and the ML features counted PARAM
  nodes as blocks (664 parameters against 86 blocks on neorv32), so
  "depends on N blocks" and the clustering features were measuring parameters.
  ✅ *(this release)*
- **v0.13** — the IDE grows up: a summary row (blocks / packages / parameters /
  edges / unresolved / complete / files / changed / pending) and a block table
  (block | file | depends on | consumed by | cluster | verdict) that is clickable
  through to the source. Fixed: block rows carried absolute graph paths while the
  tree and sources were relative, so a click did nothing. ✅ *(this release)*
- **v0.14** — regression and DBSCAN. Linear regression, CART, a random forest and
  gradient boosting (the mechanism behind XGBoost/LightGBM, not those libraries),
  scored against each other and a mean baseline on an exact kernel-computed label;
  and DBSCAN, whose real use here is naming blocks whose dependency signature
  resembles nothing else. CNNs and Transformers are deliberately **not** added —
  no image data, and a transformer belongs at a spec front-end that WENGOLD would
  then have to check rather than reimplement. ✅ *(this release)*
- **v0.15** — a transformer, written out: multi-head attention, encoder/decoder
  blocks and learned positional embeddings on a small reverse-mode autodiff tape,
  with **every backward pass verified against finite differences**. It reads a
  sentence into a register spec — `wengold spec-from-text` — and the spec is then
  checked by the parser, the validator, the conformance checker and the engine:
  the model drafts, the checker decides. Measured honestly: 100% exact on unseen
  combinations of trained words, 0% on held-out vocabulary. ✅ *(this release)*
- **v0.16** — an LSTM encoder-decoder, at the same interface as the transformer so
  the two are compared on one corpus, one split and one metric. The LSTM was given
  *more* training and reaches 5% exact against the transformer's 100% — the
  fixed-size bottleneck that attention was invented to fix. The under-trained LSTM
  also demonstrates the front-end's honest limit: it misreads a sentence, and the
  validator, the conformance checker and the prover all accept the result, because
  they check the spec's internal consistency and not its correspondence to
  English. ✅ *(this release)*
- **v0.17** — the accumulated v0.15–v0.16 work and whole-project elaboration
  groundwork, folded into the v0.17.1 release rather than described separately.
  ✅ *(this release)*
- **v0.18** — the generative families, given a job and a yardstick: a transformer
  with autoregressive decoding (already the encoder-decoder in `learn/`), plus a
  VAE, a GAN and a diffusion model that generate **stimulus**. Scored against the
  engine's own reachable-state set on a passcode design whose completing symbol is
  absent from the corpus: **diffusion reaches the deep state 4.4x as often as
  random; the VAE and the GAN land at or below random; none reproduces the
  corpus.** The conclusion is that a generative model extends a pattern it was
  shown and cannot invent what is missing from its data. ✅ *(this release)*
- **v0.19** — the agent layer: perceive, reason, plan, act, reflect, adapt. Every
  stage is wired to real data (the graph, the kernel's verdicts, a live tool probe,
  the ledger), and the reasoning trace is generated from the graph so it cannot
  assert what the graph does not support. The honest finding: **planning order buys
  nothing** — three strategies settle identical numbers at every budget, because
  the kernel's minimum evidence is already minimal and one check at the base
  cascades. The ordering problem is not a search problem, which is also why the
  earlier Q-learning lost to a two-line heuristic. ✅ *(this release)*
- **v0.20** — three agent patterns: **ReAct** (thought → action → observation, each
  step chosen from the last observation), **test-time scaling** (beam search over
  plan orderings, measured under check failures) and **multi-agent orchestration**
  (planner → reviewer → executor, where the reviewer re-derives the obligations and
  can refuse). Measured: beam beats greedy by **6–9%** and wins 11 of 12 at the
  larger budget, while **best-of-32 random sampling is no better than greedy** —
  structured search helps, brute force does not. ✅ *(this release)*
- **v0.20.1** — the agent layer checked against real designs (neorv32, picorv32),
  which corrected the previous release's headline. **Beam search gains exactly 0%
  on real projects** (0 of 8 seeds on both, all strategies tie at every budget),
  because every invalidated simulation unblocks exactly one coverage result at the
  same cost — symmetric work, so no ordering is better. The +6–9% was measured on
  an all-or-nothing structure I built, and it does not transfer. Also fixed: the
  perception line reported the *end* state beside the opening plan; a ReAct step
  budget of 40 truncated picorv32's run; and a budget check placed inside the loop
  without a break, which hung it. ✅ *(this release)*
- **v0.21** — belief, memory, MCTS and hierarchy, from the agentic taxonomy. A
  POMDP belief over P(check passes), fed by a **dual-stream memory** (episodic runs,
  semantic facts) persisted to disk. The finding: **value-of-information ordering
  loses** to greedy by 4–8% because a failed check halts the run, while **inverting
  the same belief — safest check first — beats greedy by up to 34.8%** and wins
  10/10 at the larger budgets. That is the first component in the agent layer to
  measurably beat the two-line heuristic. MCTS with UCB1 and hierarchical
  decomposition (GoalAct, ReAcTree) are implemented and gain nothing reliable.
  PPO, CTDE, meta-DRL and internalised planning are deliberately **not**
  implemented, with the reasons written down. ✅ *(this release)*
- **v0.22** — a **swarm** scheduler: decentralised control, local interaction (slices
  partitioned by IP, no scheduler object), and fault tolerance. The control
  experiment killed the headline: the swarm's 18.8-vs-10.4 win over the central
  planner on OpenTitan came entirely from **not halting on the first failure** —
  a central planner that continues scores 18.5. What survives is resilience, and
  measuring it showed the metric was wrong: under a check budget killing workers
  changes nothing, because one survivor spends the whole budget. Under a round
  budget, losing 2 of 4 workers costs ~22% and losing 3 costs ~34%. MARL/IPPO, NAS,
  HyEvo/SAGE/SelfEvolve, GNN adaptation and A2A/ANP are **not** implemented, with
  reasons recorded. ✅ *(this release)*
- **v0.24** — a **cognitive-ability scorecard**: every ability scored as measured
  (with a number), failed, or not-measurable-here (with the reason). 10 of 14
  measurable, 1 measured and failed, 4 untestable in this environment.
  Neuromorphic computing, neuroevolution, catastrophic-forgetting research and any
  AGI benchmark claim are **not** implemented — the reasons are in the table.
  ✅ *(this release)*
- **v0.25** — whole-project elaboration (one compilation unit rather than per file);
  a file set taken from the project's own build metadata (FuseSoC `.core`, `.f`
  filelists) instead of hand-passed include dirs; HJSON register maps.

> **This log stopped at v0.25 and was reconstructed at v0.54.5** from the GitHub
> release pages, so the entries below are summaries of what shipped rather than
> plans written before the fact. Anything between v0.25 and v0.54 that is not
> mentioned here is in [`CHANGELOG.md`](../CHANGELOG.md), which was kept current.

### v0.26 – v0.28 · measurement, and refusing to guess

- **v0.26** — off-policy evaluation; the finding was that **IPS is a trap** — it
  reported +406% on data where the policy had never taken the action.
- **v0.27** — waveform features for every learner. **v0.27.1** — duplicate module
  definitions were merged silently, and Anvil-Pro showed it was the third instance
  of one bug class: a bad failure mode, not a wrong answer.
- **v0.28** — failure reproduction, and refusing to lie: the tool reports the
  smallest command that reproduces a failure, and says when it cannot find one.

### v0.29 – v0.36 · the app

- **v0.29 – v0.31** — WENGOLD becomes a desktop app, then a real window rather than
  a browser shell.
- **v0.34 – v0.35** — a CLI pane at the bottom, and the three bugs a screenshot
  found that endpoint tests could not. The pane is a transcript, not a prompt.
- **v0.36** — one panel with a revision strip.

### v0.37 – v0.39 · the CDC/RDC standard

- **v0.37** — Accellera CDC/RDC v1.0: the Tcl format and Clauses 4 and 6.
- **v0.38** — IP-XACT (Clause 7) and the semantic consistency rules.
- **v0.39** — Clause 8: WENGOLD *emits* CDC assertions. **v0.39.1** — the Annex C
  fixtures, and the two parser bugs they found.

### v0.40 – v0.42 · elaboration and the formal front-end

- **v0.40** — one bad module no longer poisons every module in its file.
- **v0.41 – v0.42** — the formal front-end went **2 of 27 → 9 of 27 → 11 of 27** on
  a modern UVM project, by widening the accepted subset rather than guessing.
- **v0.42.1 – v0.42.2** — CI that actually runs, a site that stops overstating, and
  a build that is verifiable from a tarball.

### v0.43 – v0.48 · tools, and measuring from the repository

- **v0.43** — tensor operators, and the division trap.
- **v0.44** — a Linux installer and a `.deb`.
- **v0.45** — the agent acts on real tools; a sweep over six repositories found
  three bugs.
- **v0.46** — `.f` filelists, language routing, and one thing explicitly not
  verified.
- **v0.47** — GHDL runs: **54 of 54** VHDL units analysed.
- **v0.48** — simulation, and the **first non-zero settled count**:
  4 settled of 2 checks, reward 2.000.
  **v0.48.1** corrected v0.48.0's claim, which had been measured on a working tree
  the branch did not match. **v0.48.2** added `tools/verify-release.sh` so that
  cannot recur.

### v0.49 – v0.53 · generating and reviewing code

- **v0.49** — `vibe`: spec → RTL → self-checking testbench → simulation → verdict.
- **v0.50** — CDC crossing classification: synchronised, unsynchronised, or a
  multi-bit bus that must not be given a 2-FF synchroniser.
- **v0.51** — `vibe` in the app, with the generated source visible.
- **v0.52** — `review`: suggestions drawn only from checks that actually ran.
- **v0.53** — fewer lines, and the prover that nearly paid for it; the line count is
  kept in a manifest; a tighter testbench; a label (`100% cov`) that meant nothing,
  corrected.

### v0.54 · FSL, and proving the accepted sets

- **v0.54.0** — Accellera **Functional Safety Language v1.0**: sixteen Tcl commands,
  checked against the standard's clauses, plus the one check no standard can
  specify — an FMEDA naming an element that is not a block in the RTL.
- **v0.54.1 – v0.54.2** — the FSL command tables were written from memory and would
  have rejected conformant files; ten of sixteen were wrong. Regenerated from the
  standard's own tables, with a checked-in fixture and a test that compares.
- **v0.54.3** — the same audit on the CDC side found **four attributes missing**.
- **v0.54.4 – v0.54.5** — no format may reject unknown input without evidence that
  its accepted set is right, and the evidence for each must be independent rather
  than a thing compared against itself.

## Planned

- **v1.1** — a Surelog/Verible elaboration backend; SymbiYosys as an external
  engine; regression farm, coverage closure, waiver register.
- **v1.2** — safety metrics computed rather than collected: SPFM, LFM, PMHF and SFF
  from per-failure-mode rates, which needs the ISO 26262 and IEC 61508 formulas the
  FSL standard references but does not restate.
- **v2.0** — spec-to-signoff on the open toolchain, reproducible on Sky130.

The honest state of the plan: the items above are the ones with a shape I can
picture. The largest thing missing is not on this list and is not technical —
**there is no design partner**, so every number in this repository is self-assessed.

## Non-goals

WENGOLD does not claim foundry signoff. Missing tools and unpinned PDKs are
reported as missing, never as passes. Analog and mixed-signal verification is out
of scope for the core.
