"""Root-cause analysis.

The analyzer is only useful if it names the real cause and says when it cannot.
These tests build small projects where the cause is known, and check the answer —
including the two ways it must decline to answer: a change that does not reach
the result, and a name that is not in the graph at all.
"""
import textwrap

import pytest

from wengold.graph.builder import GraphBuilder
from wengold.rootcause import (diagnose_node, diagnose_verdict, localize)

needs_slang = pytest.mark.skipif(
    not __import__("wengold.graph.slang_backend", fromlist=["available"]).available(),
    reason="pyslang not installed")


def _graph(files, incdirs=(".",)):
    return GraphBuilder().build_from_files(dict(files), include_dirs=list(incdirs),
                                           backend="slang")


# ---- why is this node unresolved ------------------------------------------
@needs_slang
def test_missing_module_names_the_file_and_the_construct():
    g = _graph({"top.sv": "module top; missing_cell u_c (); endmodule\n"})
    d = diagnose_node(g, "top")
    assert d.status == "unresolved"
    cause = d.causes[0]
    assert cause.kind == "missing definition"
    assert cause.subject == "missing_cell"
    assert cause.file == "top.sv"
    assert "u_c" in (cause.construct or "")
    assert cause.action


@needs_slang
def test_missing_module_points_at_the_unvendored_dependency(tmp_path):
    """The CV32E40P case: the module comes from a dependency nobody vendored."""
    (tmp_path / "Bender.yml").write_text(textwrap.dedent("""
        package:
          name: demo
        dependencies:
          common_cells: { git: "https://example.invalid/common_cells.git", version: 1.0 }
          tech_cells_generic: { git: "https://example.invalid/tcg.git", version: 0.1 }
        sources:
          include_dirs: [rtl/include]
    """))
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "vendor").mkdir()
    (tmp_path / "rtl" / "vendor" / "common_cells").mkdir()
    (tmp_path / "top.sv").write_text("module top; pulp_clock_gating u_cg (); endmodule\n")

    g = _graph({"top.sv": (tmp_path / "top.sv").read_text()},
               incdirs=(str(tmp_path),))
    d = diagnose_node(g, "top", root=tmp_path)
    detail = d.causes[0].detail
    assert "tech_cells_generic" in detail          # declared, not vendored
    assert "common_cells" not in d.causes[0].action
    assert d.causes[0].certainty == "probable"


@needs_slang
def test_a_resolved_node_says_what_it_touches():
    g = _graph({"leaf.sv": "module leaf; endmodule\n",
                "top.sv": "module top; leaf u_l (); endmodule\n"})
    d = diagnose_node(g, "top")
    assert d.status == "resolved"
    assert any("depends on" in n for n in d.notes)
    assert any("used by" in n for n in d.notes)


def test_an_unknown_node_is_reported_as_unknown():
    g = _graph({"a.sv": "module a; endmodule\n"})
    d = diagnose_node(g, "does_not_exist")
    assert d.status == "not in the graph"
    assert "neither defined nor referenced" in d.notes[0]


# ---- why is this result invalidated ---------------------------------------
def _chain():
    """leaf <- mid <- top, so an effect from leaf reaches top through mid."""
    return _graph({
        "leaf.sv": "module leaf; endmodule\n",
        "mid.sv": "module mid; leaf u_l (); endmodule\n",
        "top.sv": "module top; mid u_m (); endmodule\n",
    })


@needs_slang
def test_localize_gives_the_path_through_the_intermediate_module():
    g = _chain()
    d = localize(g, {"top"}, {"leaf"}, result_id="r")
    assert d.status == "invalidated"
    assert d.culprits[0].node == "leaf"
    # the regression this test exists for: the path must go THROUGH mid, not
    # jump straight to top because descendants() is transitive
    assert d.culprits[0].path == ["leaf", "mid", "top"]
    assert d.culprits[0].distance == 2


@needs_slang
def test_localize_declines_when_no_change_reaches_the_result():
    g = _chain()
    # `top` is in the graph but downstream of leaf, so it cannot cause it
    d = localize(g, {"leaf"}, {"top"}, result_id="r")
    assert d.status == "not explained"
    assert "no change reaches this result" in d.notes[0]
    assert d.culprits == []


@needs_slang
def test_localize_flags_a_name_that_is_not_in_the_graph():
    g = _chain()
    d = localize(g, {"top"}, {"leafy"}, result_id="r")
    assert any("not in the graph" in n for n in d.notes)


@needs_slang
def test_localize_ranks_the_closer_change_first():
    g = _chain()
    d = localize(g, {"top"}, {"mid", "leaf"}, result_id="r")
    assert [c.node for c in d.culprits] == ["mid", "leaf"]


# ---- why is this result unknown -------------------------------------------
@needs_slang
def test_a_result_with_no_dependency_can_establish_nothing():
    g = _chain()
    d = diagnose_verdict(g, "r", set())
    assert d.status == "unknown"
    assert "declares no dependency" in d.notes[0]


@needs_slang
def test_an_unresolved_node_in_the_closure_is_the_modelling_gap():
    g = _graph({"top.sv": "module top; missing_cell u_c (); endmodule\n"})
    d = diagnose_verdict(g, "r", {"top"})
    assert d.status == "unknown"
    assert d.causes[0].kind == "modelling gap"
    assert d.causes[0].subject == "top"


@needs_slang
def test_a_clean_unaffected_result_is_valid():
    g = _chain()
    d = diagnose_verdict(g, "r", {"leaf"}, changed={"top"})
    assert d.status == "not explained"        # top is downstream, it cannot cause it
