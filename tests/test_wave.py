"""Waveforms.

Two sources, both real: the counterexample the formal engine computes, and a
simulator's VCD. The tests that matter are the ones asserting we do *not* draw a
waveform when there is nothing to draw — an invented waveform would be worse than
none.
"""
import pytest

from wengold.wave import from_formal, from_trace, parse_vcd

VCD = """$timescale 1ns $end
$scope module top $end
$var wire 1 ! clk $end
$var wire 1 " en $end
$var wire 4 # count $end
$upscope $end
$enddefinitions $end
#0
0!
0"
b0000 #
#5
1!
1"
b0001 #
#10
0!
1"
b0010 #
#15
1!
0"
b0010 #
"""


# ---- from a trace ----------------------------------------------------------
def test_a_trace_becomes_signals_with_widths():
    trace = [{"count": 0}, {"inputs": {"en": 1}, "state": {"count": 1, "en": 1}},
             {"inputs": {"en": 1}, "state": {"count": 2, "en": 1}}]
    w = from_trace(trace, {"count": 4, "en": 1}, source="test")
    assert w["cycles"] == 3
    names = [s["name"] for s in w["signals"]]
    assert names == ["count", "en"]                 # alphabetical, stable
    count = next(s for s in w["signals"] if s["name"] == "count")
    assert count["width"] == 4
    assert count["values"] == [0, 1, 2]
    en = next(s for s in w["signals"] if s["name"] == "en")
    # cycle 0 has no `en` in the initial state: unknown, not invented
    assert en["values"] == [None, 1, 1]


def test_the_clock_is_listed_first():
    trace = [{"b": 0, "clk": 0}, {"state": {"b": 1, "clk": 1}}]
    w = from_trace(trace, clock="clk")
    assert [s["name"] for s in w["signals"]][0] == "clk"


def test_an_empty_trace_is_an_empty_waveform():
    assert from_trace([])["signals"] == []


# ---- from a VCD ------------------------------------------------------------
def test_vcd_values_land_on_the_right_cycle():
    """A VCD lists changes after their #time marker; sampling on the marker
    gives the previous cycle and shifts the whole waveform."""
    w = parse_vcd(VCD)
    assert w["cycles"] == 4
    assert w["times"] == [0, 5, 10, 15]
    got = {s["name"]: s["values"] for s in w["signals"]}
    assert got["clk"] == [0, 1, 0, 1]
    assert got["en"] == [0, 1, 1, 0]
    assert got["count"] == [0, 1, 2, 2]
    assert w["clock"] == "clk"


def test_a_vcd_without_a_body_is_empty():
    assert parse_vcd("$timescale 1ns $end\n")["cycles"] == 0


# ---- from a formal run -----------------------------------------------------
def test_a_failing_property_yields_its_counterexample():
    src = ("module m (input logic clk, input logic rst_n, output logic [2:0] q);\n"
           "  always_ff @(posedge clk) begin\n"
           "    if (!rst_n) q <= 0; else q <= q + 1;\n"
           "  end\n"
           "endmodule\n")
    w = from_formal(src, "q == 3'd2", reset="rst_n")
    assert w is not None
    assert w["cycles"] >= 3
    q = next(s for s in w["signals"] if s["name"] == "q")
    assert q["width"] == 3
    assert q["values"][-1] != 2            # the counterexample is where it is NOT 2
    assert "counterexample" in w["source"]


def test_a_property_that_holds_draws_nothing():
    """No counterexample means no waveform. Drawing one would be a lie."""
    src = ("module m (input logic clk, input logic rst_n, output logic [2:0] q);\n"
           "  always_ff @(posedge clk) begin\n"
           "    if (!rst_n) q <= 0; else q <= q;\n"
           "  end\n"
           "endmodule\n")
    assert from_formal(src, "q == 3'd0", reset="rst_n") is None


def test_a_design_outside_the_subset_draws_nothing():
    src = "module m (input logic clk); always @(*) clk = 1'b0; endmodule\n"
    assert from_formal(src, "clk == 1'b1", engine="explicit") is None


# ---- in the IDE ------------------------------------------------------------
def test_the_ide_embeds_the_waveform(tmp_path):
    import json
    import re
    from wengold.graph.builder import GraphBuilder
    from wengold.ide import build
    from wengold.kernel.validity import Result

    (tmp_path / "m.sv").write_text("module m; endmodule\n")
    files = {str(tmp_path / "m.sv"): "module m; endmodule\n"}
    g = GraphBuilder().build_from_files(files, include_dirs=[str(tmp_path)],
                                        backend="regex")
    wave = from_trace([{"q": 0}, {"state": {"q": 1}}], {"q": 3},
                      source="counterexample: test")
    html = build(tmp_path, g, {"m.sv"}, {}, [Result("unit_m", "sim",
                                                   depends_on={"m"})],
                 {"m"}, wave=wave)
    assert 'id="wavesvg"' in html
    data = json.loads(re.search(r"const D = (\{.*?\});\n", html, re.S).group(1))
    assert data["wave"]["cycles"] == 2
    assert data["wave"]["signals"][0]["name"] == "q"
