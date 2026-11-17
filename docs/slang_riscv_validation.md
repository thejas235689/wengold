# Slang-based RISC-V hierarchy and waveform validation

Wengold supports two Slang paths for the `thejas235689/rv64_core` project:

- **Slang AST (recommended for hierarchy browsing):** invokes the standalone
  Slang compiler with `--ast-json` and source metadata. It builds the instance
  tree and port-expression connectivity directly from the elaborated AST.
- **Slang + Yosys netlist:** invokes Yosys `read_slang` and exports Yosys JSON.
  This path is useful when a synthesizable netlist is required, but it is
  subject to the synthesizable subset and loop-unrolling limits of that flow.

## Prerequisites

For the recommended AST path, use OSS CAD Suite or install the standalone
Slang CLI. For the optional netlist path, use OSS CAD Suite (or another Yosys
build containing `yosys-slang`):

```sh
yosys -Q -p 'plugin -i slang; help read_slang'
```

The command must report `read_slang` help. A standalone `slang` lint executable
or the Python `pyslang` package alone is not a substitute for this netlist
frontend: the hierarchy graph needs elaborated cell and port connectivity.

## Validate the real RISC-V RTL

```sh
python tools/validate_riscv_core.py /path/to/rv64_core \
  --frontend slang_ast --top riscv_core_top
```

The validator reads the authoritative ordered `RTL_SRCS` list from
`sim/run.py` without importing the Cocotb runner. Slang parses, type-checks,
and elaborates the actual `riscv_core_top`, reports instance and actual
port-expression connections, and writes `.wengold/slang_ast.json` under the
RISC-V project root. Wengold's normalized hierarchy report is written to the
path supplied with `--output` (or stdout).

## Validate an actual simulation capture

The RISC-V GitHub repository currently contains no committed `.vcd` or `.fst`
capture. Once a real VCD is available, run:

```sh
python tools/validate_riscv_core.py /path/to/rv64_core \
  --frontend slang_ast --top riscv_core_top \
  --vcd /path/to/riscv_core.vcd \
  --vcd-root tb_core_top --dut-instance u_core \
  --output /path/to/riscv_hierarchy_validation.json
```

Cross-probing uses exact hierarchical names, e.g.
`tb_core_top.u_core.u_fetch.if_req_valid`. The VCD parser preserves every
hierarchical declaration that shares a VCD identifier (common for aliased nets
in Icarus), instead of overwriting earlier scope names. If a simulator omits a
child-port alias, Wengold may use only the exact parent-net symbol recorded in
Slang's elaborated port expression and only when that exact parent path exists
in the VCD. It never fuzzy-matches leaf names. A VCD with a different testbench
instance path must supply the correct `--vcd-root` and `--dut-instance`.

## CI evidence

The deterministic capture harness compiles the real RV64 RTL and
`tb/tb_core_top.sv`, runs a short RV64 smoke program, and generates a fresh VCD.
The latest validated capture contains **2,619 hierarchical VCD signal names**
and maps **758 / 758 elaborated ports (100%)** by exact hierarchical path:
**758 direct matches, 0 parent-net fallbacks, 0 unmatched**. This is a
smoke-program capture, not a failing regression trace or a user-supplied
PASS/FAIL comparison.

## Limitations

- The graph is logical elaborated RTL connectivity, not placement, routing,
  parasitics, timing, or physical layout.
- The standalone Slang AST path is the authoritative full-SV hierarchy path.
  The optional Yosys-Slang check is configured with the default flattened netlist mode and a
  bounded `--unroll-limit 4096`; CI is still validating this heavier path.
  Passing that check would establish frontend/hierarchy compatibility only,
  not full technology-mapped synthesis, STA, or timing closure.
- The optional `yosys-slang` path supports a synthesizable SystemVerilog
  subset; simulator-only testbench constructs and unsupported language features
  may not map to a synthesis netlist.
- A port is reported as cross-probed only when its exact VCD hierarchical name
  exists, or its exact elaborated parent-net connection is present in the VCD.
  No leaf-name or approximate matching is performed.
- VCD and FST are different formats; this validator currently accepts VCD only.
