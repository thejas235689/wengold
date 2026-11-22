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

## Native desktop integration

The native Agents workspace exposes:
- A configurable maximum-iteration control.
- A graph-based plan inspection action.
- A read-only Loop & Stitch preview action.
- A reviewed-manifest input and **Run Reviewed Tool Agents** action.
- A structured result view with iteration count, agent reports, stitched
  outputs, conflicts, evidence references and explicit execution claims.

The real execution path is implemented in
`wengold/verification/manifest_agents.py`. It calls the existing
`dv_pipeline.run_regression` and `eda_flows.inspect_manifest` functions for
explicitly selected, project-local manifests of kind `simulation`, `uvm`,
`rustdv_sim` or `pss`. Each manifest becomes an independent agent. The
coordinator records iteration and final results in
`results/loop-stitch-ledger.jsonl`.

The current real-manifest runner deliberately executes each selected manifest
once. It does not rerun an unchanged failing test: a future retry must follow a
reviewed repair or changed input and new provenance fingerprint. Formal
manifests are not currently routed through this regression runner because a
formal PASS requires engine-specific proof-status parsing, not just a zero
process exit code. No RTL repair, formal proof, coverage closure or signoff is
implied by a simulation-manifest result.

## Current implementation boundary

This increment provides a synchronous Python orchestration API, native
workspace preview controls and unit tests. It does not provide distributed
workers or claim end-to-end CI validation. Tool execution continues through
WENGOLD's existing adapters.


## Proof-aware formal agents and reviewed repair proposals

Formal manifests with `kind: "formal"` are routed to
`SymbiYosysManifestAgent`, not the generic simulation runner. The manifest
must explicitly declare `engine: "symbiyosys"`, `proof_mode: "prove"`,
project inputs, and fresh proof artifacts. The agent parses the SBY
`DONE (...)` / `Status:` result using the existing outcome parser:
- Parsed PASS plus successful execution, unchanged inputs and fresh declared
  artifacts is a formal-agent PASS.
- A parsed counterexample is FAIL.
- UNKNOWN, unparseable output, stale/missing artifacts or changed inputs are
  INCONCLUSIVE.
- Missing tool/configuration and unsupported bounded/cover modes are BLOCKED.

A generic process exit code of zero is never treated as a proof. In particular,
BMC and cover PASS are not accepted as unbounded proof. The UI routes selected
formal manifests through the same **Run Reviewed Tool Agents** action.

The Agents workspace also exposes **Create Repair Proposal**. The
`RepairProposalAgent` uses the existing deterministic Repairer to create a
candidate unified diff in memory. It validates a project-local RTL path and
records source/candidate hashes. It never writes source files. The UI shows the
proposal and explicitly marks `verification_status: NOT_RUN`; an engineer
must review and apply a patch separately, then run fresh simulation/formal
checks. The proposal agent's PASS means only that a proposal was produced,
not that the RTL is correct or fixed.

Tests cover SBY PASS parsing, bounded-mode rejection, counterexample FAIL,
repair proposal non-mutation and path confinement.


Example formal manifest (adjust paths to the actual SBY work directory and
confirm that the declared PASS artifact is generated by the selected SBY
version/configuration):

```json
{
  "kind": "formal",
  "engine": "symbiyosys",
  "proof_mode": "prove",
  "argv": ["sby", "-f", "formal/top.sby"],
  "inputs": ["rtl/top.sv", "formal/top.sby"],
  "artifacts": ["results/formal/PASS"],
  "timeout_seconds": 900
}
```

The manifest runner validates the executable and inputs before launch. A
manifest that declares a nonexistent or non-fresh PASS artifact cannot yield a
formal-agent PASS. The actual SBY task must also be configured for a prove-mode
proof; WENGOLD's explicit `proof_mode` field is a declared contract and should
be checked against the reviewed `.sby` file by the engineer.
