"""Regressions for the formal front-end, found by generating RTL and proving it.

Every one of these was a construct that a *generated* module contains and the
front-end refused: a backtick in a header comment, a parameter port list, a
localparam, and a partial write to a register field.
"""
import pytest

from wengold.formal.rtl_model import (UnsupportedConstruct, parse_module,
                                      to_model)


def _model(src):
    return to_model(parse_module(src))


def test_backtick_in_a_comment_is_not_a_macro_use():
    src = ("// the subset covers `assign` and ternary `?:`\n"
           "/* and mentions `ifdef here */\n"
           "module m (input logic clk, input logic d, output logic q);\n"
           "  always_ff @(posedge clk) q <= d;\n"
           "endmodule\n")
    m = parse_module(src)
    assert m.name == "m"


def test_a_real_macro_use_is_still_refused():
    src = ("module m (input logic clk);\n"
           "  `ASSERT_KNOWN(foo)\n"
           "endmodule\n")
    with pytest.raises(UnsupportedConstruct, match="macro use"):
        parse_module(src)


def test_parameter_port_list_binds_its_default():
    src = ("module m #(parameter WIDTH = 4) (input logic clk, output logic [WIDTH-1:0] q);\n"
           "  always_ff @(posedge clk) q <= 0;\n"
           "endmodule\n")
    m = parse_module(src)
    assert m.params == {"WIDTH": 4}
    assert m.signals["q"] == 4


def test_localparam_is_bound_and_removed():
    src = ("module m (input logic clk, input logic [7:0] d, output logic [7:0] q);\n"
           "  localparam logic [7:0] MASK = 8'h0f;\n"
           "  always_ff @(posedge clk) q <= d & MASK;\n"
           "endmodule\n")
    m = parse_module(src)
    assert m.params == {"MASK": 0x0F}
    model = _model(src)
    nxt = model.step({"q": 0}, {"clk": 1, "d": 0xFF})
    assert nxt["q"] == 0x0F


def test_partial_write_merges_instead_of_overwriting():
    src = ("module m (input logic clk, input logic d, output logic [3:0] q);\n"
           "  always_ff @(posedge clk) q[3:1] <= d;\n"
           "endmodule\n")
    model = _model(src)
    # bit 0 is outside the written slice and must survive it
    assert model.step({"q": 0b1001}, {"clk": 1, "d": 1})["q"] == 0b0011
    assert model.step({"q": 0b1001}, {"clk": 1, "d": 0})["q"] == 0b0001


def test_single_bit_write_merges():
    src = ("module m (input logic clk, input logic d, output logic [3:0] q);\n"
           "  always_ff @(posedge clk) q[0] <= d;\n"
           "endmodule\n")
    model = _model(src)
    assert model.step({"q": 0b1110}, {"clk": 1, "d": 1})["q"] == 0b1111
    assert model.step({"q": 0b1111}, {"clk": 1, "d": 0})["q"] == 0b1110


def test_whole_signal_write_still_overwrites():
    src = ("module m (input logic clk, input logic d, output logic [3:0] q);\n"
           "  always_ff @(posedge clk) q <= d;\n"
           "endmodule\n")
    model = _model(src)
    # a whole-signal write replaces everything, unlike a slice write
    assert model.step({"q": 0b1001}, {"clk": 1, "d": 1})["q"] == 0b0001
    assert model.step({"q": 0b1001}, {"clk": 1, "d": 0})["q"] == 0b0000
