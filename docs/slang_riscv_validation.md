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
`tb_core_top.u_core.u_fetch.if_req_valid`. It deliberately does not fuzzy-match
leaf names. A VCD with a different testbench instance path must supply the
correct `--vcd-root` and `--dut-instance`.

## Limitations

- The graph is logical elaborated RTL connectivity, not placement, routing,
  parasitics, timing, or physical layout.
- The standalone Slang AST path handles language elaboration without asking
  Yosys to synthesize procedural loops. In the current RV64 RTL, the
  `rv64_num_wide.sv` posit decode function exceeds Yosys-Slang's default
  synthesis unroll limit (4,000). This is why the hierarchy path uses Slang AST
  directly; it does not claim the same RTL is ready for Yosys synthesis.
- The optional `yosys-slang` path supports a synthesizable SystemVerilog
  subset; simulator-only testbench constructs and unsupported language features
  may not map to a synthesis netlist.
- A port is reported as cross-probed only when its exact VCD hierarchical name
  exists. Optimized-away or un-dumped internal signals remain unmatched.
- VCD and FST are different formats; this validator currently accepts VCD only.
