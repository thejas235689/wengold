from wengold.rtl_hierarchy import build_rtl_hierarchy


def sample_netlist():
    return {"modules": {
        "top": {
            "attributes": {"top": "1"},
            "ports": {"clk": {"direction": "input", "bits": [2]}},
            "netnames": {"clk": {"bits": [2]}, "bus": {"bits": [3, 4]}},
            "cells": {"u_sub": {
                "type": "sub",
                "attributes": {"src": "rtl/top.sv:42.3-48.8"},
                "connections": {"clk_i": [2], "data_i": [3, 4]},
                "port_directions": {"clk_i": "input", "data_i": "input"},
            }},
        },
        "sub": {
            "attributes": {"src": "rtl/sub.sv:1.1-10.2"},
            "ports": {
                "clk_i": {"direction": "input", "bits": [10]},
                "data_i": {"direction": "input", "bits": [11, 12]},
            },
            "netnames": {"clk_i": {"bits": [10]}, "data_i": {"bits": [11, 12]}},
            "cells": {},
        },
    }}


def test_expands_hierarchy_and_preserves_instance_source():
    graph = build_rtl_hierarchy(sample_netlist(), top="top")
    assert [node["id"] for node in graph["nodes"]] == ["top", "top.u_sub"]
    child = graph["nodes"][1]
    assert child["module"] == "sub"
    assert child["source"]["file"] == "rtl/top.sv"
    assert child["source"]["line"] == 42


def test_maps_real_parent_bits_to_child_ports():
    graph = build_rtl_hierarchy(sample_netlist(), top="top")
    assert len(graph["edges"]) == 3
    assert graph["edges"][0]["from"] == "top.clk"
    assert graph["edges"][0]["to"] == "top.u_sub.clk_i"
    assert graph["edges"][1]["to"] == "top.u_sub.data_i"


def test_rejects_missing_top():
    import pytest
    with pytest.raises(ValueError, match="Top module"):
        build_rtl_hierarchy(sample_netlist(), top="missing")


def test_bounds_instance_expansion():
    graph = build_rtl_hierarchy(sample_netlist(), top="top", max_instances=1)
    assert graph["instance_count"] == 1
    assert graph["truncated"] is True
