"""Read-only self-diagnostics for Linux Silicon Studio.

Inspect panel availability and actual locally installed tools. Presence of a UI
control is NOT evidence of end-to-end simulation or proof correctness.
"""
from __future__ import annotations

from pathlib import Path
import shutil


def diagnostics(window, QtWidgets) -> dict:
    controls = {
        "project": ("openProjectButton", "rescanFilesButton"),
        "rtl_editor": ("openRtlButton", "saveRtlButton"),
        "synthesis": ("implSource", "implRunSynthesis", "implPpaEvidence"),
        "waveforms": ("waveFilePicker", "waveformTable", "waveRootCauseCandidates"),
        "formal": ("formalSourcePicker",),
        "local_ai": ("aiBackend", "aiConnect", "aiGenerate", "aiEvidence"),
        "dv_workflow": ("dvSpec", "dvRtl", "dvIntakeButton", "dvPlanButton", "dvTestConnection", "dvCoverageButton"),
        "workers": ("durableWorkerQueue",),
    }
    ui = {}
    for category, names in controls.items():
        present = []
        missing = []
        for name in names:
            obj = window.findChild(QtWidgets.QWidget, name)
            (present if obj is not None else missing).append(name)
        ui[category] = {"present": present, "missing": missing,
                        "controls_present": len(missing) == 0}
    commands = ("iverilog", "vvp", "verilator", "yosys", "cargo",
                "satya", "sta", "ngspice", "klayout")
    tools = {name: shutil.which(name) for name in commands}
    # Runtime readiness is NOT a certification of an actual passing run.
    gates = {
        "local_llm_inference": {
            "status": "requires_live_probe",
            "action": "DV Workflow > Test connection, then generate and review an artifact",
        },
        "uvm_simulation": {
            "status": "requires_external_simulator_and_uvm_library",
            "action": "Run an approved UVM regression manifest and inspect generated evidence",
        },
        "rtl_simulation": {
            "status": "tools_detected_not_executed" if tools["iverilog"] and tools["vvp"]
                      else "simulator_missing",
            "action": "Run the bundled counter4 simulation and inspect measured coverage",
        },
        "generic_synthesis": {
            "status": "tool_detected_not_executed" if tools["yosys"] else "tool_missing",
            "action": "Run Yosys in Synthesis / PPA on the selected project",
        },
        "sta_signoff": {
            "status": "requires_libraries_constraints_and_review",
            "action": "Supply Liberty, SDC, corners and inspect real OpenSTA timing reports",
        },
        "physical_signoff": {
            "status": "requires_pdk_rule_decks_and_licensed_or_approved_tools",
            "action": "Execute and review approved DRC/LVS/PEX flows with actual layout data",
        },
    }
    inventory = window.state.get("project_inventory") or {}
    path = Path(window.state["path"])
    return {
        "project": str(path),
        "project_exists": path.is_dir(),
        "inventory": inventory.get("counts", {}),
        "inventory_truncated": inventory.get("truncated", False),
        "ui": ui,
        "installed_tools": tools,
        "runtime_gates": gates,
        "notes": [
            "Presence of a button does not prove its workflow succeeds.",
            "Absent simulators, Yosys, RustDV/Satya or PDK-backed EDA flows require installation/configuration.",
            "Open a real project root, not your HOME directory.",
            "Run a real simulator regression before claiming verification or signoff.",
        ],
    }
