# WENGOLD Lean Verification — Engineering Backlog

This backlog decomposes docs/LEAN_VERIFICATION_ARCHITECTURE.md into reviewable work. It is intentionally staged so the existing WENGOLD graph, validity kernel and append-only ledger remain the source of truth.

## Workstream A — Repository baseline and compatibility

- A1 Inventory existing graph node/edge types and dependency traversal.
- A2 Inventory validity classifications, evidence minimization and invalidation rules.
- A3 Inventory ledger schema, run reproducibility and artifact storage.
- A4 Inventory existing adapters, especially Cocotb, and current MCP methods.
- A5 Inventory CI workflows, supported tool versions and Linux installation paths.
- A6 Produce adapter capability matrix: tested, experimental, unavailable and unsupported.
- A7 Add architecture decision records for schema versioning, tool isolation and result semantics.

Acceptance: existing tests remain green; no duplicate graph, ledger or adapter is introduced.

## Workstream B — Contracts and provenance

- B1 Add versioned DesignIR and RequirementIR models.
- B2 Add RunRequest, ExecutionPlan, RunRecord and NormalizedResult.
- B3 Add EvidenceRecord and typed outcome/status enums.
- B4 Add JSON schema export and backward-compatible migrations.
- B5 Add content digest and source-span utilities.
- B6 Add immutable run manifest and artifact manifest.
- B7 Add common adapter capability and diagnostic models.
- B8 Add contract tests for malformed payloads, unknown schema versions and missing provenance.

Acceptance: all persisted verification artifacts have stable schema version and reproducible provenance.

## Workstream C — Slang and RTL frontend

- C1 Detect Slang executable/library and report version/capabilities.
- C2 Implement safe argv-based compilation/elaboration adapter.
- C3 Capture compilation units, include paths, defines and parameters.
- C4 Normalize hierarchy, ports, types, interfaces, packages and source maps.
- C5 Preserve parser/elaboration diagnostics and unsupported constructs.
- C6 Add fixtures for packages, interfaces, parameterized modules, generate blocks, enums, structs and assertions.
- C7 Add malformed/unsupported syntax tests; incomplete parse cannot be signoff evidence.

Acceptance: canonical RTL fixtures yield stable DesignIR and source references across clean CI runs.

## Workstream D — Simulation adapters

- D1 Implement Verilator capability discovery, lint, compile and simulation.
- D2 Normalize warnings, waivers, test status, seed and runtime.
- D3 Collect VCD/FST and coverage artifacts when supported.
- D4 Harden existing Cocotb adapter against the shared protocol.
- D5 Pin Python/Cocotb/simulator versions and test dependencies.
- D6 Add deterministic replay and JUnit parsing.
- D7 Implement UVM report ingestion independent of a specific simulator.
- D8 Add optional licensed/self-hosted UVM execution runner.
- D9 Ensure unsupported UVM constructs or missing license produce explicit status.

Acceptance: real installed tools are exercised in CI; mock fixtures supplement but do not replace integration tests.

## Workstream E — Formal and Yosys

- E1 Add property registry linked to requirements and source spans.
- E2 Add SVA subset/capability declaration.
- E3 Add Yosys adapter for supported elaboration and structural checks.
- E4 Add SymbiYosys/BMC adapter where installed and supported.
- E5 Capture assumptions, solver, depth, partitions, engine and proof mode.
- E6 Add expected-proof, expected-counterexample, timeout and unsupported-property fixtures.
- E7 Detect vacuity and unreachable cover properties where supported.
- E8 Ensure bounded success cannot be reported as unbounded proof.

Acceptance: each formal claim reports its exact proof strength and assumptions.

## Workstream F — RustDV

- F1 Inspect and pin the actual RustDV revision and documented interface.
- F2 Create a capability probe and version report.
- F3 Define supported interchange format and process lifecycle.
- F4 Implement adapter only for verified supported operations.
- F5 Add conformance tests and independent reference-model fixture.
- F6 Mark unsupported capabilities explicitly; do not invent command-line flags.

Acceptance: RustDV status is evidence-backed, not inferred from repository presence.

## Workstream G — Planner and lean evidence reuse

- G1 Map source/config/constraint/tool changes into existing graph nodes.
- G2 Implement impact traversal to requirements, properties, tests and evidence.
- G3 Implement hard mandatory-evidence constraints.
- G4 Add minimum-new-evidence selection with explicit rationale.
- G5 Add reuse proof containing dependency closure and digest comparisons.
- G6 Add adversarial tests: changed include file, define, parameter, constraint, tool version and testbench.
- G7 Add periodic full-regression sentinel policy.
- G8 Benchmark full suite versus lean plan on identical revisions.
- G9 Track false reuse as a release-blocking metric.

Acceptance: no impacted mandatory evidence is skipped; all reuse decisions can be independently re-derived.

## Workstream H — Coverage and debug

- H1 Add requirement coverage ingestion with traceability.
- H2 Add functional coverage adapter schema and denominator tracking.
- H3 Add code coverage where simulator support exists.
- H4 Add assertion attempt/pass/fail/vacuity/unknown metrics.
- H5 Add formal coverage and proof-depth reporting.
- H6 Add mutation-test result ingestion.
- H7 Add deterministic failure fingerprinting and log parser fixtures.
- H8 Add seed replay and failing waveform window extraction.
- H9 Add pass/fail trace comparison and transaction-level correlation.
- H10 Keep LLM hypotheses separate from confirmed root-cause records.

Acceptance: dashboard reports distinct coverage dimensions, exclusions, unknowns and evidence provenance.

## Workstream I — Local LLM and safety

- I1 Define strict JSON schemas for planner suggestions and triage hypotheses.
- I2 Record model/version/quantization/prompt/template/context/output digests.
- I3 Add local model adapter with timeout and resource budget.
- I4 Validate generated sequences/properties before execution.
- I5 Require deterministic tool adapter to execute every proposed test.
- I6 Block model-originated shell commands, file writes and signoff changes.
- I7 Add prompt-injection and malicious RTL/comment fixtures.
- I8 Add human approval for patches, waivers and policy modifications.

Acceptance: LLM failure or hallucination cannot create PASS or weaken signoff.

## Workstream J — CI, security and release

- J1 Add PR workflow for schemas, Slang, Verilator, Yosys/formal, Cocotb and planner tests.
- J2 Add optional UVM and RustDV jobs with explicit NOT_CONFIGURED status.
- J3 Add nightly broad regression, mutation and longer formal runs.
- J4 Add clean-checkout reproducibility workflow.
- J5 Upload signed evidence manifest and immutable artifacts.
- J6 Add container isolation, resource limits and network restrictions.
- J7 Add dependency and artifact scanning.
- J8 Add signoff policy tests for stale evidence, expired waivers and UNKNOWN mandatory checks.
- J9 Publish per-engine capability matrix and known limitations.

Acceptance: CI never treats skipped, unavailable or unsupported engines as passing evidence.

## Definition of done

A task is done only with implementation, unit tests, integration tests against real tools where available, negative-path tests, documentation, provenance and CI evidence. A UI control or adapter stub alone is not completion.

## Suggested sequencing

Milestone 0: A (baseline).  
Milestone 1: B + C (contracts and Slang).  
Milestone 2: D (Verilator/Cocotb/UVM).  
Milestone 3: E + F (formal and RustDV).  
Milestone 4: G + H (lean planner, coverage and debug).  
Milestone 5: I + J (LLM safety, CI and release).

Do not start with an AI agent that chooses tests. First establish the graph, schemas, tool capability truth, reproducible runs and validity rules. Intelligence is only as trustworthy as the evidence infrastructure beneath it.
