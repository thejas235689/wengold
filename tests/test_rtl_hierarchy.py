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



def test_exact_hierarchical_vcd_crossprobe_maps_instance_ports():
    from wengold.rtl_hierarchy import crossprobe_hierarchy_to_vcd
    graph = build_rtl_hierarchy(sample_netlist(), top="top")
    wave = {"signals": [
        {"name": "tb_core_top.u_core.clk"},
        {"name": "tb_core_top.u_core.u_sub.clk_i"},
        {"name": "tb_core_top.u_core.u_sub.data_i"},
    ]}
    result = crossprobe_hierarchy_to_vcd(
        graph, wave, vcd_root="tb_core_top", dut_instance="u_core")
    assert result["matched_ports"] == 3
    assert result["unmatched_ports"] == 0
    assert result["status"] == "matched"
    assert result["matches"][0]["vcd_path"] == "tb_core_top.u_core.clk"


def test_riscv_filelist_loader_uses_run_py_authoritative_list(tmp_path):
    from wengold.rtl_hierarchy import load_riscv_core_sources
    (tmp_path / "sim").mkdir()
    (tmp_path / "rtl").mkdir()
    (tmp_path / "sim" / "run.py").write_text(
        "RTL_SRCS = ['rv64_pkg.sv', 'riscv_core_top.sv']" + chr(10))
    (tmp_path / "rtl" / "rv64_pkg.sv").write_text("package rv64_pkg; endpackage")
    (tmp_path / "rtl" / "riscv_core_top.sv").write_text("module riscv_core_top; endmodule")
    assert load_riscv_core_sources(tmp_path) == [
        "rtl/rv64_pkg.sv", "rtl/riscv_core_top.sv"]


def test_riscv_filelist_loader_rejects_missing_sources(tmp_path):
    import pytest
    from wengold.rtl_hierarchy import load_riscv_core_sources
    (tmp_path / "sim").mkdir()
    (tmp_path / "rtl").mkdir()
    (tmp_path / "sim" / "run.py").write_text(
        "RTL_SRCS = ['rv64_pkg.sv', 'riscv_core_top.sv']" + chr(10))
    (tmp_path / "rtl" / "rv64_pkg.sv").write_text("package rv64_pkg; endpackage")
    with pytest.raises(FileNotFoundError, match="missing files"):
        load_riscv_core_sources(tmp_path)


def test_invalid_frontend_is_rejected_before_tool_invocation(tmp_path):
    import pytest
    from wengold.rtl_hierarchy import elaborate_with_yosys
    with pytest.raises(ValueError, match="frontend"):
        elaborate_with_yosys(tmp_path, [], top="top", frontend="unknown")



