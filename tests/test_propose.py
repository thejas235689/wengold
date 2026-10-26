"""Edit proposals the kernel can justify.

The load-bearing test is `test_a_proposal_never_applies_itself`. A tool that edits
RTL without showing the diff first is not one you would let near a tapeout, so the
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


def test_stubs_cover_every_unresolved_module():
    g = FakeGraph()
    p = propose_stubs(g, {"unresolved": ["axi_zeroer", "sd_bridge"]})
    assert p is not None
    assert "module axi_zeroer();" in p.new_text
    assert "module sd_bridge();" in p.new_text
    assert p.path == STUB_FILE


def test_a_stub_is_visibly_empty_and_says_so():
    """A stub that returned 0 would let a check pass for the wrong reason."""
    p = propose_stubs(FakeGraph(), {"unresolved": ["m"]})
    assert "TODO: real implementation" in p.new_text
    assert "EMPTY" in p.new_text
    assert "assign" not in p.new_text, "a stub must not drive a value"


def test_the_rationale_quotes_the_kernel_fact():
    p = propose_stubs(FakeGraph(), {"unresolved": ["a", "b", "c"]})
    assert "3 module(s)" in p.rationale
    assert "UNKNOWN" in p.rationale


def test_the_diff_is_a_real_unified_diff():
    p = propose_stubs(FakeGraph(), {"unresolved": ["m"]})
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
    p = propose_stubs(FakeGraph(), {"unresolved": ["m"]})
    propose_all(FakeGraph(), {"unresolved": ["m"]}, tmp_path)
    assert not (tmp_path / STUB_FILE).exists(), "proposing wrote a file"


def test_apply_writes_only_when_called(tmp_path):
    p = propose_stubs(FakeGraph(), {"unresolved": ["m"]})
    out = p.apply(tmp_path)
    assert out.exists()
    assert "module m();" in out.read_text()


def test_propose_all_survives_a_malformed_note():
    p = propose_duplicate_exclusion(FakeGraph(notes=["duplicate definition: junk"]), ".")
    assert p is None, "a note it cannot parse must yield nothing, not a wrong edit"


def test_an_empty_graph_yields_no_proposals(tmp_path):
    assert propose_all(FakeGraph(), {"unresolved": []}, tmp_path) == []
