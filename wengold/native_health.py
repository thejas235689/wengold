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
    inventory = window.state.get("project_inventory") or {}
    path = Path(window.state["path"])
    return {
        "project": str(path),
        "project_exists": path.is_dir(),
        "inventory": inventory.get("counts", {}),
        "inventory_truncated": inventory.get("truncated", False),
        "ui": ui,
        "installed_tools": tools,
        "notes": [
            "Presence of a button does not prove its workflow succeeds.",
            "Absent simulators, Yosys, RustDV/Satya or PDK-backed EDA flows require installation/configuration.",
            "Open a real project root, not your HOME directory.",
            "Run a real simulator regression before claiming verification or signoff.",
        ],
    }
