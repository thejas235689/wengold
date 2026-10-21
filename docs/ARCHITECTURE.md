# WENGOLD architecture

```
        spec / TRM ──┐
                     ▼
   RTL ─┐      ┌───────────────┐      ┌───────────────┐      ┌───────────────┐
regmap ─┼────▶ │  wengold-graph │────▶ │ wengold-kernel │────▶ │ wengold-ledger │
  clocks─┤     │  (dependency   │      │ (validity +    │      │ (append-only,  │
  resets─┤     │   graph)       │      │  minimize)     │      │  hash-chained) │
   cdc ──┘     └───────┬───────┘      └───────┬───────┘      └───────┬───────┘
                       │                       │                      │
                       └───────────┬───────────┴──────────┬───────────┘
                                   ▼                      ▼
                          ┌────────────────┐     ┌──────────────────┐
                          │ wengold-agents │────▶│  wengold-tools    │
                          │ plan/generate/ │     │  Verilator, Yosys,│
                          │ debug/repair   │◀────│  SymbiYosys, VCS… │
                          └────────────────┘     └──────────────────┘
```

The kernel is the heart. Everything else exists to feed it or to act on its answer.

## The validity kernel

On each change the kernel answers one question per prior result:

| Verdict | Meaning | Action |
|---|---|---|
| **valid** | No dependency on the change. | Keep it, with its evidence. |
| **invalidated** | Depends on, or is reached by, the change. | Re-run. |
| **unknown** | A dependency is uncertain. | Re-establish; never assume. |

Then `minimum_new_evidence` returns only what must be re-established. Everything
still valid is carried forward.

## The graph

Nodes: RTL modules, register-map fields, tests, assertions, coverage points,
runs, requirements, clock/reset roots, CDC crossings. Edges are typed:
`drives`, `instantiates`, `verifies`, `covers`, `traces_to`, `clocked_by`,
`reset_by`, `crosses`, and `unknown`. An `unknown` edge forces the kernel to
return UNKNOWN for anything downstream — the safe direction.

## The ledger

Append-only, hash-chained JSONL. Every entry carries `prev`, so the record is
tamper-evident. Status (done / stale / failed) is always *derived* from the
ledger, never stored as a flag.
