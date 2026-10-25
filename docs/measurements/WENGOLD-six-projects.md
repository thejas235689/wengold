# Six RISC-V cores through WENGOLD

Every number below was produced by running the tool on the project. No figure is
from memory.

## Results

| project | files | blocks | edges | unresolved | complete | simulated |
| --- | --- | --- | --- | --- | --- | --- |
| picorv32 | 41 | 31 | 1,024 | 16 | false | 3/4 |
| fwrisc-s | 483 | 54 | 210 | 10 | false | 3/3 |
| cv32e40p | 181 | 154 | 872 | 8 | false | 3/6 |
| minerva | 1 | 51 | 50 | 0 | **true** | 3/3 |
| cva6 | 478 | 458 | 3,260 | 32 | false | 3/14 |
| ibex | 661 | 345 | 2,079 | 17 | false | 1/14 |

`blocks` are design units — a SystemVerilog module or a VHDL entity. `simulated`
is how many blocks compiled and ran in Icarus Verilog with a generated testbench,
out of how many were attempted.

## Waveforms — real, from a real simulator

No simulator was installed, so I downloaded the OSS CAD Suite and used **Icarus
Verilog 14.0**. Each project was then simulated: a testbench is generated from the
module's own port list (clock toggling, reset pulsed, a counter on the remaining
inputs), the module is compiled with its project's include directories, and the
VCD is rendered by `wengold ide --vcd`.

| project | blocks that produced a waveform | what the waveform shows |
| --- | --- | --- |
| picorv32 | `delay4`, `wb_ram`, `picorv32` | the **whole core** simulates standalone |
| fwrisc-s | `fwrisc_alu`, `fwrisc_mem`, `fwrisc_fetch` | 3 of 3 — the cleanest of the six |
| cv32e40p | `sram`, `sync`, `unread` | memory and pipeline primitives |
| minerva | `minerva.a`, `minerva.d`, `minerva.f` | a real `ready`/`valid` handshake |
| cva6 | `sync`, `dp_ram`, `unread` | 3 of 14 attempted |
| ibex | `bus` | 1 of 14 attempted |

The stimulus is a counter and random data. It exercises the logic and produces a
waveform worth looking at; **it is not a verification testbench and it proves
nothing about these designs.**

## What blocked the rest

Three distinct causes, and none of them is WENGOLD:

* **Icarus cannot parse much modern SystemVerilog.** cva6's `aes.sv` opens with
  `module aes import ariane_pkg::*; import aes_pkg::*; #(…)` — a package import in
  the module header. Icarus 14 rejects it. Verilator handles more but needs a C++
  compiler to simulate, and there is no compiler in this sandbox.
* **Vendor primitives are not in the repositories.** picorv32's `SB_IO` is a
  Lattice cell; cva6's `IOBUF` and `FIFO_DUALCLOCK_MACRO` are Xilinx macros.
* **Some "blocks" are not modules.** A few candidates were extracted names that
  do not correspond to a definition — reported honestly as `not found` rather than
  counted as successes.

## minerva: it ships no RTL at all

minerva is written in **Amaranth (Python)** and contains **zero HDL files**. The
Verilog is generated. I installed Amaranth and its `amaranth-soc` dependency,
generated the design, and indexed the result:

```
generated 434,301 bytes of Verilog, 51 modules
wengold: 51 blocks, 50 edges, 0 unresolved, complete: true
```

It is the only project of the six that is **complete** — every instantiation
resolves — and the only one whose RTL did not exist until it was generated. The
block names carry Amaranth's escaped identifiers (`minerva.a`,
`minerva.exception.csr_bank.mcause`), which are hierarchical design names, not
module names.

## Two bugs this run found

**A single stray VHDL file silently dropped 477 SystemVerilog files.** cva6
contains exactly one `.vhd` file (`dpti_ctrl.vhd`) and 477 `.sv` files. When the
SystemVerilog front-end was unavailable, that one VHDL unit made the internal unit
dict non-empty, and the builder returned early — **indexing cva6 to 4 blocks
instead of 458**. The number looked plausible enough to pass unnoticed; it was
found only because the IDE reported 4 blocks where `index` had reported 458. Fixed,
with a regression test.

**The fallback to the weak front-end was silent.** Without pyslang the builder
uses a bounded regex elaborator that finds a fraction of the modules, and nothing
said so. It now prints:

```
!! slang (pyslang) is not installed — fell back to the bounded regex elaborator,
   which finds far fewer modules. The block count below is an under-estimate,
   not the design.
```

## Limits of this run

* **Not a verification result.** Indexing and simulating a few blocks says nothing
  about whether these cores are correct. No testbench, no coverage, no property
  was run against them.
* **The formal engine was not used.** These are full cores; the formal front-end
  covers register-level RTL, not this.
* **The 78 unresolved blocks across the six** (mostly vendor cells and macro
  instantiations) mean results downstream of them are `unknown` by design.
* **`complete: false` for five of six** is the honest reading: their file sets, as
  collected here, do not contain everything they instantiate.
