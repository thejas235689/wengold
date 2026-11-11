# WENGOLD — Specification to Coverage Design Verification Workflow

**Native desktop:** `DV Workflow` tab. Six linked engineering stages:

1. Specification + RTL intake
2. AI-generated verification plan
3. UVM components and SystemVerilog Assertions (SVA) drafts
4. Testcase generation and real simulation regression
5. AI root-cause triage from actual failures
6. Measured functional coverage and coverage-closure plan

Each stage has its own button and an evidence log. **No local LLM output
is considered verified.** Imported tool evidence, source file hashes and
observed coverage are separate from suggestions.

## Setup / Linux

```bash
git pull origin main
sh linux/install-desktop.sh
sudo apt install iverilog  # Ubuntu / Debian; on Rocky use dnf/EPEL
export WENGOLD_LLM_BACKEND=ollama
export WENGOLD_LLM_MODEL=qwen2.5-coder:7b
~/.local/bin/wengold desktop --native ./examples/dv_workflow
```

The selected LLM must already be running locally. The backend permits only
localhost/loopback HTTP. Check with `wengold doctor --llm`. The UVM/SVA
generation buttons only require a local model; independent UVM simulation
requires a compatible simulator and UVM library.

## 1. Intake

Choose `spec/requirements.md` and `rtl/counter4.sv`.
Click **Load and fingerprint sources**. WENGOLD reads bounded UTF-8 source
files, locates module names and records SHA-256 digests. PDFs are listed in
the explorer but must be exported to UTF-8 Markdown/text before AI ingestion.
The source is NOT yet verified.

## 2. Verification planning

Click **Generate AI verification plan**. The model receives the specification
and RTL reference text, and is instructed to produce requirements traceability,
UVM structure, testcases, SVA, coverage, negative tests, and explicit gaps.
Human review and reconciliation to the actual specification is required.

## 3. UVM and SVA

Select `uvm`, `sva`, or `testcases` and click **Generate UVM / SVA drafts**.
The result remains an AI DRAFT. You can explicitly export the reviewed
draft under `wengold-drafts/`; WENGOLD will NOT overwrite existing source.
UVM, SVA and generated testcases are NOT compiled or executed automatically
and require a simulator/tool flow suitable for the generated language subset.

## 4. Real testcases and simulation

For the bundled example, select `flows/simulation.json` and click
**Run reviewed regression**. Confirm execution. The manifest calls
`scripts/run_regression.py` which actually compiles `rtl/counter4.sv` and
`tb/counter4_tb.sv` with Icarus, runs VVP, and checks explicit pass/fail
markers. It writes `results/regression.log` and `results/coverage.json`.
Both are required fresh evidence files; failures and missing artifacts are
rejected. A Python/Verilog directed test is not UVM; for full UVM instead
supply a reviewed `kind: uvm` manifest using your actual simulator.

## 5. Root cause

Select `results/regression.log` and click **Explain actual regression log**.
The local model receives bounded recorded log text and proposes RTL versus
driver/monitor/scoreboard hypotheses and confirming tests. Its answer remains
unverified until you reproduce and resolve the issue. The Wave Debug tab can
add actual VCD findings to the investigation separately.

## 6. Coverage analysis and closure

Select `results/coverage.json`, set a target (e.g. 95%), and click
**Analyze measured coverage bins**. Required interchange format:

```json
{ "bins": [
  {"name": "reset", "hits": 2},
  {"name": "increment", "hits": 4},
  {"name": "wraparound", "hits": 0},
  {"name": "unreachable", "hits": 0, "excluded": true, "reason": "approved waiver"}
] }
```

Coverage percentage is based on observed nonexcluded bins with hits > 0.
Only trusted actual simulator coverage should be imported. This generic
JSON interchange is **not** an automatic UCIS parser. Exclusions and cross
coverage still require independent review. The sample observes 3/4 bins =
**75%**, leaving wraparound uncovered. Click **Draft coverage closure plan
with Local AI** to request an actionable set of directed tests. No AI call
changes the measured coverage; it must be re-run and re-imported.

## Engineering integrity

- Imported source hashes and tool result metadata are tracked separately.
- Work is not considered signoff solely because a tool returned exit zero.
- Manual project re-indexing marks existing in-memory DV evidence stale.
- Native waveform root-cause candidates and AI findings remain hypotheses.
- Enterprise UVM verification requires simulator, licenses, coverage DB,
  strong scoreboards, assertion/functional/code coverage and reviewed waivers.
- Spec edits, RTL changes, and changed tools can invalidate earlier evidence.

## Regression tests

```bash
python3 -m pytest -q tests/test_dv_pipeline.py
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_native_studio.py
```

The Linux desktop CI runs a **real Icarus regression** on the bundled example
(when Icarus and VVP are installed), asserts its measured 75% coverage,
and verifies that the uncovered bin cannot be marked closed by the AI.
Local LLM quality remains a separate workstation-dependent test.
