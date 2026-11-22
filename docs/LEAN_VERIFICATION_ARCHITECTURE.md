# WENGOLD Lean Verification — Research-Grade Architecture

Status: proposed architecture and implementation contract
Branch: feat/lean-verification-research-architecture

## 1. Mission and safety invariants

WENGOLD Lean Verification (WLV) extends the existing WENGOLD design graph, validity kernel, append-only evidence ledger, adapters, agent orchestrator and MCP server. It must not create a parallel graph or evidence database.

Mission: select the smallest defensible verification workload for a change while preserving all mandatory evidence; combine static analysis, simulation, formal methods and independent checking; make results reproducible and invalidatable.

Non-negotiable invariants:
- PASS, FAIL, UNKNOWN and INCONCLUSIVE are distinct outcomes.
- Missing tools, parser failures, unsupported constructs, timeouts and incomplete proofs are never PASS.
- Bounded model-checking success is not an unbounded proof.
- Code coverage is not proof of correctness.
- LLM output is advisory, never signoff evidence.
- AI cannot waive requirements, suppress failures, execute arbitrary commands or approve signoff.
- Lean selection may reuse evidence only when the complete dependency closure and tool/configuration provenance remain valid.
- Full regression remains a periodic and release-level sentinel.

## 2. Architecture

    RTL / specification / constraints / regmap / clocks / resets
                              |
                     Intake + provenance
                              |
                 Slang parse / typecheck / elaborate
                              |
              DesignIR + RequirementIR + source maps
                              |
                 Existing WENGOLD design graph
                              |
                 Risk and evidence-gap planner
                              |
                    Lean execution plan
                              |
      +---------+---------+---------+---------+---------+
      |         |         |         |         |         |
     UVM      SVA/Formal Verilator  Yosys    Cocotb   RustDV
      |         |         |         |         |         |
      +---------+---------+---------+---------+---------+
                              |
              Result and coverage normalization
                              |
             Differential checking / debug triage
                              |
               Existing validity kernel + reuse
                              |
                Append-only evidence ledger
                              |
                Signoff policy + human review
                              |
                  CI / Desktop / MCP APIs

## 3. Core subsystems

1. Intake and DesignIR: Slang-based SystemVerilog parse, typecheck and elaboration; hierarchy, parameters, defines, packages, interfaces, ports, source locations, clock/reset domains and diagnostics.
2. Requirement intelligence: requirement extraction with exact source provenance, requirement type, risk, acceptance criteria and links to properties, tests and coverage.
3. Planner: graph impact traversal, risk prioritization, mandatory evidence constraints, resource budgets and defensible evidence reuse.
4. Engine adapters: capability discovery, validation, planning, isolated execution, result normalization and artifact collection.
5. Coverage intelligence: separate requirement, functional, code, assertion, formal and mutation coverage with denominators and exclusions.
6. Debug intelligence: deterministic log parsing, seed replay, waveform comparison, transaction correlation, failure clustering and ranked hypotheses.
7. Evidence and signoff: content-addressed run manifests, validity dependencies, append-only audit, waiver lifecycle and human approval.
8. Local LLM advisor: test ideas, requirement mapping suggestions, log summaries and patch proposals; all outputs schema-validated and reviewed.

## 4. Canonical data contracts

All persisted objects include schema_version, stable ID, timestamp, producer, provenance and content digest.

DesignIR:
- design_id, source_revision, top, parameters, defines, compilation_units
- modules, instances, ports, nets, variables, types, interfaces and packages
- clock_domains, reset_domains, synchronizers and state_elements
- protocol interfaces, source spans and elaboration diagnostics
- tool name/version, command digest and environment/container digest

RequirementIR:
- requirement_id, source document digest/span, statement and rationale
- kind: functional, protocol, safety, performance, reset, security or low_power
- severity/risk, verification intent, acceptance criteria and owner
- linked design elements, properties, tests, coverage points and waivers
- status: unplanned, planned, exercised, proven, failed, waived or unknown

VerificationPlan:
- plan_id, target revision, change set and graph snapshot digest
- impacted requirements and dependency closure
- selected activities, engine, command profile, timeout and resource budget
- expected evidence, stop conditions, rationale and dependencies
- skipped activities with machine-checkable reuse proof
- seeds, replay metadata, tool and container digests

