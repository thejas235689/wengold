# WENGOLD Production Readiness — Four High-Risk Areas

Scope: actual local-LLM inference, full UVM simulation, package-aware formal
and PDK-backed power/physical verification. The WENGOLD desktop can open
and route the controls; that alone does not prove external tools or signoff.

## Quick inspection (safe: does not execute third-party commands)

```bash
cd ~/wengold
git pull origin main
python3 -m wengold.production_readiness ./examples/dv_workflow
```

The JSON report has seven independent gates: `local_ai`, `uvm`,
`package_formal`, `power`, `physical_drc`, `physical_lvs`, and
`physical_pex`. The command deliberately exits nonzero until all seven
have independent execution evidence. This is an unmet-acceptance indicator,
not a software crash. Outputs always carry `signoff: NOT ESTABLISHED`.

## 1. Real local model inference

Install Ollama and an actual instruction-following coding model locally.
Use an exact installed model name. Verify the full inference path:

```bash
ollama list
export WENGOLD_LLM_MODEL=qwen2.5-coder:7b
export WENGOLD_LLM_BACKEND=ollama
export WENGOLD_LLM_URL=http://127.0.0.1:11434
python3 -m wengold.production_readiness . --model "$WENGOLD_LLM_MODEL" --probe-ai
```

**Model availability is not RTL correctness.** Test generated SystemVerilog
with a real simulator or independent reference model. For extra checking:

```bash
python3 tools/verify-local-ai-stack.py --project examples/dv_workflow \
  --testbench tb/counter4_tb.sv --top counter4_tb
```

That example requires a model generating the interface expected by the
testbench, Icarus and VVP. Different LLM outputs may fail; record failures.

## 2. Full UVM simulation

Create a project-local reviewed manifest, e.g. `flows/uvm.json`, with
`kind: uvm`, an `argv` array invoking the exact installed UVM-compatible
simulator and compile/run command, nonempty `inputs` (RTL, TB, run script),
and nonempty `artifacts` naming independent logs/coverage evidence.

Sample schema (replace all placeholders with actual project files/tools):

```json
{
  "kind": "uvm",
  "argv": ["python3", "scripts/run_uvm.py"],
  "inputs": ["rtl/top.sv", "tb/top_test.sv", "scripts/run_uvm.py"],
  "artifacts": ["results/uvm.log", "results/functional-coverage.json"],
  "timeout_seconds": 600
}
```

An actual `run_uvm.py` should compile UVM, launch the simulator, check fatal
UVM errors and scoreboard failures, and fail nonzero when required assertions
or tests fail. The manifest itself is **not** the simulator and is never
treated as proof of UVM correctness. For real UVM, use Questa/Xcelium/VCS
or an independently qualified compatible simulator.

## 3. Package-aware formal

WENGOLD's bounded internal RTL parser does **not** resolve
SystemVerilog `import pkg::*`, so use an externally elaborated formal
flow and its actual tool executable. Supply a `kind: formal` manifest
that includes package sources in correct compilation order, SVA properties,
top/bind dependencies, tool scripts, and proof logs as evidence artifacts.

The command exit status must distinguish PROVEN/COUNTEREXAMPLE/UNKNOWN,
and reports must be reviewed for vacuity, assumptions, reset and depth.
An explicit UNKNOWN result is not a proof and cannot be called closed.

## 4. Power and physical signoff

Configure separate `kind` manifests for `power`, `physical_drc`,
`physical_lvs`, and `physical_pex` with actual technology-specific tools.
Requirements include licensed/approved tool installation, real PDK/Liberty,
corners, foundry rule decks, cell/macro libraries, VCD/SAIF activity, SDC,
power intent where relevant, placed/routed layout and parasitics.

A successful program exit and fresh report file do not establish signoff;
review violations, excluded checks, waived errors and tool configuration.

## Run only reviewed manifests

```bash
python3 -m wengold.production_readiness /absolute/project \
  --model "$WENGOLD_LLM_MODEL" --probe-ai \
  --uvm-manifest flows/uvm.json \
  --formal-manifest flows/formal.json \
  --power-manifest flows/power.json \
  --drc-manifest flows/drc.json \
  --lvs-manifest flows/lvs.json \
  --pex-manifest flows/pex.json
```

The above inspects manifests but does not launch EDA tools. Add
`--execute` ONLY after auditing all the declared commands and inputs.
Each run captures exit status, fresh evidence artifact hashes, and failures
but the overall report never labels chip signoff achieved.

## Validation transparency

CI tests verify that the seven gates start unverified, wrong tool kinds are
rejected, stale/missing artifacts do not pass, AI probing is opt-in, and
tool execution does not equate to signoff. Those tests use short local
subprocesses and stub model responses: they do NOT claim a real customer
UVM simulator, local Ollama instance or proprietary PDK was run.
