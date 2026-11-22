# WENGOLD Loop & Stitch Orchestration

## Purpose

Loop & Stitch is the bounded feedback and integration layer for specialist
verification agents. It coordinates agents; it does not replace tool adapters,
the dependency graph, the validity kernel, or the append-only evidence ledger.

## Loop

Each iteration performs:

1. Resolve agent dependency order.
2. Execute an agent only after all declared dependencies pass.
3. Pass only successful upstream outputs to downstream agents.
4. Collect structured status, findings, output values, and evidence references.
5. Stitch the successful outputs and check required output keys.
6. Stop on a consistent all-pass result, a terminal failure/block, or the
   configured iteration limit.

Retryable failures can be attempted again up to LoopPolicy.max_iterations.
Exhaustion returns INCOMPLETE; it never upgrades a failure to PASS. Missing
tools, timeouts, crashes, and inconclusive formal runs should be mapped to
non-PASS agent statuses by the adapter that owns the tool result.

## Stitch

The stitcher merges outputs from passing agents only:

- Equal values for the same key are deduplicated.
- Conflicting values are surfaced, not silently overwritten.
- A conflict can be resolved only by an explicit key-to-agent mapping.
- Required output keys are checked after merging.
- Failed, blocked, and inconclusive agent outputs are excluded.

The resolution mapping is policy input and should itself be recorded in the
run context by the calling application.

## Suggested specialist agents

| Agent | Typical responsibility | Example upstream dependencies |
|---|---|---|
| Spec / Requirement | Requirement extraction and trace links | none |
| Slang Frontend | Parse, elaborate, normalize SV design | Requirement |
| Lint / Static | Structural and lint checks | Slang Frontend |
| UVM / Cocotb | Dynamic simulation and test execution | Slang Frontend |
| SVA / Formal | Assertions, bounded proof, property checks | Slang Frontend |
| Yosys | Synthesis-oriented checks and formal preparation | Slang Frontend |
| RustDV | Independent test/verification path | Slang Frontend |
| Coverage | Merge requirement, functional, code, assertion, formal metrics | Dynamic + Formal |
| Debug / Triage | Correlate failures, traces, and evidence | Dynamic + Formal |
| Signoff Packager | Build report from validated evidence | Coverage + Debug |

These are roles, not claims that every adapter is currently implemented or
available in a particular installation.

## Evidence and signoff

When supplied, the coordinator appends one loop_stitch_iteration event per
iteration and one loop_stitch_result event to the existing ledger. The
coordinator's PASS means only that all participating agents returned PASS and
the requested output contract was stitched consistently. It is not design
signoff. The signoff workflow must separately validate evidence freshness,
tool availability, requirement coverage, waivers, and human approval.

## Current implementation boundary

This increment provides a synchronous Python orchestration API and unit tests.
It does not launch EDA tools itself, provide distributed workers, persist agent
state outside the ledger, or claim end-to-end CI validation. Tool execution
continues through WENGOLD's existing adapters.
