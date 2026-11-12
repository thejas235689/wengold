"""Fail-closed handling of SystemVerilog package imports in formal CLI.

Package-aware proof is NOT yet supported by the bounded in-process frontend.
This test prevents a misleading inconclusive result that looks like a run.
"""
from argparse import Namespace

from wengold.cli import cmd_formal


def test_package_using_rtl_reports_actionable_refusal(tmp_path, capsys):
    rtl = tmp_path / "rv64_alu.sv"
    rtl.write_text(
        "module rv64_alu(input logic clk, input logic a, output logic q);\n"
        "  import rv64_pkg::*;\n"
        "  assign q = a;\n"
        "endmodule\n")
    result = cmd_formal(Namespace(
        file=str(rtl), property=["1'b1"], clock="clk", reset=None,
        engine="auto", depth=12, budget=3, sva=False))
    assert result == 2
    out = capsys.readouterr().out
    assert "package imports" in out
    assert "pkg::*" in out
    assert "externally elaborated" in out
    assert "Traceback" not in out
