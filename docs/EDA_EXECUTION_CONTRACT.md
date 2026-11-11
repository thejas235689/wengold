# WENGOLD: local AI and external EDA tool integration

## What is implemented

The native Linux Local AI panel accepts an opt-in, project-local JSON recipe
for UVM, RustDV simulator runs, PSS, DFT, UPF, physical DRC/LVS/PEX, analog
and layout. It invokes a reviewed executable through an argv array (never
shell interpolation) and records source and artifact SHA-256 digests, logs,
return code and timestamps. Missing or unchanged old artifacts invalidate
the evidence. This is an execution record, NEVER a signoff certificate.

## Manifest contract

Create flows/uvm.json under your RTL project, with contents:

```json
{
  "kind": "uvm",
  "argv": ["/absolute/path/to/approved-simulator", "--site-specific-options"],
  "inputs": ["rtl/dut.sv", "tb/uvm_top.sv"],
  "artifacts": ["results/uvm-regression.log"],
  "timeout_seconds": 300
}
```

Replace placeholder commands with the EXACT installed simulator and approved
tool arguments. Do not run untrusted manifests. The engineer must select the
manifest and confirm execution in the native desktop. A manifest is trusted
local executable configuration, not an AI suggestion.

## Separate tool flows

- UVM: requires simulator with suitable UVM support, testbench, seeds, and log/coverage artifacts.
- RustDV: optional Run RustDV VPI button invokes documented sim/run_rustdv.sh from an existing checkout. Both exit zero and REGRESSION: PASS are required for script_reported_pass; not independent signoff.
- Satya: 'check' and UVM generation are supported. PSS behavioral conformance is explicitly incomplete according to Satya's own feature audit.
- DFT and UPF: require actual design, scan/power intent, EDA licenses and recorded test reports.
- DRC/LVS/PEX and layout: require foundry PDK, technology/runset versions, design database and exception/waiver review.
- Analog/AMS: requires SPICE/AMS simulator, extracted models, PVT corners and suitable design/testbenches.

None of these tools, foundry libraries, licenses or technology files are shipped by WENGOLD.
Zero exit code by itself never proves functional correctness or silicon signoff.

## Prove your actual local model

Run on the workstation with the LLM installed and running:

```bash
export WENGOLD_LLM_BACKEND=ollama
export WENGOLD_LLM_MODEL=qwen2.5-coder:7b
python3 tools/verify-local-ai-stack.py --project ./rtl \
  --testbench tb/counter4_tb.sv --top tb \
  --output ./local-ai-evidence.json
```

The testbench must be an existing, independently authored and self-checking
testbench. The command makes a REAL model request, compiles the generated
standalone RTL with Icarus, and executes VVP with the provided testbench.
The JSON report includes stage and actual tool results. Failure does not
silently substitute pre-written RTL. A successful simulation does not prove
that testbench checks are adequate.

## Validation scope

Linux smoke runs policy tests using real subprocesses and optional Icarus.
Cross-platform CI status is separate, and CI concurrency cancels older
superseded runs to prioritize the current commit. A production EDA regression
requires a license-enabled, PDK-provisioned, access-controlled build runner.
An actual user workstation's Ollama process cannot be reached by GitHub CI
unless a deliberate self-hosted runner is configured.
