"""The preprocessor and the slang-backed elaboration.

These are the front-ends that make WENGOLD usable on real RTL: they resolve
`ifdef against the project's defines, expand includes, and parse for real instead
of guessing from text.
"""
import pytest

from wengold.graph.builder import GraphBuilder
from wengold.graph.preprocess import Preprocessor, make_resolver
from wengold.graph.slang_backend import available, elaborate, extract

needs_slang = pytest.mark.skipif(not available(), reason="pyslang not installed")


# ---- preprocessor -------------------------------------------------------
def _pp(files, defines=None):
    return Preprocessor(make_resolver(files, []), defines=defines)


def test_include_is_inlined_and_resolved():
    files = {"defs.svh": "`define W 8\n", "top.sv": '`include "defs.svh"\nlogic [`W-1:0] q;\n'}
    out = _pp(files).run(files["top.sv"], "top.sv")
    assert "defs.svh" in out.includes
    assert "logic [8-1:0] q;" in out.text          # object-like macro expanded
    assert out.unresolved == []


def test_ifdef_selects_the_right_branch():
    src = "`ifdef SYNTH\nlogic a;\n`else\nlogic b;\n`endif\n"
    assert "logic a;" in _pp({}, {"SYNTH": "1"}).run(src).text
    assert "logic b;" in _pp({}, {}).run(src).text
    both = _pp({}, {"SYNTH": "1"}).run(src).text
    assert "logic b;" not in both


def test_elsif_and_else():
    src = "`ifdef X\nlogic x;\n`elsif Y\nlogic y;\n`else\nlogic z;\n`endif\n"
    assert "logic x;" in _pp({}, {"X": "1"}).run(src).text
    assert "logic y;" in _pp({}, {"Y": "1"}).run(src).text
    assert "logic z;" in _pp({}, {}).run(src).text
    only_x = _pp({}, {"X": "1"}).run(src).text
    assert "logic y;" not in only_x and "logic z;" not in only_x


def test_ifndef():
    src = "`ifndef X\nlogic not_x;\n`endif\n"
    assert "logic not_x;" in _pp({}, {}).run(src).text
    assert "logic not_x;" not in _pp({}, {"X": "1"}).run(src).text


def test_function_like_macro_is_not_naively_expanded():
    src = "`define MAX(a, b) ((a) > (b) ? (a) : (b))\nlogic [`MAX(1, 2)-1:0] x;\n"
    out = _pp({}).run(src).text
    assert "`MAX(1, 2)" in out            # left alone, not mangled


def test_standalone_unexpandable_macro_is_dropped():
    src = ("module m;\n"
           "  `ASSERT_KNOWN(Foo_A, foo)\n"
           "  logic q;\n"
           "endmodule\n")
    out = _pp({}).run(src)
    assert "ASSERT_KNOWN" in out.unexpanded
    assert "`ASSERT_KNOWN" not in out.text
    assert "logic q;" in out.text


def test_multiline_macro_call_is_swallowed_whole():
    src = ("module m;\n"
           "  `ASSERT(Foo_A,\n"
           "          a |-> b,\n"
           "          clk, !rst_n)\n"
           "  logic q;\n"
           "endmodule\n")
    out = _pp({}).run(src)
    assert "a |-> b" not in out.text      # the whole call went, not just line 1
    assert "logic q;" in out.text


def test_unresolved_include_is_recorded():
    out = _pp({}).run('`include "missing.svh"\nlogic q;\n')
    assert out.unresolved == ["missing.svh"]


def test_timescale_and_other_directives_are_dropped():
    out = _pp({}).run("`timescale 1ns/1ps\n`default_nettype none\nlogic q;\n").text
    assert "timescale" not in out and "default_nettype" not in out
    assert "logic q;" in out


# ---- slang extraction ---------------------------------------------------
@needs_slang
def test_extract_finds_modules_and_instantiations():
    src = ("module child (input logic clk); endmodule\n"
           "module top (input logic clk);\n"
           "  child u_child (.clk(clk));\n"
           "endmodule\n")
    unit = extract(src, "top.sv")
    assert set(unit.modules) == {"child", "top"}
    assert ("top", "child", "u_child") in unit.instantiations
    assert unit.parse_errors == 0


@needs_slang
def test_extract_finds_packages_and_imports():
    src = ("package p; endpackage\n"
           "module m; import p::*; endmodule\n")
    unit = extract(src, "m.sv")
    assert "p" in unit.packages and "p" in unit.imports


