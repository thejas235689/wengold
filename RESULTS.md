# WENGOLD across 33 repositories

Every project checked in this series, at v0.27.1 unless marked otherwise.
All rows at v0.27.0/v0.27.1 were taken from a single re-fetched build, so they are
directly comparable.

**33 attempted. 30 indexed. 3 could not be.**

## Complete and clean (unresolved = 0)

| repo | files | nodes | edges | blocks | coverage |
| --- | --- | --- | --- | --- | --- |
| 2D-systolic-array | 2 | 6 | 7 | 2 | 100% |
| riscv-boom | 2 | 2 | 0 | 2 | 100% |
| neorv32 | 76 | 758 | 1,262 | 86 | 89% |
| Anvil-Pro | 25 | 27 | 107 | 19 | 76% |
| rustdv/rustdv | 8 | 7 | 5 | 7 | 62% |
| pyuvm | 23 | 15 | 38 | 7 | 30% |
| wave_rerunner | 27 | 17 | 34 | 10 | 22% |
| riscv-dv | 89 | 5 | 2 | 1 | 4% |
| minerva | - | - | - | 51 | - |
| lxp32-cpu | - | - | - | 34 | - |
| BorussCPU-Laibach | - | - | - | 8 | - |

## Not complete, with the reason

| repo | files | blocks | unresolved | coverage | why |
| --- | --- | --- | --- | --- | --- |
| riscduino | 232 | 304 | 169 | 62% | SkyWater PDK not vendored |
| cva6 | 477 | 458 | 32 | 68% | vendor IP |
| rsd | 220 | 258 | 26 | 88% | vendor primitives |
| Cores-VeeR-EL2 | 109 | 143 | 41 | 81% | one bad module poisons beh_lib.sv |
| ibex | - | 345 | 17 | - | vendor IP |
| picorv32 | 41 | 31 | 16 | 39% | picosoc not in file set |
| openCologne-PCIE | 78 | 77 | 12 | 81% | Xilinx MGT/PCIe hard blocks |
| litex_wr_nic | 22 | 39 | 11 | 100% | LiteX wrappers to vendor IP |
| frost | 248 | 256 | 8 | 98% | vendor IP |
| qeciphy | 180 | 98 | 3 | 51% | FPGA IP in example wrappers |
| OpenTitan | - | 879 | 79 | - | unresolved primitives in closures |
| cv32e40p | - | 154 | 8 | - | vendor IP |
| fwrisc-s | - | 54 | 10 | - | - |
| pcievhost | - | 34 | 16 | - | - |
| verilog-pcie | 216 | 123 | 1 | 53% | one vendor primitive; 8 duplicate board copies |
| rocket-chip | 11 | 14 | 1 | 100% | Chisel output |
| Arbiter-Verification | - | 4 | 1 | - | a UVM env, not a design |
| difftest | 12 | 11 | 5 | 75% | C++/SV glue |
| rustdv_fifo | - | 1 | 0 | - | 1 block, 1 edge |

## Could not be checked

| repo | reason |
| --- | --- |
| logisim-cpu-project | 0 HDL files — Logisim .circ schematics |
| XiangShan | not reachable at master/main |
| openpiton | not reachable at master/main |

## Findings

**Coverage separates repositories into three bands.** Real hand-written RTL lands
68-100% (frost 98%, neorv32 89%, rsd 88%, cva6 68%). Mixed design+DV 30-62%.
Verification libraries 4-22% (riscv-dv 4%, wave_rerunner 22%). Repo size predicts
nothing: riscduino has 232 files at 62%, riscv-dv has 89 at 4%.

**Coverage and completeness are independent.** `litex_wr_nic` is 100% file-coverage
and not complete — all 22 files contributed a unit, but 11 instantiations are
unresolvable vendor IP. Reporting only one number would mislead.

**Unresolved is almost always vendor IP or a missing PDK**, never a parse failure of
the code itself.

**Half of the famous cores are not RTL.** BOOM ships 2 Verilog files, rocket-chip 11;
both are Chisel generators. logisim-cpu-project has no HDL at all.

**Five defects were found by running against new repositories**, each a silent merge
of something the tool should have complained about:

| version | defect | found on |
| --- | --- | --- |
| v0.24.1 | `complete: True` on 4.5% coverage | riscv-dv |
| v0.24.2 | same note printed six times | wave_rerunner |
| v0.24.3 | transitive invalidation explained as "cannot explain it" | Anvil-Pro |
| v0.27.1 | duplicate module definitions merged silently | rustdv/rustdv |
| v0.27.1 | correction: three `module Top` declarations | Anvil-Pro |

**The prover is the weak module.** 2 of 24 files accepted on qeciphy, 2 of 125 on
CV32E40P. Nothing in 30 repositories changes that.

## What was not measured

No simulation and no formal run in any of these sweeps. Every result is UNKNOWN for
want of evidence, not because a check failed.

The one time real simulation was run: 33 runs from picorv32/picosoc modules, 6 killed
mutants, waveform features against a 1-NN classifier — 82% accuracy against an 82%
majority baseline. Reframed as signal-level localisation, 1338 samples and 9
positives gave 92.7% against a 99.3% baseline. Three framings, three failures to beat
guessing.
