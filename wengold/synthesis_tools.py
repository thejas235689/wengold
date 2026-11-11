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


def run_synthesis(root: str | Path, rel: str, top: str = "") -> dict:
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
    source = path.read_bytes()
    with tempfile.TemporaryDirectory(prefix="wengold-yosys-") as temp:
        work = Path(temp)
        (work / "design.v").write_bytes(source)
        steps = ["read_verilog -sv design.v"]
        steps.append("hierarchy -check -top " + top if top else "hierarchy -auto-top")
        steps += ["proc", "opt", "techmap", "opt", "check", "write_json netlist.json"]
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
            "log": log,
            "timing": "NOT RUN — requires mapped Liberty/SDC/STA",
            "chip_area": "NOT AVAILABLE — generic cells are not a mapped physical area",
            "power": "NOT RUN — requires library, activity, and power analysis",
            "schematic": "Netlist-derived hierarchy; full placed/routed schematic not available",
            "qualification": "Generic Yosys RTL synthesis only — NOT PPA signoff",
        }
