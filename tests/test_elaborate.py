"""Elaboration: includes, packages, parameters, generate blocks, filelists, and
the unresolved cases that must not be silently ignored."""
from wengold.graph.builder import GraphBuilder
from wengold.graph.elaborate import (Elaborator, extract_generate_blocks,
                                     extract_instantiations, extract_parameters,
                                     read_filelist)

GOOD = {
    "defs.svh": "`define WIDTH 8\n",
    "pkg.svh": "package pkg; endpackage\n",
    "top.sv": '`include "defs.svh"\n'
              "module top; import pkg::*; parameter N = 8; child u0 (); endmodule\n",
    "child.sv": "module child; endmodule\n",
}

BAD_INCLUDE = {
    "top.sv": '`include "missing.svh"\nmodule top; endmodule\n',
}

BAD_INST = {
    "top.sv": "module top; ghost u1 (); endmodule\n",
}


def test_filelist_parsing():
    text = "+incdir+rtl/include\n+define+SYNTH+WIDTH=8\ntop.sv\n// comment\nchild.sv\n"
    files, incdirs, defines = read_filelist(text)
    assert files == ["top.sv", "child.sv"]
    assert incdirs == ["rtl/include"]
    assert defines == {"SYNTH", "WIDTH"}


def test_extract_helpers():
    src = ("module m; parameter W = 4; generate for (genvar i=0;i<2;i++) begin: g "
           "child u (); endgenerate endmodule")
    assert extract_parameters(src) == {"W": "4"}
    assert extract_generate_blocks(src)
    assert ("child", "u") in extract_instantiations(src)


def test_elaboration_resolves_includes_and_imports():
    res = Elaborator(GOOD).elaborate()
    top = res.modules["top"]
    assert "defs.svh" in top.includes
    assert top.imports == {"pkg"}
    assert top.parameters.get("N") == "8"
    assert ("child", "u0") in top.instantiations
    assert not top.unresolved
    assert res.unresolved == {}


def test_unresolved_include_is_reported():
    res = Elaborator(BAD_INCLUDE).elaborate()
    reasons = res.unresolved["top"]
    assert any("unresolved include" in r for r in reasons)


def test_unresolved_instantiation_is_reported():
    res = Elaborator(BAD_INST).elaborate()
    reasons = res.unresolved["top"]
    assert any("no definition" in r for r in reasons)


def test_build_from_files_marks_unresolved():
    good = GraphBuilder().build_from_files(GOOD)
    assert good.completeness()["complete"] is True
    assert good.unresolved_nodes() == set()

    bad = GraphBuilder().build_from_files(BAD_INST)
    assert bad.completeness()["complete"] is False
    assert "ghost" in bad.unresolved_nodes()


def test_build_from_filelist_uses_incdirs():
    files = {"rtl/include/defs.svh": "`define X 1\n",
             "top.sv": '`include "defs.svh"\nmodule top; endmodule\n'}
    graph = GraphBuilder().build_from_filelist("+incdir+rtl/include\ntop.sv\n", files)
    assert graph.completeness()["complete"] is True


def test_port_connections_are_not_instantiations():
    src = ("module t; dma u (.clk(clk), .rst_n(rst_n), .prot(3'b000), .deny(d));"
           " endmodule")
    assert extract_instantiations(src) == [("dma", "u")]


# ---- regression: real-RTL noise found on OpenTitan ---------------------
def test_comments_do_not_create_instantiations():
    src = ('// Copyright lowRISC contributors. Licensed under the Apache License,\n'
           '// distributed under the License is distributed on an "AS IS" BASIS.\n'
           '/* This file is part of the project and will be used as asserted. */\n'
           'module m; child u0 (); endmodule\n')
    assert extract_instantiations(src) == [("child", "u0")]


def test_macro_invocations_are_not_instantiations():
    src = ('module m;\n'
           '  `ASSERT_FOO(a, b)\n'
           '  ASSERT_STATIC_LINT_ERROR(prim_fifo_sync)\n'
           '  child u0 ();\n'
           'endmodule\n')
    assert extract_instantiations(src) == [("child", "u0")]


def test_sva_vocabulary_is_not_instantiated():
    src = "module m; property p; disable iff (!rst_n) 1'b1; endproperty endmodule"
    assert extract_instantiations(src) == []
