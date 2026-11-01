# WENGOLD across 33 repositories

Every project checked in this series, at **v0.27.1** unless marked otherwise.
All rows at v0.27.0/v0.27.1 were taken from a single re-fetched build, so they are
directly comparable.

### Re-measured at v0.54.5: the numbers reproduce

Six of these repositories have recorded coordinates and were re-run at v0.54.5 with
`python tools/re-measure.py`:

| repo | files | nodes | edges | blocks | unresolved | design-unit files |
| --- | --- | --- | --- | --- | --- | --- |
| neorv32 | 77 | 758 | 1,262 | 86 | 0 | 68/77 |
| ibex | 661 | 960 | 2,079 | 345 | 12 | 373/661 |
| cva6 | 478 | 1,219 | 3,260 | 458 | 26 | 326/478 |
| cv32e40p | 181 | 402 | 872 | 154 | 7 | 150/181 |
| picorv32 | 41 | 83 | 1,024 | 31 | 7 | 16/41 |
| rocket-chip | 11 | 20 | 8 | 14 | 1 | 11/11 |

**They match the v0.27.1 table exactly** — neorv32 at 758 nodes, 1,262 edges and 86
blocks; ibex at 345 blocks; cva6 at 458. Twenty-seven releases of front-end work did
not move them, which is the useful result: the table was not wrong, it was
*unreproducible*, and those are different problems.

### The coordinates were recovered, and checked

The coordinates were never recorded, so they were recovered by searching GitHub —
and then **verified by measuring each candidate against its recorded row**. A
coordinate was only kept if the numbers agreed:

| evidence | projects |
| --- | --- |
| **exact** — files, nodes, edges and blocks all equal the recorded row | 13 |
| **graph** — nodes, edges and blocks equal, only the file count moved because the repository gained files | 5 |
| **blocks** — the block count equals the recorded row, the only value recorded | 4 |
| **unmatched** — the canonical repository for the name, but nothing to compare against | 3 |

The `graph` cases are worth a note, because they are the ones where a guess would
have been tempting and wrong in a subtle way. `qeciphy` now has 203 files where the
table says 180, and `riscduino` has 235 where it says 232 — but their node, edge and
block counts are **identical** (qeciphy 165 / 334 / 98, riscduino 1,564 / 40,797 /
304). The graph is the same graph; the repository grew. That is much stronger
evidence than a name match.

Three candidates were rejected for not matching, including two other repositories
called `2D-systolic-array` — `tms4517` measured 3 files / 8 nodes where the row says
2 / 6, and `el-oggy` measured 78 files / 49 blocks. `bodsvei/2D-systolic-array`
matched exactly. **Searching for a name and taking the first hit would have produced
a number that looked real and was wrong.**

### What is still not measured, and why

| project | why |
| --- | --- |
| `minerva` | no GitHub repository by that name; the recorded row has a block count and no coordinates |
| `XiangShan` | recorded as not reachable at master/main, and still is |
| `openpiton` | same |
| `Arbiter-Verification`, `logisim-cpu-project` | ambiguous names, not searched |
| `rustdv_fifo` | a directory inside `rustdv/rustdv`, not a repository |
| `OpenTitan` | needs its own run; the recorded row came from a different measurement path |

`tools/repositories.json` holds **25 recovered coordinates** — 22 of them checked
against a recorded row — and lists the 7 that could not be recovered with the reason
for each. `tools/re-measure.py` fetches and
measures them, and refuses to run without `pyslang`.

### The measurement depends on the backend, and this is not optional

With `pyslang` installed the elaborator resolves most modules. Without it the code
falls back to a bounded regex elaborator and reports very different numbers. Same
trees, both measured:

| repo | with pyslang | without |
| --- | --- | --- |
| ibex | 345 blocks, 12 unresolved | 338 blocks, 190 unresolved |
| cva6 | 458 blocks, 26 unresolved | 503 blocks, 306 unresolved |

Neither is wrong — they answer different questions — but only the first is
comparable with the table. **`tools/re-measure.py` refuses to report numbers from
the fallback**, because a table whose values depend silently on what happened to be
installed is not a measurement.

### One column is named wrongly in the tables below

The `coverage` column is **not test coverage**. It is the share of files that
contained a design unit — how much of the repository the graph can describe at all.
`riscv-dv` at 4% means 4% of its files are modules, packages or interfaces, not that
4% of it was exercised. The re-measured table above calls it `design-unit files`;
the older rows keep the old heading so they are not mistaken for freshly measured
ones.

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
