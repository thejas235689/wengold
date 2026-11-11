"""Bounded, evidence-backed gate-level connectivity for PyQt schematic viewing.

Only Yosys JSON connections are used. The graph is an abstract connectivity
view, not a placed physical layout or a transistor-level circuit.
"""
from __future__ import annotations

from collections import defaultdict


MAX_CELLS = 180
MAX_EDGES = 420


def build_schematic(netlist: dict, *, preferred_top: str = "") -> dict:
    modules = netlist.get("modules", {})
    if not modules:
        return {"module": "", "cells": [], "edges": [], "truncated": False}
    if preferred_top in modules:
        module_name = preferred_top
    else:
        tops = [name for name, data in modules.items()
                if str(data.get("attributes", {}).get("top", "0")) in ("1", "00000000000000000000000000000001")]
        module_name = tops[0] if tops else next(iter(modules))
    module = modules[module_name]
    cells = module.get("cells") or {}
    nodes = []
    bit_drivers: dict[int, list[str]] = defaultdict(list)
    bit_sinks: dict[int, list[str]] = defaultdict(list)
    for name, cell in list(sorted(cells.items()))[:MAX_CELLS]:
        nodes.append({"id": name, "type": cell.get("type", "unknown")})
        for port, bits in cell.get("connections", {}).items():
            direction = cell.get("port_directions", {}).get(port, "input")
            for bit in bits:
                if not isinstance(bit, int):
                    continue
                if direction == "output":
                    bit_drivers[bit].append(name)
                else:
                    bit_sinks[bit].append(name)
    edges = []
    seen = set()
    for bit, drivers in bit_drivers.items():
        for src in drivers:
            for dst in bit_sinks.get(bit, []):
                if src == dst or (src, dst) in seen:
                    continue
                seen.add((src, dst))
                edges.append({"from": src, "to": dst, "bit": bit})
                if len(edges) >= MAX_EDGES:
                    break
            if len(edges) >= MAX_EDGES:
                break
        if len(edges) >= MAX_EDGES:
            break
    return {
        "module": module_name, "cells": nodes, "edges": edges,
        "total_cells": len(cells),
        "truncated": len(cells) > MAX_CELLS or len(edges) >= MAX_EDGES,
        "qualification": "Yosys netlist connectivity only; not a physical layout",
    }
