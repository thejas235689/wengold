# WENGOLD graphical schematic, mapped synthesis, STA and physical flow

The **Synthesis / PPA** Linux workbench now exposes a real gate-connectivity
diagram built from the Yosys JSON netlist. Cells, their actual Yosys types
and connectivity bit IDs are derived from the generated netlist. It supports
pan and zoom and deliberately caps large schematics at 180 cells / 420 edges.
Neither the drawing nor its routing corresponds to real physical placement.

## How to use

1. Open a project folder and choose **Synthesis / PPA**.
2. Select a single Verilog/SystemVerilog RTL module source; enter the top
   module name, if known. Multi-file designs should use a reviewed flow
   manifest until a complete filelist-aware synthesis frontend exists.
3. Click **Run Yosys Synthesis** to generate an actual generic netlist.
   Switch between **Gate schematic** and **Netlist details**, and use Zoom.
4. To map gates to technology cells, provide a **project-relative Liberty**
   path ending in `.lib`; the synthesis backend runs Yosys dfflibmap and
   ABC mapping, and reports mapped cell area only when Yosys provides it.
   This is a library-area estimate, not physical die area.
5. For an OpenSTA timing run, additionally supply an explicit top module and
   a project-relative `.sdc` file. The backend writes mapped Verilog and
   invokes an installed `sta` executable with the supplied Liberty and SDC.
   The actual report_checks, WNS and TNS output goes in the EDA evidence pane.
   Review unconstrained paths and warnings; successful tool exit is not
   timing signoff.
6. For power, DRC, LVS, PEX, physical place-and-route, or commercial signoff,
   select a **reviewed project-local EDA manifest** and use **Inspect tool
   recipe** before **Run reviewed EDA flow**. The manifest runner requires
   executable tool commands and captures exit status, input hashes and logs.
   Actual DRC/LVS/power pass criteria still require engineer review.

## Required dependencies

- Generic schematic / synthesis: `yosys` installed on Linux.
- Mapped area: compatible cell Liberty file for your technology.
- Timing: `sta` (OpenSTA), mapped netlist, Liberty, suitable SDC constraints.
- Power: a power estimation or signoff engine, technology power data,
  switching activity (VCD/SAIF), corner and voltage specifications.
- Layout/physical: approved PDK, technology/rule decks, layout data,
  extracted parasitics and real DRC/LVS/PEX/place-route tools.

EDA manifests can have kind `sta`, `power`, `physical_place_route`,
`physical_drc`, `physical_lvs`, `physical_pex`, or other supported kinds.
Manifest source files must be reviewed: WENGOLD executes their declared
commands only after explicit GUI confirmation, never from model text.

## Engineering limitations

- The native schematic does not replace a gate-level static timing or
  transistor netlist viewer, and Yosys generic cell names may not map to PDK.
- Single-source Yosys synthesis is insufficient for most SoCs containing
  packages, custom macros or unresolved IP; use approved filelist flows.
- The mapped area is an estimate based on Liberty area attributes and
  omits buffers, CTS, routing, filler cells, and later physical optimization.
- STA tool output alone does not prove full-path coverage or SDC completeness.
- WENGOLD does not contain foundry PDKs, licenses, PPA golden baselines,
  proprietary tools or a physical placement-and-route engine.
- Power is not calculated from waveform toggles without library and tool
  integration; the workflow explicitly indicates not run when absent.

## Validation

Run under Linux:

```bash
python3 -m pytest -q tests/test_synthesis_tools.py tests/test_schematic_graph.py
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_native_studio.py
```

The dedicated Linux desktop GitHub workflow runs these alongside the real
installed Yosys counter synthesis, UI screenshot and installation smoke.
Real Liberty/STA/physical PDK signoff remains a separate site-specific
qualification gate.