@needs_slang
def test_extract_ignores_comments_and_macros():
    src = ("// Copyright lowRISC contributors, distributed as asserted.\n"
           "/* child u0 (); this is prose */\n"
           "module m; endmodule\n")
    unit = extract(src, "m.sv")
    assert unit.modules == ["m"]
    assert unit.instantiations == []


@needs_slang
def test_elaborate_over_a_file_set():
    files = {"defs.svh": "`define W 8\n",
             "child.sv": "module child (input logic clk); endmodule\n",
             "top.sv": ('`include "defs.svh"\nmodule top (input logic clk);\n'
                        '  child u (.clk(clk));\nendmodule\n')}
    units = elaborate(files, include_dirs=["."], defines={})
    top = units["top.sv"]
    assert top.modules == ["top"]
    assert ("top", "child", "u") in top.instantiations
    assert "defs.svh" in top.includes
    assert top.parse_errors == 0


# ---- builder routing ----------------------------------------------------
@needs_slang
def test_builder_uses_slang_and_marks_missing_definitions():
    files = {"top.sv": ("module top (input logic clk);\n"
                        "  ghost u_ghost (.clk(clk));\nendmodule\n")}
    g = GraphBuilder().build_from_files(files, backend="slang")
    assert "top" in g.nodes
    assert "top" in g.unresolved_nodes()          # ghost has no definition
    assert any(e.kind.value == "unknown" for e in g.edges)


@needs_slang
def test_builder_slang_resolves_a_complete_set():
    files = {"child.sv": "module child (input logic clk); endmodule\n",
             "top.sv": ("module top (input logic clk);\n"
                        "  child u (.clk(clk));\nendmodule\n")}
    g = GraphBuilder().build_from_files(files, backend="slang")
    assert g.completeness()["complete"] is True
    assert g.unresolved_nodes() == set()
    assert any(e.kind.value == "instantiates" for e in g.edges)


def test_builder_regex_backend_still_works():
    files = {"top.sv": ("module top (input logic clk);\n"
                        "  child u (.clk(clk));\nendmodule\n")}
    g = GraphBuilder().build_from_files(files, backend="regex")
    assert "top" in g.nodes


@needs_slang
def test_instantiation_is_attributed_to_its_own_module():
    """Two modules in one file must not both claim the other's instantiations.

    A Verilog file commonly defines several modules, and a file-level attribution
    invents a hierarchy in which every module instantiates every other.
    """
    src = ("module leaf (input logic a, output logic y); assign y = a; endmodule\n"
           "module uses_it (input logic a, output logic y);\n"
           "  leaf u_leaf (.a(a), .y(y));\n"
           "endmodule\n"
           "module does_not (input logic a, output logic y);\n"
           "  assign y = ~a;\n"
           "endmodule\n")
    unit = extract(src, "multi.v")
    owners = {(o, c) for o, c, _i in unit.instantiations}
    assert ("uses_it", "leaf") in owners
    assert not any(o == "does_not" for o, _c in owners)


@needs_slang
def test_untaken_generate_branch_is_not_a_missing_module():
    """`generate if (0)` is dead code, not a missing definition.

    CV32E40P instantiates its PMP inside `if (PULP_SECURE && USE_PMP)` with both
    localparams 0; reporting that as unresolved blames the file set for code no
    build would elaborate.
    """
    def unit_for(use):
        src = ("module leaf (input logic a); endmodule\n"
               "module top (input logic a);\n"
               f"  localparam USE = {use};\n"
               "  generate if (USE) begin : g\n"
               "    leaf u_leaf (.a(a));\n"
               "  end endgenerate\n"
               "endmodule\n")
        return extract(src, "top.sv")

    assert unit_for(0).instantiations == []          # not elaborated: not missing
    assert ("top", "leaf", "u_leaf") in unit_for(1).instantiations


@needs_slang
def test_interfaces_count_as_definitions():
    """An instantiation of an interface must not read as a missing module."""
    files = {"iface.sv": "interface mem_interface; endinterface\n",
             "child.sv": "module child (input logic clk); endmodule\n",
             "top.sv": ("module top (input logic clk);\n"
                        "  mem_interface u_if ();\n"
                        "  child u_c (.clk(clk));\n"
                        "endmodule\n")}
    units = elaborate(files, include_dirs=["."], defines={})
    assert "mem_interface" in units["iface.sv"].interfaces
    g = GraphBuilder().build_from_files(files, backend="slang")
    assert "mem_interface" in g.nodes
    assert "top" not in g.unresolved_nodes()      # resolved, not missing
