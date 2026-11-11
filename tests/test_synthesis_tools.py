"""Standalone synthesis/PPA integration tests: no synthetic signoff claims."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from wengold.synthesis_tools import run_synthesis


def test_synthesis_requires_real_yosys(tmp_path, monkeypatch):
    src = tmp_path / "simple.sv"
    src.write_text("module simple(input wire a, output wire b); assign b=a; endmodule")
    monkeypatch.setattr("wengold.synthesis_tools.shutil.which", lambda tool: None)
    result = run_synthesis(tmp_path, "simple.sv")
    assert result["status"] == "unavailable" and not result["ok"]
    assert "Yosys" in result["message"]


def test_real_tool_json_is_required_for_cell_metrics(tmp_path, monkeypatch):
    import json
    from wengold import synthesis_tools
    (tmp_path / "simple.v").write_text("module simple; endmodule")
    monkeypatch.setattr(synthesis_tools.shutil, "which", lambda name: "/usr/bin/yosys")
    def pretend_tool(args, **kwargs):
        assert args[:3] == ["/usr/bin/yosys", "-Q", "-T"]
        netlist = {
            "modules": {"simple": {
                "cells": {"cell_1": {"type": "$_NOT_"},
                          "cell_2": {"type": "$_AND_"}},
                "netnames": {"a": {}, "b": {}},
                "ports": {"in": {}, "out": {}}}}
        }
        (Path(kwargs["cwd"]) / "netlist.json").write_text(json.dumps(netlist))
        return SimpleNamespace(returncode=0, stdout="Yosys report", stderr="")
    monkeypatch.setattr(synthesis_tools.subprocess, "run", pretend_tool)
    report = run_synthesis(tmp_path, "simple.v", "simple")
    assert report["ok"] and report["status"] == "synthesized_generic_netlist"
    assert report["total_cells"] == 2
    assert report["total_wire_names"] == 2
    assert report["cell_types"]["$_AND_"] == 1
    assert "NOT AVAILABLE" in report["chip_area"]
    assert report["timing"].startswith("NOT RUN")
    assert len(report["netlist_sha256"]) == 64


def test_yosys_failure_cannot_be_misreported(tmp_path, monkeypatch):
    from wengold import synthesis_tools
    (tmp_path / "simple.v").write_text("module simple; endmodule")
    monkeypatch.setattr(synthesis_tools.shutil, "which", lambda name: "/usr/bin/yosys")
    monkeypatch.setattr(synthesis_tools.subprocess, "run",
                        lambda *_a, **_k: SimpleNamespace(
                            returncode=1, stdout="", stderr="ERROR: bad source"))
    result = run_synthesis(tmp_path, "simple.v")
    assert not result["ok"] and result["status"] == "failed"
    assert "ERROR" in result["log"]


def test_synthesis_restricts_source_and_top(tmp_path):
    (tmp_path / "x.sv").write_text("module x; endmodule")
    with pytest.raises(ValueError):
        run_synthesis(tmp_path, "x.sv", "x; shell")
    with pytest.raises(Exception):
        run_synthesis(tmp_path, "../x.sv")


@pytest.mark.skipif(__import__("shutil").which("yosys") is None,
                    reason="Yosys executable not installed")
def test_real_yosys_synthesizes_a_small_counter(tmp_path):
    (tmp_path / "counter.v").write_text(
        "module counter(input clk, rst_n, output reg [3:0] count);\n"
        "always @(posedge clk or negedge rst_n)\n"
        "if (!rst_n) count <= 0; else count <= count + 1;\n"
        "endmodule\n")
    result = run_synthesis(tmp_path, "counter.v", "counter")
    assert result["ok"], result.get("log")
    assert result["total_cells"] > 0
    assert any(m["name"] == "counter" for m in result["modules"])
    assert result["timing"].startswith("NOT RUN")
    assert result["chip_area"].startswith("NOT AVAILABLE")


def test_liberty_mapping_and_opensta_use_real_logs_and_inputs(tmp_path, monkeypatch):
    import json
    from wengold import synthesis_tools
    (tmp_path / "x.sv").write_text("module x; endmodule")
    (tmp_path / "cells.lib").write_text("library (test) {}")
    (tmp_path / "timing.sdc").write_text("create_clock -period 10 [get_ports clk]")
    monkeypatch.setattr(synthesis_tools.shutil, "which",
                        lambda name: "/usr/bin/" + name if name in ("yosys", "sta") else None)
    seen = []
    def fake_run(argv, **kwargs):
        work = Path(kwargs["cwd"])
        seen.append(list(argv))
        if argv[0].endswith("yosys"):
            assert "abc -liberty cells.lib" in (work / "run.ys").read_text()
            (work / "netlist.json").write_text(json.dumps({
                "modules": {"x": {"cells": {}, "netnames": {}, "ports": {}}}}))
            (work / "mapped.v").write_text("module x; endmodule")
            return SimpleNamespace(returncode=0,
                stdout="Chip area for module \\x: 12.5", stderr="")
        assert argv[0].endswith("sta")
        tcl = (work / "timing.tcl").read_text()
        assert "read_sdc constraints.sdc" in tcl
        assert "report_checks" in tcl
        assert "read_liberty cells.lib" in tcl
        return SimpleNamespace(returncode=0, stdout="wns 0.2", stderr="")
    monkeypatch.setattr(synthesis_tools.subprocess, "run", fake_run)
    result = run_synthesis(tmp_path, "x.sv", "x", "cells.lib", "timing.sdc")
    assert len(seen) == 2
    assert result["mapping"] == "liberty"
    assert result["mapped_cell_area"] == 12.5
    assert "12.5" in result["chip_area"]
    assert result["sta_evidence"]["status"] == "tool_completed"
    assert result["sta_evidence"]["log"].startswith("wns")
    assert len(result["sta_evidence"]["sdc_sha256"]) == 64
    assert "not signoff" in result["sta_evidence"]["qualification"]


def test_sta_refuses_missing_constraints_and_mapping(tmp_path):
    (tmp_path / "x.sv").write_text("module x; endmodule")
    (tmp_path / "timing.sdc").write_text("create_clock -period 10 [get_ports clk]")
    with pytest.raises(ValueError):
        run_synthesis(tmp_path, "x.sv", "x", "", "timing.sdc")
