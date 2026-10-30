"""The VHDL path: GHDL, its library name, and the C compiler it needs.

Two things this had to get right, both found by running it against neorv32's real
54-unit filelist rather than a fixture:

**The library name.** neorv32's sources say `library neorv32;`, so its units must
be analysed into a library of that name with that directory on the search path.
Analysing everything into `work` gave **49 failures out of 54** with "cannot find
resource library 'neorv32'" — the sources were fine and the invocation was wrong.

**The C compiler.** GHDL's LLVM backend refuses to start without `cc`. On a machine
with no compiler that reads as "GHDL is broken", so it is reported as `tool_missing`
with the fix named.

With both fixed, neorv32 analyses 54 of 54 units cleanly.
"""
import os
import stat
from pathlib import Path

import pytest

from wengold.agent.runners import ToolRunner, Toolchain
from wengold.graph.builder import GraphBuilder
from wengold.kernel.validity import Result

VHD = """library neorv32;
use neorv32.neorv32_package.all;

entity {name} is
  port (c : in bit; q : out bit);
end entity;
"""

VHD_PLAIN = """entity {name} is
  port (c : in bit; q : out bit);
end entity;
"""


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


def fake(directory, name, body):
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return directory


def capture(directory, name, outfile):
    """A fake tool that records its argv, so the invocation can be asserted."""
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / name
    p.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {outfile}\nexit 0\n')
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return directory


# ---- the library name ----------------------------------------------------
def test_the_library_name_comes_from_the_sources(tmp_path):
    """`library neorv32;` means units go into a library called neorv32."""
    g, res = build(tmp_path, {"rtl/core.vhd": VHD.format(name="core")})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    design, _ = tr.ordered_files("vhdl")
    assert tr._vhdl_library(design) == "neorv32"


def test_ieee_and_work_are_not_taken_as_the_library(tmp_path):
    src = "library ieee;\nlibrary work;\nentity c is end entity;\n"
    g, res = build(tmp_path, {"c.vhd": src})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    assert tr._vhdl_library(tr.ordered_files("vhdl")[0]) == "work"


def test_a_project_without_a_library_declaration_defaults_to_work(tmp_path):
    g, res = build(tmp_path, {"c.vhd": VHD_PLAIN.format(name="c")})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    assert tr._vhdl_library(tr.ordered_files("vhdl")[0]) == "work"


# ---- the invocation ------------------------------------------------------
def test_ghdl_is_given_the_library_and_the_search_path(tmp_path):
    argvfile = tmp_path / "argv.txt"
    bin_ = capture(tmp_path / "bin", "ghdl", argvfile)
    g, res = build(tmp_path / "proj",
                   {"rtl/core.vhd": VHD.format(name="core")})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    tr(next(iter(res)), "sim")
    argv = argvfile.read_text()
    assert "--work=neorv32" in argv, argv
    assert "-P" in argv, argv
    assert "--std=08" in argv


def test_ghdl_analyses_one_file_at_a_time_in_order(tmp_path):
    """`ghdl -a` takes one unit; order matters and the filelist supplies it."""
    argvfile = tmp_path / "argv.txt"
    bin_ = capture(tmp_path / "bin", "ghdl", argvfile)
    files = {"rtl/z.vhd": VHD_PLAIN.format(name="z"),
             "rtl/a.vhd": VHD_PLAIN.format(name="a"),
             "rtl/core.f": "rtl/z.vhd\nrtl/a.vhd\n"}
    g, res = build(tmp_path / "proj", files)
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    tr(next(iter(res)), "sim")
    # the fake records only the last call; the order is asserted on ordered_files
    design, source = tr.ordered_files("vhdl")
    assert source == "filelist"
    assert [Path(p).name for p in design] == ["z.vhd", "a.vhd"]


# ---- outcomes ------------------------------------------------------------
def test_ghdl_missing_is_tool_missing(tmp_path):
    g, res = build(tmp_path, {"core.vhd": VHD_PLAIN.format(name="core")})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    rec = tr(next(iter(res)), "sim")
    assert rec["tool"] == "ghdl"
    assert rec["outcome"] == "tool_missing"


def test_a_clean_analysis_is_inconclusive_not_a_pass(tmp_path):
    """Analysing proves the design compiles. It does not prove the property."""
    bin_ = fake(tmp_path / "bin", "ghdl", "exit 0")
    g, res = build(tmp_path / "proj",
                   {"core.vhd": VHD_PLAIN.format(name="core")})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "inconclusive"
    assert "compiles" in rec["note"]


def test_a_missing_c_compiler_names_the_fix(tmp_path):
    """`cc not found` reads as 'GHDL is broken'. It is a missing build tool."""
    bin_ = fake(tmp_path / "bin", "ghdl",
                'echo "ghdl:error: installation problem: cc not found" >&2\nexit 1')
    g, res = build(tmp_path / "proj",
                   {"core.vhd": VHD_PLAIN.format(name="core")})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "tool_missing"
    assert "cc-shim" in rec["note"], rec["note"]


def test_a_real_analysis_error_is_a_fail(tmp_path):
    bin_ = fake(tmp_path / "bin", "ghdl",
                'echo "core.vhd:3:5:error: unexpected token" >&2\nexit 1')
    g, res = build(tmp_path / "proj",
                   {"core.vhd": VHD_PLAIN.format(name="core")})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "fail"


# ---- against the real GHDL, when it can run -----------------------------
REAL = Toolchain()
can_run = REAL.has("ghdl")


@pytest.mark.skipif(not can_run, reason="ghdl not installed")
def test_real_ghdl_analyses_a_package_and_a_user_of_it(tmp_path):
    """The exact shape that failed: a package in a named library, then a user."""
    pkg = ("package p is\n  constant W : integer := 8;\nend package;\n"
           "package body p is\nend package body;\n")
    user = ("library neorv32;\nuse neorv32.p.all;\n"
            "entity u is port (c : in bit; q : out bit); end entity;\n")
    files = {"rtl/p.vhd": pkg, "rtl/u.vhd": user,
             "rtl/core.f": "rtl/p.vhd\nrtl/u.vhd\n"}
    g, res = build(tmp_path / "proj", files)
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=REAL)
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "inconclusive", rec["log"][:400]