RunRecord:
- run_id, plan_id, engine, tool/version and executable digest
- argv, controlled environment, cwd, input/config/source digests
- seed, timestamps, exit status, timeout and resource status
- stdout/stderr, logs, VCD/FST, coverage and artifact digests
- normalized result and parser version

EvidenceRecord:
- evidence_id, requirement_id, claim type and result status
- producer run IDs, inputs, assumptions, proof depth/completeness
- coverage model/version, source/config digests and validity dependencies
- reviewer, waiver reference and status: valid, invalidated, unknown or disputed

Use typed outcomes: PASS, FAIL, UNKNOWN, INCONCLUSIVE, NOT_CONFIGURED, UNSUPPORTED and SKIPPED. The latter three are execution states, not successful evidence.

## 5. Engine integration contracts

Common adapter protocol in wengold/verification/adapters/base.py:

    class VerificationAdapter(Protocol):
        def capabilities(self) -> AdapterCapabilities: ...
        def validate(self, request: RunRequest) -> ValidationReport: ...
        def plan(self, request: RunRequest) -> ExecutionPlan: ...
        def execute(self, plan: ExecutionPlan) -> RunRecord: ...
        def normalize(self, record: RunRecord) -> NormalizedResult: ...
        def collect_artifacts(self, record: RunRecord) -> list[ArtifactRef]: ...

Adapter requirements:
- Declare language/tool subset, supported coverage formats, formal modes, trace formats, determinism and known limitations.
- Execute argv arrays without shell interpolation, in isolated work directories with explicit timeout and resource limits.
- Never mutate the source checkout.
- Missing executable returns NOT_CONFIGURED; unsupported feature returns UNSUPPORTED.
- Contract tests cover normal logs, malformed logs, timeout, missing binary, nonzero exit and deterministic replay.

Slang: primary SV frontend. Preserve source spans, elaborated hierarchy, parameters, packages, interfaces, generate constructs and diagnostics. No regex-based SV parsing. Partial elaboration is marked incomplete and cannot satisfy signoff.

SystemVerilog/UVM: compile and run actual UVM environments on supported simulators. Normalize test name, seed, phase/objection errors, scoreboard failures, assertions and report summaries. Do not claim generic UVM support through Verilator unless the exact supported subset is demonstrated.

SVA/Formal: property registry, assumptions, assertions, cover properties, BMC and supported proofs. Record bounds, assumptions, solver, partitions and proof status. Distinguish bounded PASS, proven PASS, counterexample FAIL, UNKNOWN and timeout. Unsupported SVA must be surfaced, never silently dropped.

Yosys: structural checks, synthesis-oriented elaboration, SAT/formal preparation and supported equivalence flows. Record frontend, passes, blackboxes, memory mapping, defines and assumptions. A lint run is not a formal proof.

Verilator: fast lint, compile and supported RTL simulation. Capture warnings, waivers, flags, seeds, tests, coverage and traces. Report simulator limitations.

Cocotb: Python-driven tests, reference models, scoreboards and protocol stress. Pin Python, Cocotb, simulator and dependencies; collect test discovery, JUnit and coverage.

RustDV: independent Rust drivers, monitors or reference models only where the actual RustDV revision and interface support them. Pin revision and create conformance tests. Do not invent a CLI or claim integration before verification.

Local LLM: requirement mapping suggestions, test ideas, failure summaries and candidate fixes. Record model/version/quantization, prompt/template/context and output digests. Model output is never correctness evidence.

## 6. Service and MCP API

Versioned service methods:
- POST /api/v1/designs:ingest — source manifest, top, defines and parameters; returns design_id and elaboration status.
- GET /api/v1/designs/{design_id} — DesignIR summary and source revision.
- POST /api/v1/requirements:ingest — requirements with source provenance.
- POST /api/v1/plans — design_id, change_set, risk_policy and budget; returns plan and rationale.
- POST /api/v1/runs — plan_id and selected activity; returns run_id.
- GET /api/v1/runs/{run_id} — status, normalized result, logs and artifacts.
- POST /api/v1/coverage:ingest — typed coverage with producer run IDs.
- GET /api/v1/coverage/{design_id} — coverage dimensions, denominators and exclusions.
- POST /api/v1/evidence:revalidate — change digest; returns valid/invalidated/unknown evidence.
- GET /api/v1/signoff/{design_id} — gate result, open risks, waivers and evidence manifest.
- POST /api/v1/triage — run IDs and artifacts; returns ranked hypotheses, not an accepted root cause.

