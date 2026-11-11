# OpenPiton compatibility with WENGOLD

## Test scope and provenance

OpenPiton official source: https://github.com/PrincetonUniversity/openpiton
OpenPiton default branch is `openpiton` (not `main`).
Tested baseline is pinned to upstream commit `1c6bfd2d2ea53ddd7b6f933fa2d439d1a540e207`.
The original manycore platform uses SPARC; OpenPiton+Ariane/CVA6 RISC-V support resides in an external Git submodule.

## What the dedicated CI checks

The `OpenPiton Compatibility Smoke` workflow checks out real upstream OpenPiton
and WENGOLD in separate directories; it does not vendor upstream RTL.
It copies five files from `piton/design/chip/chip_bridge/rtl` into a temporary
isolated fixture and performs:

- `wengold index` on actual upstream RTL with the installed pyslang frontend
- comparison against expected `chip_bridge`, `bridge_network_chooser`, and `sync_fifo` RTL units
- real `build_state` and actual CIW `summary`, `files`, `blocks`, `help` dispatch
- actual Icarus compilation of the standalone `sync_fifo.v` (`iverilog -g2012 -tnull -s sync_fifo`)
- a PyQt6 offscreen screenshot of WENGOLD running on the actual OpenPiton bridge directory
- upload of report and screenshot as GitHub Actions artifacts

An indexer exit code of zero does not establish complete elaboration. WENGOLD's
`complete`, unresolved modules, and issues are recorded separately in the JSON evidence.
Partial unresolved macros/includes may be expected because the bridge fixture
does not include all of OpenPiton's platform configuration and include files.

## Execute on your Linux machine

```bash
git clone --branch openpiton https://github.com/PrincetonUniversity/openpiton.git
git clone https://github.com/thejas235689/wengold.git
cd wengold
python3 -m pip install 'pyslang==12.1.0' PyQt6
sudo apt install iverilog  # Debian/Ubuntu; adapt to your Linux distro
python3 tools/check-openpiton.py --openpiton ../openpiton --report openpiton-smoke.json
wengold desktop --native ../openpiton/piton/design/chip/chip_bridge/rtl
```

For a RISC-V/Ariane experiment, clone/initialize the Ariane submodule as
specified in the upstream `.gitmodules` and use OpenPiton's simulation setup.
The upstream README documents `PITON_ROOT`, configuration macros, generated
files, and simulator tool requirements. These remain necessary for complete
manycore simulation and verification.

## Still unverified by this smoke

- Full SPARC manycore boot, L1.5/L2 coherence, or network under traffic
- RISC-V Ariane/CVA6 integration (external submodule not loaded by smoke)
- OpenPiton regression tests, UVM, directed test suites, and coverage
- ASIC synthesis, timing, layout, DRC/LVS or tapeout readiness

Do not label the complete SoC as VERIFIED based on the bridge smoke alone.
Only the exact checked stages can be called successful after CI passes.

## CI

Workflow: `.github/workflows/openpiton-compat.yml`.
Evidence artifact: `openpiton-wengold-bridge-evidence`.
Check the actual GitHub Actions job conclusion rather than assuming success
from the presence of an evidence file.
