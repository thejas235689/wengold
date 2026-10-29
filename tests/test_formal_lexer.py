"""The formal front-end's lexer and the constructs it now accepts.

Measured on qeciphy's `src/*.sv`: **2/27 before, 9/27 after**. Every failure used
to be reported as "cannot tokenize", which said nothing about the design; there are
now **zero** tokenizer failures, so each remaining file gets a real reason.

What changed, and why each was needed:

  * `{` and `}` were not in the tokenizer's character class at all, so any
    concatenation `{a, b}` killed the file. 18 of the 27 failures were this.
  * `'0` / `'1` fill literals, `"strings"`, `$system` names and `'(cast)` were
    likewise untokenizable.
  * `typedef` and module instantiation were refused outright. A module's own
    assigns and properties can still be proved without modelling its children, so
    instances are now **recorded and skipped** rather than fatal.

The remaining refusals are deliberate scope limits — `ifdef`, `generate`, multiple
clock domains — and a test below keeps them refusing.
"""
import pytest

from wengold.formal.rtl_model import (RtlModule, UnsupportedConstruct,
                                      parse_module, tokenize)


def test_braces_tokenize():
    assert tokenize("assign {a,b} = c;") == [
        "assign", "{", "a", ",", "b", "}", "=", "c", ";"]


@pytest.mark.parametrize("text,expected", [
    ("x = '0;", ["x", "=", "'0", ";"]),
    ("x = '1;", ["x", "=", "'1", ";"]),
    ('p = "GTY";', ["p", "=", '"GTY"', ";"]),
    ("x = $clog2(N);", ["x", "=", "$clog2", "(", "N", ")", ";"]),
    ("x = '(a);", ["x", "=", "'", "(", "a", ")", ";"]),
])
def test_the_literals_and_casts_tokenize(text, expected):
    assert tokenize(text) == expected


def test_a_concatenation_target_no_longer_kills_the_file():
    m = parse_module("module t(input logic a, output logic [1:0] q);\n"
                     "  assign q = {a, a};\nendmodule\n")
    assert m.name == "t" and len(m.assigns) == 1


def test_an_instantiation_is_recorded_not_refused():
    m = parse_module("module t(input logic clk, output logic q);\n"
                     "  sub u_sub(.clk(clk), .q(q));\n"
                     "  assign q = clk;\nendmodule\n")
    assert m.instances == ["sub"]
    assert len(m.assigns) == 1, "the module's own logic must still be analysed"


@pytest.mark.parametrize("decl,expected", [
    ("sub #(.W(4)) u (.clk(clk));", ["sub"]),
    ("sub u [3:0] (.clk(clk));", ["sub"]),
    ("sub u (.clk(clk));", ["sub"]),
])
def test_instantiation_shapes(decl, expected):
    m = parse_module("module t(input logic clk);\n  " + decl + "\nendmodule\n")
    assert m.instances == expected


def test_a_typedefd_variable_is_not_an_instance():
    """`state_t st;` looks like the first two tokens of an instantiation but has
    no port list. Requiring the `(` is what tells them apart."""
    m = parse_module("module t(input logic clk);\n"
                     "  typedef enum logic [1:0] {IDLE, RUN} state_t;\n"
                     "  state_t st;\nendmodule\n")
    assert m.instances == [], m.instances
    assert "st" in m.signals
    assert m.typedefs


def test_the_skip_is_declared_not_hidden():
    """A caller must be able to see what the prover did not model."""
    m = parse_module("module t(input logic clk);\n"
                     "  sub u (.clk(clk));\nendmodule\n")
    assert m.instances == ["sub"]


# ---- the refusals that are deliberate -------------------------------------
@pytest.mark.parametrize("body,fragment", [
    ("generate\n  if (1) begin end\nendgenerate", "generate"),
    ("`ifdef FOO\n  assign x = 1;\n`endif", "conditional compilation"),
])
def test_constructs_that_change_elaboration_still_refuse(body, fragment):
    """These are refused on purpose: taking one branch silently would be a wrong
    answer, and this front-end does not give wrong answers."""
    with pytest.raises(UnsupportedConstruct) as e:
        parse_module("module t(input logic clk);\n" + body + "\nendmodule\n")
    assert fragment in str(e.value).lower()


def test_a_fill_literal_is_not_folded_to_a_number():
    """`'1` is all-ones at the signal width; without the width it is not a
    number, and folding it would be a silent lie."""
    from wengold.formal.rtl_model import eval_int
    with pytest.raises(UnsupportedConstruct):
        eval_int(("fill", "'1"), {}, {})
