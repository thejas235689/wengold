# WENGOLD Product QA and Release Readiness

Last reviewed: 2026-11-12. Source: GitHub CI, Linux native offscreen Qt
workflows, installed app testing, and cross-platform matrix results.

## What the automated Linux release gate tests

| User journey | Evidence | Scope / caveat |
| --- | --- | --- |
| Install desktop in a clean HOME | Isolated Qt venv, launcher and uninstall tested | Ubuntu runner; Rocky workstation still needs a local test |
| Start Linux UI | Real PyQt6 offscreen screenshot | Does not prove every display driver or window manager |
| Open project | Qt folder selection, source discovery, project switch, external file updates | Very large filelists still limited |
| Navigate project | Filter Design RTL, UVM, specs, automation; double-click editor | PDF must first be converted to readable text |
| Edit existing files | Hash-guarded save and rejection of escapes; text, YAML, JSON and SV supported | No unrestricted file creation from editor |
| Run HDL syntax | Supported HDL files only; scripts rejected with explanation | Requires tool for advanced constructs |
| Spec + RTL DV intake | Real file read, digest and module discovery | Not proof of requirement satisfaction |
| AI verification planning | Explicit model dependency, draft status and safe export | Model is mocked in CI; real model requires workstation |
| AI UVM/SVA/testcases | Real Qt button actions tested using stub inference | No generated test is automatically accepted as verified |
| SystemVerilog simulation | Real Icarus example and nonzero-on-failure regression | Not UVM simulation |
| Waveforms and debug | Real VCD parse, X signals, rule findings and UI navigation | Limited VCD sample window, not universal root-cause proof |
| Coverage and closure | Measured counter example (3/4 bins), source hash and missing-bin plan | No UCIS import or assertion/code coverage signoff |
| Yosys generic synthesis | Real counter synthesis, schematic canvas and logs | No foundry mapping without supplied Liberty |
| Mapping / timing | Unit-tested mapping and OpenSTA invocation contract | Real Liberty/SDC/corners and analysis not qualified |
| Formal | Bounded engine and explicit unsupported handling | Package-aware full SV front-end remains unresolved |
| Persistent workers | SQLite queue, local jobs and signoff evidence tests | No independent multi-host server/workers |
| CIW | Commands, history and docked console tested | Not an arbitrary system shell |

## Acceptance conditions for a fully working installation

1. Verify the complete cross-platform matrix has passed, not merely Linux
   native smoke. The matrix may include genuine Windows/EDA dependency failures.
2. On your own Linux machine, run `sh linux/install-desktop.sh` from a fresh clone;
   open the application from a desktop launcher, not only from a terminal.
3. Open an actual project with SystemVerilog, UVM and scripts. Confirm file
   tree, double-click editor, save, refresh and source diagnostics.
4. Run a real simulator regression, inspect failures, and compare measured
   coverage/scoreboard output. Generated AI drafts require code review.
5. Test Ollama/OpenAI-compatible loopback model discovery and inference on
   installed local hardware; confirm expected code compiles independently.
6. Verify licensed/approved UVM simulator, Satya PSS and RustDV under explicit
   tool manifests, using real simulator execution and evidence.
7. Bring real Liberty, SDC, power library, PDK, rule decks and STA/physical
   engines for signoff integration; do not accept default/demo figures.

## Run checks

```bash
git pull origin main
sh linux/install-desktop.sh
~/.local/bin/wengold --version
~/.local/bin/wengold doctor --llm
~/.local/bin/wengold desktop --native ./examples/dv_workflow
```

In the app, open **Help > UI & Tool Diagnostics**; check `runtime_gates`
rather than treating a visible button as a validated backend. In
**DV Workflow**, test the model connection before attempting generation.

Local regression (with project dev dependencies installed):

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_product_qa.py
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_native_studio.py
python -m pytest -q tests/test_dv_pipeline.py tests/test_synthesis_tools.py
```

## Meaning of test results

- **PASS** means a specific executed check passed on the tested machine.
- **DRAFT** means AI-generated content not yet compiled or reviewed.
- **EVIDENCE IMPORTED** means source logs or bins were read, not independently
  proven correct.
- **STALE** means sources changed and relevant checks must rerun.
- **UNAVAILABLE** means tools, input files or credentials are missing.
- **SIGNOFF** is separate and requires audited, technology-specific evidence.

**Release claim:** Linux desktop smoke passing is not a universal guarantee
that every third-party EDA tool, GPU driver, formal proof path, UVM simulator,
local model, and commercial PDK works on a user's computer.
