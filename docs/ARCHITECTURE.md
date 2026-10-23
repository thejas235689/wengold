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

## The result contract

A result carries what it establishes and under what conditions it may be reused —
`Claim`, `Scope` (files, configuration, reset), `Method` (kind, engine, settings),
`Assumptions`, `Evidence` (fingerprints, commands, proof status, artifacts) and
`Limits` (supported configuration, modeling gaps). Without it a stored `PASS` is
read more broadly than the check supports.

## Four independent questions

| Question | Field | Values |
|---|---|---|
| What happened during execution? | `execution` | passed / failed / timed_out / crashed / tool_missing |
| Is the evidence current? | `currency` (computed) | current / stale / unknown / withdrawn |
| What does it establish? | `establishes` | none / observation / bounded_check / proof |
| Has engineering accepted it? | `acceptance` | pending / accepted / rejected / waived |

They are never collapsed. A waiver is an engineering decision and never becomes a
technical pass: `decide()` reports `reusable` (technical) apart from
`accepted_for_use` (reusable or waived).

## Reuse as an auditable decision

`decide()` evaluates explicit obligations — evidence current, established at the
required level, acceptance not rejected, contract present (when required), config
in scope, assumptions discharged, supporting evidence not withdrawn — and exports
a `DecisionRecord`. `verify_decision()` re-derives the decision from that record
alone, independently of the kernel's own path.

## Typed dependencies and composition

Edges carry a `DependencyType` (compilation, elaboration, behavioral, assumption,
configuration, requirement), each with its own reassessment rule. Blocks carry
assumptions and guarantees; `check_subsystem()` verifies that a parent's
assumptions are discharged by its children, so a proven block is not promoted into
a proven subsystem.

## Verifying the kernel itself

`wengold/kernel/reference.py` is an independent implementation of the invalidation
semantics (explicit path enumeration, not a closure). `wengold/kernel/invariants.py`
checks five invariants — no upgrade under added uncertainty, known changes
invalidate consumers, no confidence from removed information, determinism, and
withdrawal propagation — over generated graphs (`gengraph.py`) and against the
reference. `invariants.fuzz()` returns zero violations.

## Formal verification

The property IR is written once and consumed by every backend: compiled to
SystemVerilog assertions for SymbiYosys, and to the in-process engines.

```
Property (IR) ──┬─▶ SVA module        (sby / commercial formal)
                ├─▶ explicit engine   (reachability fixpoint)
                └─▶ z3 engine         (BMC + k-induction)
```

A bounded RTL front-end parses a documented subset into a transition function; the
explicit engine explores the reachable state space and proves the property at a
fixpoint, the z3 engine unrolls the transition relation and closes by k-induction.
A run that neither proves nor finds a counterexample is **BOUNDED**, not a pass,
and anything outside the subset is **UNKNOWN**.

`formal/loop.py` wraps this in a counterexample-guided loop: check, diagnose,
propose a repair, apply, re-check, bounded by a budget. Each property leaves a
`Contract` whose method is `proof` only when it really was proven.

## Front-ends

`graph/` reads source through one of two backends, chosen automatically:

- **slang** (`graph/slang_backend.py`) — a real SystemVerilog front-end
  (`pyslang`). Modules, hierarchy instantiations, interfaces, packages, imports
  and parameters come from an actual parse tree, so the graph reflects what the
  language says rather than what the text looks like.
- **regex** (`graph/elaborate.py`) — the bounded elaborator, used when slang is
  not installed. It is a fallback, not a parser.

Both run behind `graph/preprocess.py`, a preprocessor that resolves `` `include ``
against the include path, expands object-like `` `define `` macros, and evaluates
`` `ifdef ``/`` `ifndef ``/`` `elsif ``/`` `else `` against the project's defines.
Function-like macros are left alone rather than naively substituted — their
bodies use `` `" `` and `` `` `` — and an unexpandable macro used as a statement is
dropped whole, including a multi-line call.

Anything a file does not resolve — a parse error, or an instantiation with no
definition in the file set — marks the module unresolved, and the kernel then
refuses to call anything downstream VALID.

## Register maps and clock domains

`graph/regmap.py` parses SystemRDL and IP-XACT into one normalised address map
(registers, fields, addresses, widths, `sw`/`hw` access, reset values), reports
address collisions and overlapping fields, and adds register/field nodes with
`drives` edges so a policy change propagates.

`graph/cdc.py` finds the clock domains in a module, resolves which domain each
signal's value comes from (including through combinational logic), and reports
every signal read in one domain but written in another as a `cdc.*` node with
`crosses` edges. Signals whose domain cannot be determined are reported, and the
module is marked unresolved — so the kernel returns UNKNOWN downstream rather than
trusting a stale result across a crossing.
