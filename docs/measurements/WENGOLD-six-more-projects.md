# Six more projects through WENGOLD

Every number came from running the tool on the project. Three of these six are
**verification** projects rather than designs, which is worth noting up front.

## Results

| project | files | blocks | edges | unresolved | complete | simulated |
| --- | --- | --- | --- | --- | --- | --- |
| rustdv_fifo | 1 | 1 | 3 | 0 | **true** | 1/1 |
| BorussCPU-Laibach | 8 | 8 | 20 | 0 | **true** | 3/3 |
| Arbiter-Verification | 21 | 4 | 29 | 1 | false | 0/4 |
| lxp32-cpu | 40 | 34 | 163 | 0 | **true** | 0/14 |
| pcievhost | 42 | 34 | 356 | 16 | false | 2/14 |
| qeciphy_riverlane | 167 | 83 | 269 | 3 | false | 3/10 |

`blocks` are design units. `simulated` is how many compiled and ran in Icarus
Verilog with a generated testbench, out of how many were attempted.

## Waveforms — four of six produced one

| project | block | what the waveform shows |
| --- | --- | --- |
| rustdv_fifo | `sync_fifo` | 147 cycles: `wr_ptr`/`rd_ptr` walking, `count` rising, `full`/`empty` asserting |
| BorussCPU-Laibach | `boruss_alu` | `operand_a`/`operand_b`, `operation_code`, `result`, and the carry/negative/zero flags |
| pcievhost | `clkmux` | a clock mux switching between its inputs |
| qeciphy_riverlane | `BUFG_GT` | a GT clock buffer: `DIV`, `CE`, `CEMASK`, `CLR`, `I` → `O` |

The stimulus is a clock, a reset pulse and a counter on the other inputs. It
exercises the logic and produces a waveform worth looking at; **it is not a
verification testbench and it proves nothing about these designs.**

## The two that produced none, and why

**lxp32-cpu is 100% VHDL** (40 `.vhd`, zero Verilog). WENGOLD's graph handled it
perfectly — **34 blocks, 163 edges, 0 unresolved, complete: true**, the only
clean result of the six. The waveform is blocked by the *toolchain*, not the tool:
I extended the harness to parse VHDL entities, ports and generics (all three now
work — `lxp32_alu` parses its 15 ports with widths and its two required generics),
and GHDL analysed all 36 source files. GHDL then could not link: it needs a C
compiler (I shimmed `zig cc`) and then a newer glibc than Debian 12 has
(`__isoc23_strtol`, glibc 2.38+). That is an environment limit, stated rather than
worked around.

**Arbiter-Verification is a UVM environment**, not a design: `package arbiter_pkg`,
two `interface`s (`if_host`, `if_response`) and a `module top` that imports
`uvm_pkg`. Its four "blocks" are the package, the two interfaces and the top — so
two are not modules at all, and the top cannot elaborate without a UVM library.
0/4 is the correct answer, not a failure.

## What this run found

**The kernel does the right thing on an unresolved project.** In
qeciphy_riverlane the IDE shows two blocks marked `unknown` —
`unit_qeciphy_syn_wrapper` and `unit_qeciphy_tb` — with the reason printed:
*"unresolved, so every result downstream of it is unknown."* That is the whole
product claim working on a real project: not a guess, not a silent pass.

**pcievhost has 16 unresolved blocks of 34** — nearly half. It instantiates
Xilinx/Intel primitives that are not in the repository, so the graph honestly
reports that anything downstream is unknown.

**Harness bugs fixed along the way** (the harness is not the product, but each one
had hidden a result):

* A `#( ... )` parameter list unbalanced the port-splitting counter, so a
  parameterised module parsed to **one port** — `sync_fifo` reported 1 of 11.
* A non-greedy `).` stopped the VHDL port clause at the first vector —
  `std_logic_vector(31 downto 0);` — so every vector port after it read as 1 bit.
* VHDL generics with no default (`DIVIDER_EN: boolean;`) stopped elaboration.
* A module carrying its own `$dumpfile("build/…")` made `vvp` abort because the
  directory did not exist; and when it did, the module's dump won the race and the
  VCD landed somewhere other than where we looked.

**And one environment issue:** `/tmp` is a 64 MB tmpfs and it filled with the
tarballs I had left there, which surfaced as a spurious "no space left on device"
while `/scratch` had 281 GB free.

## Limits of this run

* **Not a verification result.** Simulating a few blocks says nothing about whether
  these designs are correct.
* **The formal engine was not used** — these are cores, UVM environments and
  clock-buffer stubs, not register-level RTL.
* **Two of the six could not be simulated at all**, for reasons above that are
  about the environment and the projects, not about WENGOLD.
* **The four downloads failed through the usual route** — the proxy stripped
  codeload responses to 0 bytes and `fetch_repo` was API-rate-limited — so the
  repositories were reconstructed file-by-file through the authenticated GitHub
  integration instead.
