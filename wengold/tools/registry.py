"""The WENGOLD tool registry.

Three groups, mirroring how chip teams actually organise their flow:

  01  Simulation, debug and testbench
  02  Formal, emulation and FPGA
  03  Around the flow

Open-source tools are first-class (`open_source=True`); commercial tools plug in
through the same adapter contract.
"""
from __future__ import annotations

from .base import ToolSpec

# 01 · Simulation, debug and testbench --------------------------------------
SIMULATION = [
    ToolSpec("vcs",         "VCS",         "Synopsys",  "simulation", "simulator",  False, "vcs"),
    ToolSpec("xcelium",     "Xcelium",     "Cadence",   "simulation", "simulator",  False, "xrun"),
    ToolSpec("questa",      "Questa",      "Siemens",   "simulation", "simulator",  False, "qsim"),
    ToolSpec("verilator",   "Verilator",   "Verilator", "simulation", "simulator",  True,  "verilator"),
    ToolSpec("verdi",       "Verdi",       "Synopsys",  "simulation", "debug",      False, "verdi"),
    ToolSpec("simvision",   "SimVision",   "Cadence",   "simulation", "debug",      False, "simvision"),
    ToolSpec("verisium",    "Verisium",    "Cadence",   "simulation", "debug",      False, None),
    ToolSpec("gtkwave",     "GTKWave",     "GTKWave",   "simulation", "waveform",   True,  "gtkwave"),
    ToolSpec("cocotb",      "cocotb",      "cocotb",    "simulation", "testbench",  True,  None),
    ToolSpec("uvm",         "UVM",         "Accellera", "simulation", "testbench",  True,  None),
]

# 02 · Formal, emulation and FPGA -------------------------------------------
FORMAL = [
    ToolSpec("jaspergold",  "JasperGold",  "Cadence",   "formal", "formal",     False, "jg"),
    ToolSpec("vcformal",    "VC Formal",   "Synopsys",  "formal", "formal",     False, "vcformal"),
    ToolSpec("onespin",     "OneSpin",     "Siemens",   "formal", "formal",     False, "onespin"),
    ToolSpec("zebu",        "ZeBu",        "Synopsys",  "formal", "emulation",  False, "zebu"),
    ToolSpec("palladium",   "Palladium",   "Cadence",   "formal", "emulation",  False, None),
    ToolSpec("veloce",      "Veloce",      "Siemens",   "formal", "emulation",  False, None),
    ToolSpec("vivado",      "Vivado",      "AMD",       "formal", "fpga",       False, "vivado"),
    ToolSpec("quartus",     "Quartus",     "Altera",    "formal", "fpga",       False, "quartus_sh"),
    ToolSpec("yosys",       "Yosys",       "YosysHQ",   "formal", "synthesis",  True,  "yosys"),
    ToolSpec("vmanager",    "vManager",    "Cadence",   "formal", "regression", False, "vmanager"),
]

# 03 · Around the flow -------------------------------------------------------
FLOW = [
    ToolSpec("git",         "Git",         "Git",       "flow", "vcs",      True, "git"),
    ToolSpec("github",      "GitHub",      "GitHub",    "flow", "forge",    False, None),
    ToolSpec("gitlab",      "GitLab",      "GitLab",    "flow", "forge",    False, None),
    ToolSpec("jira",        "Jira",        "Atlassian", "flow", "tracker",  False, None),
    ToolSpec("slack",       "Slack",       "Salesforce","flow", "chat",     False, None),
    ToolSpec("tcl",         "Tcl",         "Tcl",       "flow", "script",   True,  "tclsh"),
    ToolSpec("python",      "Python",      "PSF",       "flow", "script",   True,  "python3"),
    ToolSpec("make",        "Make",        "GNU",       "flow", "build",    True,  "make"),
]

# WENGOLD's own open verification backends, grouped under formal for the graph.
_EXTRA = [
    ToolSpec("symbiyosys",  "SymbiYosys",  "YosysHQ",   "formal", "formal",  True, "sby"),
    ToolSpec("z3",          "Z3",          "Microsoft", "formal", "solver",  True, "z3"),
    ToolSpec("iverilog",    "Icarus Verilog", "Icarus", "simulation", "simulator", True, "iverilog"),
    ToolSpec("surelog",     "Surelog",     "CHIPS Alliance", "flow", "parser", True, "surelog"),
    ToolSpec("verible",     "Verible",     "CHIPS Alliance", "flow", "lint", True, "verible-verilog-lint"),
]

TOOL_GROUPS: dict[str, list[ToolSpec]] = {
    "simulation": SIMULATION + [t for t in _EXTRA if t.group == "simulation"],
    "formal": FORMAL + [t for t in _EXTRA if t.group == "formal"],
    "flow": FLOW + [t for t in _EXTRA if t.group == "flow"],
}

GROUP_TITLES = {
    "simulation": "Simulation, debug and testbench",
    "formal": "Formal, emulation and FPGA",
    "flow": "Around the flow",
}


def tools_in_group(group: str) -> list[ToolSpec]:
    return list(TOOL_GROUPS[group])


def all_tools() -> list[ToolSpec]:
    return [t for group in TOOL_GROUPS.values() for t in group]