def test_slang_frontend_emits_read_slang_and_records_frontend(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from wengold import rtl_hierarchy

    source = tmp_path / "top.sv"
    source.write_text("module top(input logic clk); endmodule")
    netlist = {"modules": {"top": {
        "attributes": {"top": "1"},
        "ports": {"clk": {"direction": "input", "bits": [1]}},
        "netnames": {"clk": {"bits": [1]}},
        "cells": {},
    }}}
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        output = tmp_path / ".wengold" / "rtl_hierarchy.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(netlist))
        class Result:
            returncode = 0
            stdout = "slang frontend ok"
            stderr = ""
        return Result()

    monkeypatch.setattr(rtl_hierarchy.shutil, "which", lambda _name: "/usr/bin/yosys")
    monkeypatch.setattr(rtl_hierarchy.subprocess, "run", fake_run)
    graph = rtl_hierarchy.elaborate_with_yosys(
        tmp_path, [source], top="top", frontend="slang")
    assert graph["frontend"] == "yosys-slang/read_slang"
    assert "plugin -i slang" in calls["command"][-1]
    assert "read_slang --top top --std 1800-2017" in calls["command"][-1]
    assert "--unroll-limit 4096" in calls["command"][-1]
    assert "read_verilog" not in calls["command"][-1]


def test_slang_frontend_validates_sv_standard(tmp_path):
    import pytest
    from wengold.rtl_hierarchy import elaborate_with_yosys
    with pytest.raises(ValueError, match="SystemVerilog standard"):
        elaborate_with_yosys(tmp_path, [], top="top",
                              frontend="slang", sv_standard="1364-2005")



def sample_slang_ast():
    return {"design": {"kind": "Root", "members": [
        {"kind": "Instance", "name": "top", "body": {
            "kind": "InstanceBody", "name": "top",
            "members": [
                {"kind": "Port", "name": "clk", "addr": 10,
                 "type": "logic", "direction": "In"},
                {"kind": "Net", "name": "clk", "addr": 11, "type": "logic"},
                {"kind": "Net", "name": "req_valid", "addr": 12, "type": "logic"},
                {"kind": "Net", "name": "data_bus", "addr": 13, "type": "logic[63:0]"},
                {"kind": "Instance", "name": "u_sub", "connections": [
                    {"port": {"kind": "Port", "name": "clk_i", "type": "logic",
                              "direction": "In"},
                     "expr": {"kind": "NamedValue", "type": "logic",
                              "symbol": "11 clk"}},
                    {"port": {"kind": "Port", "name": "valid_i", "type": "logic",
                              "direction": "In"},
                     "expr": {"kind": "NamedValue", "type": "logic",
                              "symbol": "12 req_valid"}},
                    {"port": {"kind": "Port", "name": "data_i", "type": "logic[63:0]",
                              "direction": "In"},
                     "expr": {"kind": "NamedValue", "type": "logic[63:0]",
                              "symbol": "13 data_bus"}},
                ], "body": {
                    "kind": "InstanceBody", "name": "sub",
                    "members": [
                        {"kind": "Port", "name": "clk_i", "type": "logic", "direction": "In"},
                        {"kind": "Port", "name": "valid_i", "type": "logic", "direction": "In"},
                        {"kind": "Port", "name": "data_i", "type": "logic[63:0]", "direction": "In"},
                        {"kind": "Instance", "name": "u_leaf", "connections": [],
                         "body": {"kind": "InstanceBody", "name": "leaf", "members": [
                             {"kind": "Port", "name": "enable", "type": "logic", "direction": "In"}
                         ]}},
                    ],
                }},
            ],
        }},
    ]}}


def test_build_hierarchy_from_slang_ast_maps_instance_port_expressions():
    from wengold.rtl_hierarchy import build_hierarchy_from_slang_ast
    graph = build_hierarchy_from_slang_ast(sample_slang_ast(), top="top")
    assert [node["id"] for node in graph["nodes"]] == [
        "top", "top.u_sub", "top.u_sub.u_leaf"]
    assert graph["nodes"][1]["module"] == "sub"
    assert graph["connection_unit"] == "port connections"
    assert graph["connection_count"] == 3
    assert graph["edges"][0]["from"] == "top.clk"
    assert graph["edges"][0]["to"] == "top.u_sub.clk_i"
    assert graph["edges"][2]["from"] == "top.data_bus"
    assert graph["edges"][2]["width"] == 64


def test_slang_ast_requires_selected_top():
    import pytest
    from wengold.rtl_hierarchy import build_hierarchy_from_slang_ast
    with pytest.raises(ValueError, match="Top instance"):
        build_hierarchy_from_slang_ast(sample_slang_ast(), top="missing")


def test_slang_ast_expansion_limit_is_reported():
    from wengold.rtl_hierarchy import build_hierarchy_from_slang_ast
    graph = build_hierarchy_from_slang_ast(
        sample_slang_ast(), top="top", max_instances=1)
    assert graph["instance_count"] == 1
    assert graph["truncated"] is True


def test_slang_ast_cli_exports_elaborated_json(tmp_path, monkeypatch):
    import json
    from wengold import rtl_hierarchy

    source = tmp_path / "top.sv"
    source.write_text("module top(input logic clk); endmodule")
    ast_doc = {"design": {"kind": "Root", "members": [{
        "kind": "Instance", "name": "top",
        "body": {"kind": "InstanceBody", "name": "top", "members": [
            {"kind": "Port", "name": "clk", "type": "logic", "direction": "In"}
        ]},
    }]}}
    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command
        output = tmp_path / ".wengold" / "slang_ast.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(ast_doc))
        class Result:
            returncode = 0
            stdout = "Slang AST ok"
            stderr = ""
        return Result()

    monkeypatch.setattr(rtl_hierarchy.shutil, "which", lambda _name: "/usr/bin/slang")
    monkeypatch.setattr(rtl_hierarchy.subprocess, "run", fake_run)
    graph = rtl_hierarchy.elaborate_with_slang_ast(
        tmp_path, [source], top="top")
    assert graph["frontend"] == "Slang CLI elaborated AST JSON"
    assert "--ast-json-source-info" in calls["command"]
    assert calls["command"][calls["command"].index("--max-loop-analysis-steps") + 1] == "0"


def test_crossprobe_uses_only_exact_parent_net_alias_when_child_port_is_not_dumped():
    from wengold.rtl_hierarchy import crossprobe_hierarchy_to_vcd
    graph = {
        "top": "top",
        "nodes": [{"id": "top", "module": "top", "ports": []},
                  {"id": "top.u_sub", "module": "sub", "ports": [
                      {"name": "data_i", "direction": "input", "width": 32}]}],
        "edges": [{"instance": "top.u_sub", "port": "data_i",
                   "from": "top.data_bus", "to": "top.u_sub.data_i",
                   "parent_symbol": "data_bus", "expression_kind": "NamedValue"}],
    }
    wave = {"signals": [{"name": "tb.dut.data_bus"}]}
    result = crossprobe_hierarchy_to_vcd(
        graph, wave, vcd_root="tb", dut_instance="dut")
    assert result["direct_matches"] == 0
    assert result["parent_net_alias_matches"] == 1
    assert result["matched_ports"] == 1
    assert result["unmatched_ports"] == 0
    alias = result["parent_net_alias_records"][0]
    assert alias["match_kind"] == "exact_parent_net_alias"
    assert alias["matched_vcd_path"] == "tb.dut.data_bus"


def test_crossprobe_does_not_guess_parent_alias_without_exact_vcd_signal():
    from wengold.rtl_hierarchy import crossprobe_hierarchy_to_vcd
    graph = {
        "top": "top",
        "nodes": [{"id": "top.u_sub", "module": "sub", "ports": [
            {"name": "data_i", "direction": "input", "width": 32}]}],
        "edges": [{"instance": "top.u_sub", "port": "data_i",
                   "from": "top.data_bus", "to": "top.u_sub.data_i",
                   "parent_symbol": "data_bus", "expression_kind": "NamedValue"}],
    }
    result = crossprobe_hierarchy_to_vcd(
        graph, {"signals": [{"name": "tb.dut.other_bus"}]},
        vcd_root="tb", dut_instance="dut")
    assert result["matched_ports"] == 0
    assert result["unmatched_ports"] == 1
    assert result["status"] == "no_exact_matches"