All writes require schema validation, authorization, audit logging, request IDs and idempotency keys. Enforce payload size limits. Never expose arbitrary shell execution through an API.

## 7. Lean planner and evidence reuse

1. Compute changed source, configuration, constraint and tool digests.
2. Traverse typed dependencies from changed nodes to impacted requirements, properties, tests, coverage and evidence.
3. Reuse only evidence whose complete dependency closure is unchanged and whose producer/tool/config remains accepted by policy.
4. Select minimum new evidence satisfying all hard constraints for impacted requirements, mandatory safety properties and signoff policy.
5. Order by cost and diagnostic value: schema validation, Slang elaboration, lint, focused tests, formal checks, unit simulation, then integration and broad regression.
6. If evidence is conflicting, incomplete or nondeterministic, mark UNKNOWN and escalate.
7. Keep full regression and periodic randomized stress as anti-optimization sentinels.

Optimization objective: minimize runtime/cost subject to hard evidence constraints. Risk scores prioritize work but cannot relax mandatory requirements. A skipped test requires an explicit reuse proof and policy approval.

## 8. Coverage and quality metrics

Keep coverage dimensions separate:
- Requirement coverage = requirements with valid linked evidence / applicable requirements.
- Functional coverage = hit bins / applicable bins, with exclusions and unreachable bins reviewed.
- Code coverage = line/branch/toggle/FSM only where tool support exists.
- Assertion coverage = attempts, successes, failures, vacuity, disabled and unknown properties.
- Formal coverage = cover reachability, proof status, depth and assumptions.
- Mutation effectiveness = valid non-equivalent mutants detected / valid non-equivalent mutants.
- Cross-engine agreement = agreement on shared deterministic scenarios; never merge unlike denominators.

Track:
- wall time and CPU-hours per change
- selected tests / total tests, reuse rate and invalidation precision
- false evidence reuse rate (critical metric; target zero)
- stale evidence accepted (target zero)
- requirement traceability and mandatory requirement closure
- proof depth, assumptions, vacuity and assertion unknowns
- mutation score and surviving-mutant review
- bug yield per CPU-hour
- median/p90 time-to-first-failure and time-to-root-cause
- deterministic replay rate and adapter conformance
- unsupported features and LLM suggestion acceptance/defect rates

Research claims must be measured on the same commits/workloads with machine, versions, seeds, confidence intervals and raw manifests. Success hypothesis: reduce median PR verification runtime while maintaining or improving seeded-mutant detection, with zero false evidence reuse.

## 9. Failure triage and differential checking

Normalize failures: compile/elaboration, assertion, scoreboard, protocol, timeout, deadlock/liveness, X-propagation, reset, tool crash, infrastructure and unknown.

Pipeline:
- deterministic log parsing and failure fingerprint
- seed/input replay
- waveform window extraction and pass/fail trace comparison
- transaction reconstruction and protocol lane correlation
- property counterexample + scoreboard transaction + RTL source correlation
- LLM-ranked hypotheses and proposed experiments
- engineer-confirmed root cause and fix

Differential checks require matched inputs, reset assumptions, timing abstraction and observable semantics. A mismatch is an investigation signal, not automatically a DUT bug.

## 10. CI workflows

PR workflow:
1. Python formatting, lint, typing, dependency/security checks.
2. IR/schema and migration contract tests.
3. Slang parse/elaboration fixtures with archived diagnostics and DesignIR.
4. Verilator lint, compile and deterministic smoke simulation.
5. Cocotb tests on supported simulator targets; archive JUnit and coverage.
6. Yosys/formal fixtures including expected proof and expected counterexample.
7. UVM on optional licensed/self-hosted runners; absent license/runtime reports NOT_CONFIGURED, never fake pass.
8. RustDV build/conformance only when pinned toolchain and revision are available.
9. Lean planner tests for impact traversal, reuse and invalidation using synthetic graphs.
10. Deterministic replay and normalized artifact comparison.
11. Signoff-policy tests rejecting false PASS, missing/stale evidence, expired waiver and unknown mandatory checks.
12. Upload logs, reports, IR, coverage, traces and evidence manifest as CI artifacts.

