"""Real opt-in RTL synthesis for the native Implementation workspace.

Yosys is invoked only on a bounded existing project source. Everything shown
comes from its generated JSON netlist; no PPA or timing estimate is invented.
Full ASIC signoff needs technology libraries, SDC and appropriate EDA tools.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def run_synthesis(root: str | Path, rel: str, top: str = "", liberty: str = "", sdc: str = "") -> dict:
    from .studio_workspace import project_file
    if top and not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9$]*", top):
        raise ValueError("invalid top module")
    path = project_file(root, rel, {".v", ".sv"})
    if path.stat().st_size > 2_000_000:
        raise ValueError("source exceeds 2 MiB single-file synthesis limit")
    yosys = shutil.which("yosys")
    if not yosys:
        return {"ok": False, "status": "unavailable", "message":
                "Yosys is not installed. Install yosys or configure a reviewed EDA flow."}
    lib_path = None
    if liberty:
        lib_path = project_file(root, liberty, {".lib"})
        if lib_path.stat().st_size > 24_000_000:
            raise ValueError("Liberty exceeds 24 MiB mapping limit")
    sdc_path = None
    if sdc:
        if not lib_path or not top:
            raise ValueError("STA requires both an explicit top module and Liberty")
        sdc_path = project_file(root, sdc, {".sdc"})
        if sdc_path.stat().st_size > 1_000_000:
            raise ValueError("SDC exceeds 1 MiB analysis limit")
    source = path.read_bytes()
    with tempfile.TemporaryDirectory(prefix="wengold-yosys-") as temp:
        work = Path(temp)
        (work / "design.v").write_bytes(source)
        steps = ["read_verilog -sv design.v"]
        steps.append("hierarchy -check -top " + top if top else "hierarchy -auto-top")
        steps += ["proc", "opt", "techmap", "opt"]
        if lib_path:
            (work / "cells.lib").write_bytes(lib_path.read_bytes())
            steps += ["read_liberty -lib cells.lib", "dfflibmap -liberty cells.lib",
                      "abc -liberty cells.lib", "clean", "check",
                      "stat -liberty cells.lib"]
        else:
            steps += ["check"]
        steps.append("write_json netlist.json")
        if lib_path:
            steps.append("write_verilog -noattr mapped.v")
        (work / "run.ys").write_text("\n".join(steps) + "\n")
        try:
            result = subprocess.run([yosys, "-Q", "-T", "-s", "run.ys"],
                                    cwd=work, capture_output=True, text=True,
                                    check=False, timeout=60)
        except subprocess.TimeoutExpired:
            return {"ok": False, "status": "timeout", "log": "Yosys exceeded 60 seconds"}
        except OSError as exc:
            return {"ok": False, "status": "unavailable", "log": str(exc)}
        log = (result.stdout + "\n" + result.stderr)[-16000:]
        if result.returncode or not (work / "netlist.json").is_file():
            return {"ok": False, "status": "failed", "exit_code": result.returncode, "log": log,
                    "source_sha256": hashlib.sha256(source).hexdigest()}
        if (work / "netlist.json").stat().st_size > 12_000_000:
            return {"ok": False, "status": "oversize", "log": "Netlist JSON exceeded 12 MiB"}
        netlist = json.loads((work / "netlist.json").read_text())
        from .schematic_graph import build_schematic
        schematic = build_schematic(netlist, preferred_top=top)
        # Parse area only when the actual Yosys mapping report includes it.
        area = None
        if lib_path:
            candidates = re.findall(
                r"Chip area for module[^\n]*?:\s*([0-9]+(?:\.[0-9]+)?)",
                log, flags=re.I)
            if candidates:
                area = float(candidates[-1])
        sta_evidence = {"status": "not_run",
                        "reason": "Provide approved Liberty, explicit top, SDC and OpenSTA to run timing"}
        if sdc_path:
            sta_exe = shutil.which("sta")
            if not sta_exe:
                sta_evidence = {"status": "unavailable", "reason": "OpenSTA executable sta not found"}
            elif not (work / "mapped.v").is_file():
                sta_evidence = {"status": "unavailable", "reason": "Yosys did not produce mapped Verilog"}
            else:
                (work / "constraints.sdc").write_bytes(sdc_path.read_bytes())
                tcl = [
                    "read_liberty cells.lib",
                    "read_verilog mapped.v",
                    "link_design " + top,
                    "read_sdc constraints.sdc",
                    "check_setup",
                    "report_checks -path_delay max -group_path_count 10",
                    "report_wns", "report_tns",
                ]
                (work / "timing.tcl").write_text("\n".join(tcl) + "\n")
                try:
                    sta_result = subprocess.run(
                        [sta_exe, "-exit", "timing.tcl"], cwd=work,
                        capture_output=True, text=True, timeout=60, check=False)
                    sta_log = (sta_result.stdout + "\n" + sta_result.stderr)[-24000:]
                    failed = (sta_result.returncode != 0 or
                              bool(re.search(r"(^|\n)Error:", sta_log, re.I)))
                    sta_evidence = {
                        "status": "failed" if failed else "tool_completed",
                        "ok": not failed, "exit_code": sta_result.returncode,
                        "log": sta_log,
                        "sdc_sha256": hashlib.sha256(sdc_path.read_bytes()).hexdigest(),
                        "qualification": "OpenSTA output requires engineer review; not signoff"}
                except subprocess.TimeoutExpired:
                    sta_evidence = {"status": "timeout", "ok": False}
        modules = netlist.get("modules") or {}
        structure = []
        totals = Counter()
        for name, body in sorted(modules.items()):
            cells = body.get("cells") or {}
            counts = Counter(c.get("type", "unknown") for c in cells.values())
            totals.update(counts)
            structure.append({"name": name, "cells": len(cells),
                              "wires": len(body.get("netnames") or {}),
                              "ports": len(body.get("ports") or {}),
                              "cell_types": dict(counts)})
        return {
            "ok": True, "status": "synthesized_generic_netlist",
            "source": rel, "top": top or "auto-selected",
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "netlist_sha256": hashlib.sha256((work / "netlist.json").read_bytes()).hexdigest(),
            "module_count": len(modules),
            "total_cells": sum(totals.values()),
            "total_wire_names": sum(x["wires"] for x in structure),
            "cell_types": dict(totals),
            "modules": structure,
            "schematic_graph": schematic,
            "mapping": "liberty" if lib_path else "generic",
            "liberty_sha256": hashlib.sha256(lib_path.read_bytes()).hexdigest() if lib_path else None,
            "mapped_cell_area": area,
            "sta_evidence": sta_evidence,
            "log": log,
            "timing": ("OpenSTA " + sta_evidence["status"] if sdc_path
                       else "NOT RUN — requires mapped Liberty/SDC/STA"),
            "chip_area": (
                f"Yosys liberty-mapped cell area: {area} (Liberty area units)"
                if area is not None else
                "NOT AVAILABLE — mapped library report missing or no Liberty supplied"),
            "power": "NOT RUN — requires library, activity, and power analysis",
            "schematic": "Netlist-derived cell connectivity; not placed/routed",
            "qualification": (
                "Liberty-mapped synthesis estimate only — NOT placed/routed signoff"
                if lib_path else "Generic Yosys RTL synthesis only — NOT PPA signoff"),
        }
