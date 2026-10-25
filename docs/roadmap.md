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
- **v0.12** — a VHDL front-end: entities, architectures, instantiations, packages
  and `use` clauses, so a VHDL design indexes at all. neorv32 (68 VHDL files, no
  SystemVerilog) gives 86 blocks / 1,262 edges / 0 unresolved. Structural only —
  no ports, no signal references. Also fixed: the IDE's file filter did not know
  about `.vhd`, so it showed 8 files of 76, and the ML features counted PARAM
  nodes as blocks (664 parameters against 86 blocks on neorv32), so
  "depends on N blocks" and the clustering features were measuring parameters.
  ✅ *(this release)*
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
- **v0.21** — whole-project elaboration (one compilation unit rather than per file);
  a file set taken from the project's own build metadata (FuseSoC `.core`, `.f`
  filelists) instead of hand-passed include dirs; HJSON register maps.
- **v1.1** — a Surelog/Verible elaboration backend; SymbiYosys as an external
  engine; regression farm, coverage closure, waiver register.
- **v2.0** — spec-to-signoff on the open toolchain, reproducible on Sky130.

## Non-goals

WENGOLD does not claim foundry signoff. Missing tools and unpinned PDKs are
reported as missing, never as passes. Analog and mixed-signal verification is out
of scope for the core.
