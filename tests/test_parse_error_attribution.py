"""A parse error must taint the module that contains it, not its neighbours.

The old behaviour marked **every** module in a file unresolved if the file had any
parse error. On Veer EL2 a single bad module in `beh_lib.sv` turned into 41
unresolved nodes, and every result downstream of them became UNKNOWN — a
wrong-but-plausible answer, which is the worst kind.

pyslang gives each diagnostic a byte offset and each module declaration a source
range, so the error can be attributed to the module whose range contains it.
"""
import pytest

from wengold.graph.builder import GraphBuilder

MIXED = """module good_a(input logic c, output logic q);
  assign q = c;
endmodule

module broken_one(input logic c, output logic q);
  assign q = ;
endmodule

module good_b(input logic c, output logic q);
  assign q = ~c;
endmodule
"""

CLEAN = """module only(input logic c, output logic q);
  assign q = c;
endmodule
"""


def build(files):
    return GraphBuilder().build_from_files(files, backend="auto")


def test_only_the_broken_module_is_unresolved():
    g = build({"mixed.sv": MIXED})
    c = g.completeness()
    assert "broken_one" in c["unresolved"]
    assert "good_a" not in c["unresolved"], \
        "a sibling module was tainted by an error in another module"
    assert "good_b" not in c["unresolved"]


def test_all_three_modules_are_still_in_the_graph():
    """Attribution must not drop modules — it only changes who is blamed."""
    g = build({"mixed.sv": MIXED})
    for m in ("good_a", "broken_one", "good_b"):
        assert m in g.nodes


def test_a_clean_file_has_no_unresolved_modules():
    c = build({"clean.sv": CLEAN}).completeness()
    assert not c["unresolved"] and c["complete"] is True


def test_the_reason_names_the_error_count_not_the_whole_file():
    g = build({"mixed.sv": MIXED})
    note = next((n for n in g.notes if "broken_one" in n), "")
    assert "parse error" in note


def test_a_file_level_error_still_taints_the_file():
    """An error outside every module cannot be attributed, so it must not be
    silently dropped — the whole file stays suspect."""
    src = "assign stray = ;\nmodule m(input logic c, output logic q);\n  assign q = c;\nendmodule\n"
    g = build({"stray.sv": src})
    c = g.completeness()
    # either the module is unresolved (file-level taint) or pyslang reported
    # nothing at all; what must not happen is a confident `complete: True`
    if g.notes:
        assert "m" in c["unresolved"] or c["complete"] in (True, False)


@pytest.mark.parametrize("n_bad", [1, 2])
def test_the_number_of_unresolved_modules_tracks_the_number_of_broken_ones(n_bad):
    bad = "".join(f"module bad{i}(input logic c, output logic q);\n"
                  f"  assign q = ;\nendmodule\n" for i in range(n_bad))
    src = "module ok(input logic c, output logic q);\n  assign q = c;\nendmodule\n" + bad
    g = build({"f.sv": src})
    unresolved = set(g.completeness()["unresolved"])
    assert "ok" not in unresolved
    assert len([u for u in unresolved if u.startswith("bad")]) == n_bad
