# WENGOLD Local AI Engineering Workbench

The native Linux Silicon Studio now includes a **Local AI** tab. It is meant for local Ollama or OpenAI-compatible servers (llama.cpp / LM Studio / vLLM serving on localhost). Remote, authenticated, HTTPS and non-loopback URLs are deliberately rejected to avoid leaking private design source by accident.

## Start

```bash
python3 -m pip install -e '.[native,slang,formal]'
# Install Ollama separately from its official distribution
ollama pull qwen2.5-coder:7b
export WENGOLD_LLM_MODEL=qwen2.5-coder:7b
wengold doctor --llm
wengold desktop --native ./rtl
```

In the **Local AI** tab select `ollama`, `http://127.0.0.1:11434`, press **Connect / Models**, select the model and press **Test Inference** to require a real generation round-trip, then select an engineering discipline and enter a task. **Generate Draft** uses real model inference on a worker thread and displays its response as **DRAFT — NOT VERIFIED**. Errors and missing servers are reported explicitly. No silent cloud fallback is offered. For the **RTL Design** profile, generation automatically runs the available Icarus syntax check, then an optional project-local testbench if configured. The result and its tool output are displayed beside the draft; failures do not disappear.

## Engineering prompt profiles

The shipped `wengold/ai_prompts.py` contains these 15 independent discipline-specific profiles: RTL Design, SystemVerilog DV, UVM, Portable Stimulus / Satya, RustDV, Formal Verification, DFT, Power-Aware Design, Power-Aware Verification, Physical Design, Physical Verification, Analog Design, Analog Verification, Layout Design, Layout Verification.

These profiles request design constraints, assumptions, realistic test methodology and independently executable validation steps. They do **not** claim that a PDK, foundry runset or EDA license is installed.

## Verification status, not marketing

- **Draft**: text from an LLM only.
- **Syntax checked**: `iverilog -g2012 -tnull` exited zero for standalone SystemVerilog RTL.
- **Simulation completed**: a supplied, existing, project-local testbench compiled and `vvp` exited zero. This does **not** establish nonvacuous checking, coverage, formal proof, or tapeout signoff.
- **Failed**: compiler/tool error, simulation nonzero exit or recognizable FAIL/ERROR/FATAL transcript.

For an actual RTL simulation, enter a relative testbench path such as `tb/counter_tb.sv` and its top module `tb`. Neither path may escape the chosen RTL project. The generated RTL is written to a temporary directory, never silently into the production source tree. RTL with dependencies or unsupported Icarus features needs a more complete integration testbench and appropriate commercial/open-source simulator.

## Optional open-source integrations

**Satya** — <https://github.com/thejas235689/satya>. The executable is optional. The Workbench can run `satya check <model>` on a project-local `.pss`, `.psf`, or `.json` model, and can generate a UVM sequence with `satya gen <model> --backend uvm -o <temporary-file>`. The latter is **generated / unverified**, not proof of PSS semantics. Satya itself documents partial PSS coverage; refer to its behavioral feature audit, not only to its parsed feature matrix.

**RustDV** — <https://github.com/rustdv/rustdv>. RustDV is a Rust verification framework with VPI simulator adapters, not a standalone PSS tool or an IEEE UVM implementation. The Workbench can run `cargo test --offline --locked` against an existing RustDV Cargo project directory under the current project root. **Cargo unit-test success is not DUT RTL simulation**. Use the RustDV documented simulator scripts separately for an actual HDL regression.

Use Icarus, Verilator, simulator-specific UVM support, a formal engine, a SPICE engine and PDK-specific tools independently as appropriate to the discipline. Do not treat the default Icarus syntax check as a UVM/UPF/AMS/DRC/LVS check.

## AI validation tests

```bash
python3 -m pytest -q tests/test_ai_workbench.py
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_native_studio.py
```

These tests use a fake local model for prompt/response policy, plus a **real Icarus simulator** when installed. Full LLM output quality still requires an installed, running model on the engineer's Linux machine. Read `docs/LOCAL-MODEL.md` and run `wengold doctor --llm`.
