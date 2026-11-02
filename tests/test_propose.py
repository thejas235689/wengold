"""Edit proposals the kernel can justify.

The load-bearing test is `test_a_proposal_never_applies_itself`. A tool that edits
RTL without showing the diff first is not one you would let near silicon signoff, so the
gate is pinned rather than assumed.
"""
import pytest

from wengold.agent.propose import (STUB_FILE, Proposal, propose_all,
                                   propose_duplicate_exclusion, propose_stubs)


class FakeNode:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeGraph:
    def __init__(self, notes=None, nodes=None):
        self.notes = notes or []
        self.nodes = nodes or {}


def test_no_unresolved_means_no_stub_proposal():
    assert propose_stubs(FakeGraph(), {"unresolved": []}) is None


def test_stubs_cover_every_missing_module():
    """The stub list comes from the notes, not from `unresolved`.

    `unresolved` names the modules that *contain* an unresolved instantiation —
    the dependents, which are defined. Stubbing those would write a second
    definition of a module that already exists. See
    `test_a_defined_module_is_never_stubbed` below.
    """
    g = FakeGraph()
    p = propose_stubs(g, {
        "unresolved": ["top"],
        "issues": ["top: instantiation `axi_zeroer` has no definition in the file set",
                   "top: instantiation `sd_bridge` has no definition in the file set"]})
    assert p is not None
    assert "module axi_zeroer();" in p.new_text
    assert "module sd_bridge();" in p.new_text
    assert p.path == STUB_FILE


def test_a_stub_is_visibly_empty_and_says_so():
    """A stub that returned 0 would let a check pass for the wrong reason."""
    p = propose_stubs(FakeGraph(), {
        "unresolved": ["top"],
        "issues": ["top: instantiation `m` has no definition in the file set"]})
    assert "TODO: real implementation" in p.new_text
    assert "EMPTY" in p.new_text
    assert "assign" not in p.new_text, "a stub must not drive a value"


def test_the_rationale_quotes_the_kernel_fact():
    p = propose_stubs(FakeGraph(), {
        "unresolved": ["top"],
        "issues": [f"top: instantiation `{n}` has no definition in the file set"
                   for n in ("a", "b", "c")]})
    assert "3 module(s)" in p.rationale
    assert "UNKNOWN" in p.rationale


def test_a_defined_module_is_never_stubbed():
    """The regression this contract change exists for.

    `unresolved` holds `top`; `top` is defined; a stub for it would be a second
    definition of a module that already exists.
    """
    p = propose_stubs(FakeGraph(), {
        "unresolved": ["top"],
        "issues": ["top: instantiation `missing_block` has no definition in the file set"]})
    declared = [ln.split()[1].split("(")[0]
                for ln in p.new_text.splitlines() if ln.startswith("module ")]
    assert declared == ["missing_block"], declared


def test_unresolved_without_a_named_missing_module_proposes_nothing():
    """Better to do nothing than to stub the wrong module."""
    assert propose_stubs(FakeGraph(), {"unresolved": ["top"]}) is None


def test_the_diff_is_a_real_unified_diff():
    p = propose_stubs(FakeGraph(), {
        "unresolved": ["top"],
        "issues": ["top: instantiation `m` has no definition in the file set"]})
    assert p.diff.startswith("--- a/")
    assert "+++ b/" in p.diff
    assert "@@" in p.diff


def test_no_duplicates_means_no_exclusion_proposal():
    assert propose_duplicate_exclusion(FakeGraph(), ".") is None


def test_a_duplicate_proposal_excludes_all_but_one():
    note = ("duplicate definition: `Top` is declared in Core/Top.sv, "
            "Test/A.sv, Test/B.sv — the graph keeps only one")
    p = propose_duplicate_exclusion(FakeGraph(notes=[note]), ".")
    assert p is not None
    assert "Core/Top.sv" in p.new_text
    assert "excluded: Test/A.sv" in p.new_text
    assert "excluded: Test/B.sv" in p.new_text
    # the kept copy must appear as a bare path line, not only inside a comment
    assert any(ln.strip() == "Core/Top.sv" for ln in p.new_text.splitlines())


def test_a_proposal_never_applies_itself(tmp_path):
    """Proposing is not applying. This is the whole safety property."""
    p = propose_stubs(FakeGraph(), {
        "unresolved": ["top"],
        "issues": ["top: instantiation `m` has no definition in the file set"]})
    propose_all(FakeGraph(), {"unresolved": ["m"]}, tmp_path)
    assert not (tmp_path / STUB_FILE).exists(), "proposing wrote a file"


def test_apply_writes_only_when_called(tmp_path):
    p = propose_stubs(FakeGraph(), {
        "unresolved": ["top"],
        "issues": ["top: instantiation `m` has no definition in the file set"]})
    out = p.apply(tmp_path)
    assert out.exists()
    assert "module m();" in out.read_text()


def test_propose_all_survives_a_malformed_note():
    p = propose_duplicate_exclusion(FakeGraph(notes=["duplicate definition: junk"]), ".")
    assert p is None, "a note it cannot parse must yield nothing, not a wrong edit"


def test_an_empty_graph_yields_no_proposals(tmp_path):
    assert propose_all(FakeGraph(), {"unresolved": []}, tmp_path) == []


# ---- ports come from the instantiation site ----------------------------
def test_ports_are_recovered_from_the_instantiation(tmp_path):
    """The stub used to say "port list not recoverable from the graph".

    That was true of the graph and false of the project: the instantiation names
    every port. A stub without them can fail to elaborate against its own
    instantiation.
    """
    (tmp_path / "top.sv").write_text(
        "module top(input logic c, output logic q);\n"
        "  missing_block u(.clk(c), .rst_n(c), .q(q));\n"
        "endmodule\n")
    from wengold.desktop import build_state

    state = build_state(str(tmp_path))
    completeness = state["graph"].completeness()
    p = propose_stubs(state["graph"], completeness, str(tmp_path))
    assert p is not None
    assert "module missing_block(clk, rst_n, q);" in p.new_text


def test_a_stub_claims_no_port_directions(tmp_path):
    """An instantiation gives names and connections, not directions. Non-ANSI
    form is legal and claims nothing the source does not say."""
    (tmp_path / "top.sv").write_text(
        "module top(input logic c, output logic q);\n"
        "  missing_block u(.a(c), .b(q));\n"
        "endmodule\n")
    from wengold.desktop import build_state

    state = build_state(str(tmp_path))
    p = propose_stubs(state["graph"], state["graph"].completeness(), str(tmp_path))
    line = [l for l in p.new_text.splitlines() if l.startswith("module ")][0]
    assert "input" not in line and "output" not in line, line


def test_without_a_root_the_stub_says_what_it_does_not_know():
    """No root means no source scan, and the comment must not claim more."""
    p = propose_stubs(FakeGraph(), {
        "unresolved": ["top"],
        "issues": ["top: instantiation `m` has no definition in the file set"]})
    assert "module m();" in p.new_text
    assert "no instantiation of this module was found" in p.new_text


def test_the_graph_still_wins_when_it_has_ports():
    """A defined module's ports come from the graph; the source scan is a fallback."""
    from wengold.agent.propose import _port_names

    class N:
        ports = ["a", "b"]
    g = FakeGraph(nodes={"m": N()})
    assert _port_names(g, "m", "/nonexistent") == ["a", "b"]
