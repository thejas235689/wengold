"""Filelists and language routing.

Two things the sweep proved the hard way:

**File order cannot be guessed.** Verilator rejects a design read out of the order
the project intends ("picosoc.v must be read before picorv32.v"), and reordering
picorv32's files by hand still left 28 errors. Only the project's own `.f` is
correct, so when there is no filelist the honest answer is `inconclusive`.

**A VHDL core is not a Verilator problem.** neorv32 is 54 `.vhd` files plus nine
Verilog vendor models; handing it to a SystemVerilog linter produced a wall of
syntax errors that read as broken RTL.
"""
import os
from pathlib import Path

import pytest

from wengold.agent.runners import ToolRunner, Toolchain, parse_filelist
from wengold.graph.builder import GraphBuilder
from wengold.kernel.validity import Result

SV = """module {name}(input logic c, output logic q);
  assign q = c;
endmodule
"""

VHD = """entity {name} is
  port (c : in bit; q : out bit);
end entity;
"""


# ---- filelist parsing ----------------------------------------------------
def test_a_filelist_keeps_the_projects_order():
    """Order is the whole reason to read one."""
    text = "$H/z.v\n$H/a.v\n$H/m.v\n"
    out = parse_filelist(text, Path("/base"), {"H": "/proj"})
    assert [Path(p).name for p in out] == ["z.v", "a.v", "m.v"]


def test_comments_and_blank_lines_are_dropped():
    text = "\n".join(["// a comment", "", "# hash comment",
                      "$H/a.v   // trailing", "$H/b.v"])
    out = parse_filelist(text, Path("/base"), {"H": "/proj"})
    assert [Path(p).name for p in out] == ["a.v", "b.v"]


def test_incdir_and_define_flags_are_not_files():
    text = "+incdir+/x/y\n+define+FOO=1\n$H/a.v\n"
    out = parse_filelist(text, Path("/base"), {"H": "/proj"})
    assert len(out) == 1 and out[0].endswith("a.v")


def test_a_variable_is_expanded():
    out = parse_filelist("$HOME/rtl/a.vhd\n", Path("/base"), {"HOME": "/proj"})
    assert out == ["/proj/rtl/a.vhd"]


def test_an_unexpanded_variable_is_skipped_not_guessed():
    """A path we cannot resolve must not become a path we invent."""
    out = parse_filelist("$UNSET/a.v\n$H/ok.v\n", Path("/base"), {"H": "/p"})
    assert out == ["/p/ok.v"]


def test_a_relative_entry_is_resolved_against_the_filelist():
    out = parse_filelist("rtl/a.v\n", Path("/proj"), {})
    assert out == ["/proj/rtl/a.v"]


def test_an_absolute_entry_is_left_alone():
    out = parse_filelist("/abs/d.v\n", Path("/proj"), {})
    assert out == ["/abs/d.v"]


def test_a_quoted_path_is_unquoted():
    out = parse_filelist('"/abs/with space/a.v"\n', Path("/p"), {})
    assert out == ["/abs/with space/a.v"]


# ---- discovery and ordering ---------------------------------------------
def build(tmp_path, files):
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    g = GraphBuilder().build_from_files(
        {str(tmp_path / n): t for n, t in files.items()}, backend="auto")
    results = {f"{b}_sim": Result(f"{b}_sim", "sim", depends_on={b})
               for b in g.nodes if not b.startswith(("file:", "param."))}
    return g, results


def test_a_shipped_filelist_is_found_and_used(tmp_path):
    files = {"rtl/a.sv": SV.format(name="a"), "rtl/b.sv": SV.format(name="b"),
             "rtl/core.f": "rtl/b.sv\nrtl/a.sv\n"}
    g, res = build(tmp_path, files)
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    assert tr.filelist is not None
    ordered, source = tr.ordered_files("verilog")
    assert source == "filelist"
    assert [Path(p).name for p in ordered] == ["b.sv", "a.sv"], \
        "the filelist order was not preserved"


def test_without_a_filelist_the_source_says_sorted(tmp_path):
    g, res = build(tmp_path, {"a.sv": SV.format(name="a")})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    _, source = tr.ordered_files("verilog")
    assert source == "sorted"


def test_the_filelist_is_filtered_by_language(tmp_path):
    files = {"rtl/a.sv": SV.format(name="a"), "rtl/b.vhd": VHD.format(name="b"),
             "rtl/core.f": "rtl/a.sv\nrtl/b.vhd\n"}
    g, res = build(tmp_path, files)
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    v, _ = tr.ordered_files("verilog")
    h, _ = tr.ordered_files("vhdl")
    assert [Path(p).name for p in v] == ["a.sv"]
    assert [Path(p).name for p in h] == ["b.vhd"]


# ---- language routing ----------------------------------------------------
def test_a_vhdl_core_routes_to_ghdl(tmp_path):
    """neorv32 is VHDL with a few Verilog models; counting files got it wrong."""
    # a clear majority, which is the neorv32 shape: 54 VHDL units, 9 Verilog models
    g, res = build(tmp_path, {"rtl/core.vhd": VHD.format(name="core"),
                              "rtl/cpu.vhd": VHD.format(name="cpu"),
                              "model/vendor.v": SV.format(name="vendor")})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    assert tr.dominant_language() == "vhdl"


def test_a_verilog_core_with_some_vhdl_routes_to_verilator(tmp_path):
    g, res = build(tmp_path, {"rtl/a.sv": SV.format(name="a"),
                              "rtl/b.sv": SV.format(name="b"),
                              "rtl/c.vhd": VHD.format(name="c")})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    assert tr.dominant_language() == "verilog"


def test_ghdl_absent_is_tool_missing_not_a_failure(tmp_path):
    g, res = build(tmp_path, {"core.vhd": VHD.format(name="core")})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    rec = tr(next(iter(res)), "sim")
    assert rec["tool"] == "ghdl"
    assert rec["outcome"] == "tool_missing"
    assert rec["outcome"] != "pass"


# ---- the outcome still refuses to over-claim ----------------------------
def test_a_rejected_file_list_is_inconclusive(tmp_path):
    """No filelist, sorted order — Verilator may reject it, and that is our fault."""
    import stat
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    tool = bin_ / "verilator"
    tool.write_text('#!/bin/sh\necho "%Error: b.sv must be read before a.sv!" >&2\n'
                    'exit 1\n')
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    g, res = build(tmp_path / "proj", {"a.sv": SV.format(name="a")})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "inconclusive"
    assert "file list" in rec["note"]
