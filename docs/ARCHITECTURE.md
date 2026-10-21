# WENGOLD architecture

```
        spec / TRM ──┐
                     ▼
   RTL ─┐      ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
regmap ─┼────▶ │  wengold-graph │────▶ │ wengold-kernel │────▶ │ wengold-ledger │
  clocks─┤     │  (elaboration  │      │ (validity +    │      │ (append-only,  │
  resets─┤     │   + graph)     │      │  minimize)     │      │  hash-chained) │
   cdc ──┘     └───────┬───────┘      └───────┬───────┘      └───────┬───────┘
                       │                       │                      │
                       └───────────┬───────────┴──────────┬───────────┘
                                   ▼                      ▼
                          ┌────────────────┐     ┌──────────────────┐
                          │ wengold-agents │────▶│  wengold-tools    │
                          │ plan/run/debug │     │  Verilator, Yosys,│
                          │ repair         │◀────│  SymbiYosys, ...  │
                          └────────────────┘     └──────────────────┘
```

The kernel is the heart. Everything else exists to feed it or to act on its answer.

## The validity kernel

On each change the kernel answers one question per prior result:

| Verdict | Meaning | Action |
|---|---|---|
| **valid** | No dependency on the change. | Keep it, with its evidence. |
| **invalidated** | Depends on, or is reached by, the change. | Re-run. |
| **unknown** | Evidence insufficient, dependency uncertain, or the graph incomplete. | Re-establish; never assume. |

It is conservative by construction. It returns `VALID` only when it can prove the
result is unaffected; an empty dependency set, a dependency on an unresolved
node, or a graph built without full elaboration all yield `UNKNOWN`.

`minimum_new_evidence()` then returns only what must be re-established — the
invalidated and unknown results, closed over everything downstream of them in the
result graph.

## The graph

Built by an **elaborator**, not a regex scan: it resolves `include` chains,
`define` macros, `package`/`import`, `parameter`s, `generate` blocks and `.f`
file lists, and reports what it cannot resolve. Nodes: RTL modules, packages,
files, register-map fields, tests, assertions, coverage points, runs,
requirements, clock/reset roots, CDC crossings. Edges are typed: `drives`,
`instantiates`, `verifies`, `covers`, `traces_to`, `clocked_by`, `reset_by`,
`crosses`, `includes`, `imports`, `parameterizes`, `defined_in`, `generates`,
`constrained_by`, and `unknown`.

An unresolved node — a missing include, an instantiation with no definition, a
branch behind an undefined macro — forces `UNKNOWN` for anything downstream of
it. Missing dependencies must never preserve evidence.

## The ledger

Append-only, hash-chained JSONL, hardened with advisory file locking for
concurrent writers, sequence and chain validation on read, malformed-record
handling, and a **trusted checkpoint** written out of band so deletion of
trailing records is detectable — something a local hash chain alone cannot see.

## Reproducible evidence

Every verdict is bound to the RTL, testbench, assertions and constraints it
consumed, the tool, version, arguments, seed, working directory and timeout, and
an environment fingerprint — reduced to a single `repro` hash. Change any input
and the evidence no longer describes the design, so the result is stale.
