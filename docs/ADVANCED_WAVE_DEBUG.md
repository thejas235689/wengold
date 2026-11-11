# Advanced waveform debugging: RTL vs verification environment

WENGOLD Silicon Studio provides **Waveforms** (native VCD timeline) and
**Wave Debug** (DUT and testbench evidence inspection). Both operate on actual
simulation VCD files and keep the normal Command Interpreter Window available.

## Workflow

1. Run a simulation using your RTL and independent verification environment.
   Enable VCD dumping for the DUT, testbench signals, drivers, monitors and
   scoreboard expectations. Store the VCD under `waves/`, `waveforms/`,
   `sim/`, `results/` or another supported project evidence folder.
2. Open WENGOLD Linux desktop and select **Waveforms → Refresh files → Load VCD**.
3. Open **Wave Debug**. Configure comma-separated **RTL/DUT hierarchy roots**
   (example: `tb.dut`) and **TB/UVM roots** (example: `tb`). Deeper matched
   DUT scopes override their enclosing testbench scope. Inspect the separate
   DUT and TB signal tables; unclassified signals are counted, not invented.
4. Choose the captured-sample handshake window and select **Analyze VCD evidence**.
5. Select a finding to view its actual observed signal names, sample time,
   rule and evidence. The tab cross-probes sources and jumps back to the VCD
   timeline at that sample. Exact source ownership is NOT inferred from names.
6. Configure Ollama or an OpenAI-compatible local server and press
   **Explain evidence using Local AI** to request a bounded AI triage.
   The model response is labeled HYPOTHESES, not proof.

## Current deterministic diagnostic rules

- `unknown_transition`: a signal switches from a captured known sample to
  X/Z/unobserved; inspect reset, drive, power, multiple drivers and dump scope.
- `all_unknown`: a signal never resolves in the available capture.
- `clock_static`: observed clock remains fixed over the capture; may be gating
  or sampling limitations rather than a clock-tree defect.
- `scoreboard_mismatch`: expected/actual pair in the same hierarchy disagree.
  Supported signal suffixes: `_expected` / `_exp` / `_reference` / `_ref`
  and `_actual` / `_act` / `_got`.
- `handshake_timeout_candidate`: request/ack or valid/ready pair lacks a high
  response during a configurable number of captured timestamps. This is NOT
  a cycle-accurate protocol property because VCD timestamps need not match
  sampling clock edges.

The report contains signal domain, severity, time, evidence names, observation
and configuration; it never asserts a definitive root cause. For a final
engineering diagnosis, run directed simulations or SVA/formal and correlate
driver logs, monitor sampling, scoreboard predictions, reset and power states.

## Local AI guarantees

- Model inference is explicit; local endpoint is constrained to HTTP loopback.
- The model only receives a bounded structured evidence report; no RTL files
  are silently transmitted to it.
- A model outage raises a visible error rather than a fabricated explanation.
- Its response includes a SHA-256 of the evidence report used for the prompt.
- No AI response is promoted to a verified finding or tapeout signoff.

## Current implementation limits

VCD source files are capped at 8 MiB by the existing workspace. The viewer
currently exposes the first 256 signals and 1200 real timestamps. Four-state
X and Z are currently collapsed into an unknown sample. Large SoC traces
need indexed streaming backends, virtualized wave trees and windowed loading.
Waveform classifications rely on explicit hierarchy prefixes or heuristics;
UVM transaction semantics cannot be inferred from signal names alone.

## Tests

```bash
python3 -m pytest -q tests/test_wave_debug.py tests/test_wave.py
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_native_studio.py
```

These tests include real VCD samples with RTL unknowns, TB scoreboard
mismatches, missing handshakes and a clean capture. AI tests use a stub
to verify prompting and evidence boundaries: a real local model remains
workstation-dependent.
