# Slang-based RISC-V hierarchy and waveform validation

Wengold can elaborate the `thejas235689/rv64_core` project using the
`yosys-slang` Yosys plugin. This uses Slang for SystemVerilog parsing and
elaboration, then exports the hierarchy-preserving Yosys JSON consumed by the
schematic and cross-probe UI.

## Prerequisites

Use OSS CAD Suite (or another Yosys build containing `yosys-slang`):

```sh
yosys -Q -p 'plugin -i slang; help read_slang'
```

The command must report `read_slang` help. A standalone `slang` lint executable
or the Python `pyslang` package alone is not a substitute for this netlist
frontend: the hierarchy graph needs elaborated cell and port connectivity.

## Validate the real RISC-V RTL

```sh
python tools/validate_riscv_core.py /path/to/rv64_core \
  --frontend slang --top riscv_core_top
```

The validator reads the authoritative ordered RTL source list from
`sim/run.py --list-rtl`, preserving package-before-module order. It elaborates
the actual `riscv_core_top`, reports instance and port-bit-connection counts,
and writes the hierarchy JSON to `.wengold/rtl_hierarchy.json` under the RISC-V
project root.

## Validate an actual simulation capture

The RISC-V GitHub repository currently contains no committed `.vcd` or `.fst`
capture. Once a real VCD is available, run:

```sh
python tools/validate_riscv_core.py /path/to/rv64_core \
  --frontend slang --top riscv_core_top \
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
- `yosys-slang` supports a synthesizable SystemVerilog subset; simulator-only
  testbench constructs and unsupported language features may not map to a
  synthesis netlist.
- A port is reported as cross-probed only when its exact VCD hierarchical name
  exists. Optimized-away or un-dumped internal signals remain unmatched.
- VCD and FST are different formats; this validator currently accepts VCD only.
