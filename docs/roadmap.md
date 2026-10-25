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
- **v0.10** — whole-project elaboration (one compilation unit rather than per file);
  a file set taken from the project's own build metadata (FuseSoC `.core`, `.f`
  filelists) instead of hand-passed include dirs; HJSON register maps.
- **v1.1** — a Surelog/Verible elaboration backend; SymbiYosys as an external
  engine; regression farm, coverage closure, waiver register.
- **v2.0** — spec-to-signoff on the open toolchain, reproducible on Sky130.

## Non-goals

WENGOLD does not claim foundry signoff. Missing tools and unpinned PDKs are
reported as missing, never as passes. Analog and mixed-signal verification is out
of scope for the core.
