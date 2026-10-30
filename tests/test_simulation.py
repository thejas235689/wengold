"""Simulation: the only check that can settle a result as PASSING.

Everything before this could only ever report `inconclusive` or `fail`. Linting
proves a design compiles; analysing VHDL proves it compiles. Neither proves the
property holds, so neither may settle a check as passed.

A simulation with a self-checking testbench is different: the assertions either
fired or they did not. That is a real check, and it is the first thing in this
project that produces a non-zero settled count.

The guard that matters: **a testbench with no assertions proves nothing.** neorv32
ships `neorv32_tb.vhd` with zero assertions — it loads an external program — so
running it must not settle anything. A runner that treated "ran to completion" as
a pass would report every design as verified.
"""
import stat
from pathlib import Path

import pytest

from wengold.agent.runners import ToolRunner, Toolchain
from wengold.graph.builder import GraphBuilder
from wengold.kernel.validity import Result

SV = """module {name}(input logic c, output logic q);
  assign q = c;
endmodule
"""

TB_ASSERT = """module tb;
  initial begin
    if (1 !== 1) $fatal(1, "boom");
    $finish;
  end
endmodule
"""

TB_NO_ASSERT = """module tb;
  initial begin
    $display("ran");
    $finish;
  end
endmodule
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


# ---- finding a testbench -------------------------------------------------
def test_a_testbench_is_found(tmp_path):
    g, res = build(tmp_path, {"a.sv": SV.format(name="a"),
                              "counter_tb.sv": TB_ASSERT})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    tb, has = tr.testbench()
    assert tb and tb.endswith("counter_tb.sv")
    assert has is True


def test_a_testbench_with_no_assertions_is_flagged(tmp_path):
    """neorv32's tb is exactly this shape and must not settle anything."""
    g, res = build(tmp_path, {"a.sv": SV.format(name="a"),
                              "counter_tb.sv": TB_NO_ASSERT})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    tb, has = tr.testbench()
    assert tb and has is False


def test_no_testbench_means_nothing_to_run(tmp_path):
    g, res = build(tmp_path, {"a.sv": SV.format(name="a")})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    assert tr.testbench() == (None, False)


@pytest.mark.parametrize("marker", ["assert x = 1", "$fatal(1, \"x\")",
                                    "$error(\"x\")"])
def test_assertion_markers_are_recognised(tmp_path, marker):
    """A Verilog testbench usually says $fatal inside an `if`; matching only the
    word "assert" classified a working testbench as uncheckable."""
    g, res = build(tmp_path, {"a.sv": SV.format(name="a"),
                              "x_tb.sv": f"module tb;\ninitial begin {marker}; end\nendmodule\n"})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    _, has = tr.testbench()
    assert has is True


# ---- outcomes ------------------------------------------------------------
def test_no_testbench_is_inconclusive(tmp_path):
    g, res = build(tmp_path, {"a.sv": SV.format(name="a")})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "inconclusive"
    assert "no testbench" in rec["note"]


def test_an_unasserted_testbench_is_inconclusive(tmp_path):
    """The guard that stops 'it ran' becoming 'it passed'."""
    bin_ = fake(tmp_path / "bin", "iverilog", "exit 0")
    fake(bin_, "vvp", "exit 0")
    g, res = build(tmp_path / "proj", {"a.sv": SV.format(name="a"),
                                       "t_tb.sv": TB_NO_ASSERT})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "inconclusive"
    assert "no assertions" in rec["note"]
    assert rec["outcome"] != "pass"


def test_a_clean_simulation_is_a_pass(tmp_path):
    """The one path that may settle as passing."""
    bin_ = fake(tmp_path / "bin", "iverilog", "exit 0")
    fake(bin_, "vvp", "exit 0")
    g, res = build(tmp_path / "proj", {"a.sv": SV.format(name="a"),
                                       "t_tb.sv": TB_ASSERT})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "pass"
    assert rec["tool"] == "iverilog"


def test_a_fired_assertion_is_a_fail(tmp_path):
    bin_ = fake(tmp_path / "bin", "iverilog", "exit 0")
    fake(bin_, "vvp", 'echo "FATAL: expected 2, got 4" >&2\nexit 1')
    g, res = build(tmp_path / "proj", {"a.sv": SV.format(name="a"),
                                       "t_tb.sv": TB_ASSERT})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "fail"


def test_a_missing_simulator_is_tool_missing(tmp_path):
    g, res = build(tmp_path, {"a.sv": SV.format(name="a"),
                              "t_tb.sv": TB_ASSERT})
    tr = ToolRunner(g, res, tmp_path, toolchain=Toolchain.empty())
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "tool_missing"
    assert rec["outcome"] != "pass"


def test_a_compile_error_is_not_a_pass(tmp_path):
    bin_ = fake(tmp_path / "bin", "iverilog", 'echo "syntax error" >&2\nexit 1')
    fake(bin_, "vvp", "exit 0")
    g, res = build(tmp_path / "proj", {"a.sv": SV.format(name="a"),
                                       "t_tb.sv": TB_ASSERT})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] != "pass"


def test_the_vhdl_elaboration_limit_is_explained(tmp_path):
    """GHDL's LLVM backend needs a working linker; analysis works, simulation may
    not. That is an environment limit and must read as one."""
    bin_ = fake(tmp_path / "bin", "ghdl",
                'echo "error: unable to find dynamic system library \\"z\\"" >&2\n'
                'exit 1')
    g, res = build(tmp_path / "proj", {"a.vhd": "entity a is end entity;\n",
                                       "a_tb.vhd": "entity a_tb is end entity;\n"
                                                   "architecture s of a_tb is begin\n"
                                                   "  assert true report \"x\";\n"
                                                   "end architecture;\n"})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=Toolchain(str(bin_)))
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "inconclusive"
    assert "linker" in rec["note"], rec["note"]


# ---- against the real tools ---------------------------------------------
REAL = Toolchain()
has_sim = REAL.has("iverilog") and REAL.has("vvp")

COUNTER = """module counter(input logic clk, input logic rst_n, output logic [3:0] q);
  always_ff @(posedge clk) if (!rst_n) q <= 4'd0; else q <= q + 4'd1;
endmodule
"""

COUNTER_TB = """module counter_tb;
  logic clk = 0, rst_n = 0;
  logic [3:0] q;
  counter dut(.clk(clk), .rst_n(rst_n), .q(q));
  always #5 clk = ~clk;
  initial begin
    repeat(2) @(posedge clk);
    rst_n = 1;
    @(posedge clk); @(posedge clk);
    #1;
    if (q !== 4'd2) $fatal(1, "expected 2, got %0d", q);
    $finish;
  end
endmodule
"""


@pytest.mark.skipif(not has_sim, reason="iverilog/vvp not installed")
def test_real_simulation_passes_a_correct_counter(tmp_path):
    g, res = build(tmp_path / "proj", {"counter.sv": COUNTER,
                                       "counter_tb.sv": COUNTER_TB})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=REAL)
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "pass", rec["log"][-500:]


@pytest.mark.skipif(not has_sim, reason="iverilog/vvp not installed")
def test_real_simulation_fails_a_wrong_counter(tmp_path):
    broken = COUNTER.replace("q + 4'd1", "q + 4'd2")
    g, res = build(tmp_path / "proj", {"counter.sv": broken,
                                       "counter_tb.sv": COUNTER_TB})
    tr = ToolRunner(g, res, tmp_path / "proj", toolchain=REAL)
    rec = tr(next(iter(res)), "sim")
    assert rec["outcome"] == "fail", rec["log"][-500:]