Nightly workflow: broad randomized regression, mutation tests, longer formal bounds, differential checks and performance benchmarks.

Release workflow: clean-checkout reproducibility, complete required gates, signed provenance and human signoff.

CI states must distinguish PASS, FAIL, SKIPPED, NOT_CONFIGURED, UNSUPPORTED and INCONCLUSIVE. A skipped licensed UVM job is never counted as UVM validation.

## 11. Security and operations

- Execute untrusted RTL, testbenches and generated code in isolated containers/VMs; network disabled by default.
- Cap CPU, memory, disk, processes and wall-clock.
- Allowlist executables and environment; reject LLM-generated shell commands.
- Keep secrets out of prompts, logs and artifacts.
- Pin toolchains and model digests; scan dependencies and artifacts.
- Sign evidence manifests and preserve audit history.
- Require human approval for waivers, signoff and policy changes.

## 12. Proposed repository layout

    wengold/verification/
      models.py
      schemas/
      services/{intake,planner,execution,coverage,evidence,signoff,triage}.py
      adapters/{base,slang,verilator,yosys,formal,uvm,cocotb,rustdv}.py
      normalize/{results,coverage,logs}.py
      policy/{capabilities,signoff,reuse}.py
      llm/{advisor.py,prompts/}
      cli.py
    tests/verification/
      contract/ fixtures/ planner/ validity/ coverage/ signoff/ security/
    docs/
      LEAN_VERIFICATION_ARCHITECTURE.md
      LEAN_VERIFICATION_ROADMAP.md

This is a target layout, not a claim that every module already exists. Reconcile current repository modules before implementation to avoid duplicating adapters and services.

## 13. Phased engineering roadmap

Phase 0 — Baseline: inventory graph/kernel/ledger/adapters/MCP/CI; map existing Cocotb adapter and orchestrator; record baseline tests and capability matrix. Exit: reviewed gap analysis and unchanged existing tests pass.

Phase 1 — Contracts: add typed IR/result/evidence schemas, version migrations, capability discovery, common errors, immutable run manifests and artifact digests. Exit: adapter contract suite passes or explicitly reports unsupported/not configured.

Phase 2 — Slang + Verilator: elaboration adapter, source maps, lint/compile/simulation adapter, requirement mapping and design dashboard. Exit: clean checkout parses and simulates canonical RTL fixtures with archived evidence.

Phase 3 — Formal: SVA/property registry, supported Yosys/SymbiYosys flows, expected proof/counterexample fixtures, assumptions, bounds and vacuity. Exit: no bounded result mislabeled as unbounded proof.

Phase 4 — UVM/Cocotb/RustDV: harden Cocotb, add UVM report adapter and optional licensed runner, integrate RustDV only against pinned discovered interface. Exit: reproducible conformance for every enabled engine.

Phase 5 — Lean planner: change-impact traversal, mandatory constraints, evidence reuse proofs, full-regression sentinels and adversarial false-reuse tests. Exit: no impacted mandatory evidence skipped in adversarial tests.

Phase 6 — Debug/LLM: failure fingerprints, waveform/transaction correlation, local LLM advisor, prompt-injection and unsafe-command tests. Exit: model cannot execute commands, waive checks or alter signoff.

Phase 7 — Research evaluation: CPU/AXI/arbiter/cache workloads; full-vs-lean comparison; runtime, bug yield, false reuse and confidence intervals; publish reproducible report. Exit: reviewed research report and release gate.

## 14. Signoff states and acceptance

Signoff states:
- NOT_READY: mandatory evidence missing or failures open.
- READY_FOR_REVIEW: gates met, human review outstanding.
- APPROVED: authorized reviewers approve exact evidence digest.
- REJECTED: mandatory criterion failed.
- STALE: evidence invalidated by change.

Waivers require scope, rationale, owner, expiry, affected requirement IDs and reviewer approval. No AI agent can set APPROVED.

A feature is complete only when schema/unit tests pass, real-tool integration tests pass, expected failures are correctly classified, invalidation is tested after RTL/constraint/tool/config changes, replay is demonstrated where claimed, CI artifacts preserve provenance and documentation lists limitations. Report each engine as IMPLEMENTED_AND_TESTED, IMPLEMENTED_UNVERIFIED, NOT_CONFIGURED, UNSUPPORTED or FAILED. Do not infer integration from a UI panel or adapter stub.
