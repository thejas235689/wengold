"""Netlist-derived schematic and evidence-only implementation tests."""
from wengold.schematic_graph import build_schematic


def test_true_cell_connectivity_only():
    netlist = {"modules": {"cpu": {"attributes": {"top": "1"}, "cells": {
        "u_inv": {"type": "$_NOT_", "connections": {"A": [1], "Y": [2]},
                  "port_directions": {"A": "input", "Y": "output"}},
        "u_ff": {"type": "$_DFF_P_", "connections": {"D": [2], "Q": [3]},
                 "port_directions": {"D": "input", "Q": "output"}},
    }}}}
    data = build_schematic(netlist, preferred_top="cpu")
    assert data["module"] == "cpu"
    assert len(data["cells"]) == 2
    assert any(e["from"] == "u_inv" and e["to"] == "u_ff" and e["bit"] == 2
               for e in data["edges"])
    assert "not a physical layout" in data["qualification"]


def test_empty_netlist_shows_no_invented_connectivity():
    result = build_schematic({"modules": {}})
    assert result["cells"] == [] and result["edges"] == []


def test_limited_schematic_size():
    cells = {f"c{i}": {"type": "AND", "connections": {}, "port_directions": {}}
             for i in range(240)}
    graph = build_schematic({"modules": {"top": {"cells": cells}}}, preferred_top="top")
    assert len(graph["cells"]) == 180
    assert graph["truncated"]


def test_new_eda_flow_kinds_available():
    from wengold.eda_flows import FLOWS
    assert {"sta", "power", "physical_place_route", "physical_drc",
            "physical_lvs", "physical_pex"}.issubset(FLOWS)
