"""The real runner — acting on tools instead of on a model of tools.

`SimulatedRunner` settles every check it is handed and says so in its own
docstring. This module's tests are mostly about the opposite: **what the runner
refuses to claim**.

The central case is a lint pass. Verilator reporting a clean lint means the design
elaborates; it does not mean the property holds. A runner that returned `pass`
there would be inventing the answer this whole project exists to avoid, so
`inconclusive` is asserted explicitly.
"""
import os
import stat
import sys
from pathlib import Path

import pytest

from wengold.agent.runners import ToolRunner, Toolchain
from wengold.graph.builder import GraphBuilder
from wengold.kernel.validity import Result

HDL = """module {name}(input logic c, output logic q);
  assign q = c;
endmodule
"""

BROKEN = """module {name}(input logic c, output logic q);
  assign q = & ;
endmodule
"""


def build(tmp_path, files):
    for name, text in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    g = GraphBuilder().build_from_files(
        {str(tmp_path / n): text for n, text in files.items()}, backend="auto")
    results = {f"{b}_sim": Result(f"{b}_sim", "sim", depends_on={b})
               for b in g.nodes if not b.startswith(("file:", "param."))}
    return g, results


def fake_tool(directory, name, body):
    """A stand-in executable, so the outcome mapping is tested without a 700 MB
    toolchain and without depending on a simulator's exact wording."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return directory


# ---- the toolchain probe ------------------------------------------------
def test_a_missing_toolchain_reports_every_name():
    # `extra_path` extends PATH rather than replacing it, so a bogus directory is
    # not enough to simulate absence on a machine that has the tools.
    tc = Toolchain.empty()
    assert tc.found == {}
    assert set(tc.missing()) == set(Toolchain.NAMES)
    assert "no simulator" in tc.describe()


def test_extra_path_is_searched(tmp_path):
    fake_tool(tmp_path, "verilator", "exit 0")
    tc = Toolchain(str(tmp_path))
    assert tc.has("verilator")


# ---- the outcome mapping ------------------------------------------------
def test_a_clean_lint_is_inconclusive_not_a_pass(tmp_path):
    """The whole point. Linting clean proves elaboration, not the property."""
    tool = fake_tool(tmp_path / "bin", "verilator", "exit 0")
    g, results = build(tmp_path / "proj", {"a.sv": HDL.format(name="a")})
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=Toolchain(str(tool)))
    rec = r(next(iter(results)), "sim")
    assert rec["outcome"] == "inconclusive"
    assert "elaborates" in rec["note"]


def test_an_elaboration_error_is_a_real_fail(tmp_path):
    tool = fake_tool(tmp_path / "bin", "verilator",
                     'echo "%Error: syntax" >&2\nexit 1')
    g, results = build(tmp_path / "proj", {"a.sv": HDL.format(name="a")})
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=Toolchain(str(tool)))
    rec = r(next(iter(results)), "sim")
    assert rec["outcome"] == "fail"
    assert rec["rc"] == 1


def test_a_missing_tool_is_never_a_pass(tmp_path):
    g, results = build(tmp_path / "proj", {"a.sv": HDL.format(name="a")})
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=Toolchain.empty())
    rec = r(next(iter(results)), "sim")
    assert rec["outcome"] == "tool_missing"
    assert rec["outcome"] != "pass"


def test_a_kind_no_tool_answers_is_inconclusive(tmp_path):
    tool = fake_tool(tmp_path / "bin", "verilator", "exit 0")
    g, results = build(tmp_path / "proj", {"a.sv": HDL.format(name="a")})
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=Toolchain(str(tool)))
    rec = r(next(iter(results)), "coverage")
    assert rec["outcome"] == "inconclusive"
    assert "no installed tool" in rec["note"]


def test_a_result_with_no_file_is_inconclusive(tmp_path):
    tool = fake_tool(tmp_path / "bin", "verilator", "exit 0")
    g, results = build(tmp_path / "proj", {"a.sv": HDL.format(name="a")})
    results["ghost"] = Result("ghost", "sim", depends_on={"not_a_node"})
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=Toolchain(str(tool)))
    assert r("ghost", "sim")["outcome"] == "inconclusive"


def test_a_timeout_is_inconclusive_not_a_fail(tmp_path):
    """A hung tool has not told us the design is wrong."""
    tool = fake_tool(tmp_path / "bin", "verilator", "sleep 30")
    g, results = build(tmp_path / "proj", {"a.sv": HDL.format(name="a")})
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=Toolchain(str(tool)),
                   timeout=1)
    rec = r(next(iter(results)), "sim")
    assert rec["outcome"] == "inconclusive"
    assert rec["rc"] == 124


# ---- file resolution ----------------------------------------------------
def test_paths_handed_to_the_tool_are_absolute_and_exist(tmp_path):
    """A relative path plus cwd=root double-prefixes and reads as a design error."""
    tool = fake_tool(tmp_path / "bin", "verilator", "exit 0")
    g, results = build(tmp_path / "proj", {"sub/a.sv": HDL.format(name="a")})
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=Toolchain(str(tool)))
    files = r.project_files()
    assert files, "no design files found"
    for f in files:
        assert os.path.isabs(f)
        assert Path(f).exists()


def test_elaboration_sees_the_whole_design_not_one_file(tmp_path):
    """`soc_top` instantiates `dma`. Linting soc_top alone reports a missing module
    and blames the RTL for the runner's own incomplete file list."""
    tool = fake_tool(tmp_path / "bin", "verilator", "exit 0")
    g, results = build(tmp_path / "proj", {
        "dma.sv": HDL.format(name="dma"),
        "top.sv": "module top(input logic c, output logic q);\n"
                  "  dma u(.c(c), .q(q));\nendmodule\n",
    })
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=Toolchain(str(tool)))
    assert len(r.project_files()) == 2


# ---- the record ---------------------------------------------------------
def test_the_outcome_records_what_it_ran(tmp_path):
    tool = fake_tool(tmp_path / "bin", "verilator", "exit 0")
    g, results = build(tmp_path / "proj", {"a.sv": HDL.format(name="a")})
    seen = []
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=Toolchain(str(tool)),
                   on_step=seen.append)
    rec = r(next(iter(results)), "sim")
    assert seen and seen[0]["result"] == rec["result"]
    for key in ("result", "tool", "outcome", "rc", "kind", "secs"):
        assert key in rec


# ---- against the real tools, when they are installed -------------------
REAL = Toolchain()
has_verilator = pytest.mark.skipif(not REAL.has("verilator"),
                                   reason="verilator not installed")


@has_verilator
def test_real_verilator_accepts_a_good_module(tmp_path):
    g, results = build(tmp_path / "proj", {"a.sv": HDL.format(name="a")})
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=REAL)
    assert r(next(iter(results)), "sim")["outcome"] == "inconclusive"


@has_verilator
def test_real_verilator_rejects_a_broken_module(tmp_path):
    g, results = build(tmp_path / "proj", {"b.sv": BROKEN.format(name="b")})
    r = ToolRunner(g, results, tmp_path / "proj", toolchain=REAL)
    rec = r(next(iter(results)), "sim")
    assert rec["outcome"] == "fail", rec["log"][:300]
