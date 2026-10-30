"""Static CDC analysis: is a crossing synchronised?

Until this, WENGOLD read and wrote the Accellera CDC format and checked the
collateral for internal consistency — it never looked at whether a crossing was
safe. Every release said so. This is that gap closed, as far as it can be closed
by reading syntax.

The tests are mostly about the distinctions that make a CDC report trustworthy:

* a single flop is **not** a synchroniser
* a 2-FF synchroniser on a **multi-bit bus** is not enough, and says so
* a signal that reaches the destination **through combinational logic** cannot have
  a synchroniser at all
* **no crossings found is not the same as clean** — the distinction a CDC tool
  that says "clean" when it means "I saw nothing" is how CDC bugs reach silicon
"""
import pytest

from wengold.cdc_analysis import analyse_text, classify
from wengold.graph.cdc import analyse as detect

TWO_FF = """
module sync2(input logic clk_a, input logic clk_b, input logic d, output logic q);
  logic meta, s;
  always_ff @(posedge clk_a) meta <= d;
  always_ff @(posedge clk_b) s <= meta;
  always_ff @(posedge clk_b) q <= s;
endmodule
"""

ONE_FF = """
module sync1(input logic clk_a, input logic clk_b, input logic d, output logic q);
  logic meta;
  always_ff @(posedge clk_a) meta <= d;
  always_ff @(posedge clk_b) q <= meta;
endmodule
"""

BUS_2FF = """
module busx(input logic clk_a, input logic clk_b, input logic [7:0] d,
            output logic [7:0] q);
  logic [7:0] m, s;
  always_ff @(posedge clk_a) m <= d;
  always_ff @(posedge clk_b) s <= m;
  always_ff @(posedge clk_b) q <= s;
endmodule
"""

THROUGH_LOGIC = """
module viacomb(input logic clk_a, input logic clk_b, input logic d,
               output logic q);
  logic reg_a, comb, reg_b;
  always_ff @(posedge clk_a) reg_a <= d;
  assign comb = reg_a & 1'b1;
  always_ff @(posedge clk_b) reg_b <= comb;
endmodule
"""


# ---- clocks and structure -----------------------------------------------
def test_both_clocks_are_found():
    a = analyse_text(TWO_FF, "t.sv")
    assert a.clocks["sync2"] == {"clk_a", "clk_b"}


def test_a_single_clock_module_has_no_crossings():
    src = """
module one(input logic clk, input logic d, output logic q);
  always_ff @(posedge clk) q <= d;
endmodule
"""
    assert analyse_text(src, "t.sv").crossings == []


# ---- the classification --------------------------------------------------
def test_a_two_flop_synchroniser_is_synchronised():
    a = analyse_text(TWO_FF, "t.sv")
    c = [x for x in a.crossings if x.signal == "meta"][0]
    assert c.verdict == "synchronised"
    assert "2-FF" in c.detail


def test_a_single_flop_is_not_a_synchroniser():
    """The distinction the whole module exists for."""
    a = analyse_text(ONE_FF, "t.sv")
    c = [x for x in a.crossings if x.signal == "meta"][0]
    assert c.verdict == "unsynchronised"
    assert "no second flop" in c.detail


def test_a_multibit_bus_through_2ff_is_flagged():
    """2-FF reduces metastability; it does not make a bus coherent."""
    a = analyse_text(BUS_2FF, "t.sv")
    c = [x for x in a.crossings if x.signal == "m"][0]
    assert c.width == 8, "the packed range was not read"
    assert c.verdict == "synchronised"
    assert "each bit settles independently" in c.detail


def test_a_crossing_through_combinational_logic_is_unsynchronised():
    rep = detect(THROUGH_LOGIC, "viacomb")
    a = analyse_text(THROUGH_LOGIC, "t.sv")
    cs = classify(rep, a)
    comb = [c for c in cs if c.signal == "comb"]
    assert comb, "the detector should find the combinational crossing"
    assert comb[0].verdict == "unsynchronised"
    assert "combinational" in comb[0].detail


# ---- the honesty guards --------------------------------------------------
def test_no_crossings_is_not_clean():
    """`clean` must not be true just because nothing was found."""
    src = """
module quiet(input logic clk, input logic d, output logic q);
  always_ff @(posedge clk) q <= d;
endmodule
"""
    a = analyse_text(src, "t.sv")
    assert a.crossings == []
    assert a.clean is False, "'I saw nothing' is not 'there is nothing'"


def test_an_unreadable_file_is_reported_not_passed():
    a = analyse_text("module broken(input logic", "bad.sv")
    assert a.unreadable == ["bad.sv"]
    assert a.crossings == []
    assert any("parse errors" in n for n in a.notes)


def test_the_render_says_so_when_nothing_was_found():
    src = "module quiet(input logic clk); always_ff @(posedge clk) ; endmodule\n"
    text = analyse_text(src, "t.sv").render()
    assert "not the same as clean" in text


# ---- against the repository's own example -------------------------------
def test_the_repo_example_is_reported_unsynchronised():
    """`examples/cdc/mixed_clocks.sv` demonstrates a crossing with one flop and one
    through logic. Both are genuinely unsynchronised and both must be reported."""
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "examples/cdc/mixed_clocks.sv"
    src = p.read_text()
    rep = detect(src, "mixed_clocks")
    cs = classify(rep, analyse_text(src, str(p)))
    signals = {c.signal: c.verdict for c in cs}
    assert signals.get("a_reg") == "unsynchronised"
    assert signals.get("comb") == "unsynchronised"
