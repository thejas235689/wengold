# Roadmap

- **v0.1** — graph, kernel, ledger, tool registry, CLI, demo. ✅
- **v0.2** — elaboration-based dependencies; conservative kernel with graph
  completeness; rerun propagation; reproducible evidence; working cocotb flow;
  reliable tool outcomes; hardened ledger with checkpoint; operational agents and
  a working MCP server. ✅ *(this release)*
- **v0.3** — register-map and CDC front-ends (SystemRDL, IP-XACT); Surelog and
  Verible elaboration backends.
- **v0.4** — formal loop (SymbiYosys + Z3) with counterexample-guided repair.
- **v0.5** — regression farm, coverage closure, waiver register.
- **v1.0** — spec-to-signoff on the open toolchain, reproducible on Sky130.

## Non-goals

WENGOLD does not claim foundry signoff. Missing tools and unpinned PDKs are
reported as missing, never as passes. Analog and mixed-signal verification is out
of scope for the core.
