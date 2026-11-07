"""The four remaining false negatives in the CDC crossing analysis.

Each test here failed on the code before its fix and passes after it. The four are
the ones the audit left open as "still would let a real CDC bug through":

  1. ``cdc_analysis.analyse_text`` built crossings only from clocked writes, so a
     signal that reached the destination through combinational logic produced no
     entry at all — and ``clean`` returned True.
  2. ``graph.cdc``'s assignment pattern matched ``sig <= expr`` inside an ``if``
     condition, so a comparison was recorded as an assignment: the crossing
     vanished and the signal was listed under the wrong clock.
  3. its block-body reader stopped at the first ``;``, so every assignment after
     the first in an ``if (en) begin ... end`` body was lost.
  4. ``if clock in src: continue`` suppressed every crossing into a mixed-domain
     combinational node, losing the genuine contribution from the other domain.

Why the standard cares, in its own words:

  * Clause 3.1 defines a glitch as "A transient pulse on a signal that is caused by
    a race between signals in its fan-in. This includes asynchronous data path (for
    example, combinational logic going into synchronizers)". Combinational logic on
    the path is part of the asynchronous data path, so a tool that only looks at
    flop-to-flop writes is not looking at the whole path.
  * Clause 4.3.10: ``-logic`` ``internal_sync`` "indicates a multi-flop
    synchronizer on the path through the port", while ``combo`` / 
    ``glitch_free_combo`` describe combinatorial logic on that path. A
    combinational path is not an ``internal_sync`` path, and Table 3 makes the
    default explicit: "If the logic attribute is not provided in the code, the port
    is assumed to be connected to a sequential component directly." Safety is not
    the default; it has to be shown.
  * Clause 4.3.8 states the crossing case plainly: two flops in two asynchronous
    clock domains with data between them "indicates a clock domain crossing
    violation on the data crossing between F0 and F1". Losing that data crossing
    because of a regex (findings 2, 3, 4) reports no violation where the standard
    describes one.
"""
import pytest

from wengold.cdc_analysis import analyse_text
from wengold.graph.cdc import analyse as detect


# ---- finding 1: combinational crossings -------------------------------
# `s` is written on clk_a and is correctly synchronised into clk_b by a 2-FF
# chain — but it *also* reaches clk_b through `comb`, straight into a flop. The
# old analyse_text saw only the clocked writes, so `comb` never appeared as a
# crossing and `clean` came back True on an unsynchronised path.
COMB_PATH = """
module combx(input logic clk_a, input logic clk_b, input logic d, input logic en,
             output logic q, output logic q2);
  logic s, meta, sync, comb;
  always_ff @(posedge clk_a) s <= d;
  always_ff @(posedge clk_b) begin meta <= s; sync <= meta; q <= sync; end
  assign comb = s & en;
  always_ff @(posedge clk_b) q2 <= comb;
endmodule
"""

# The same shape of path, but this time the combinational node feeds a real 2-FF
# chain. Clause 4.3.10 calls that a `glitch_free_combo`/`combo` path into a
# synchroniser, which is a legitimate structure — the fix must not flag it.
COMB_INTO_SYNC = """
module combok(input logic clk_a, input logic clk_b, input logic d, input logic en,
              output logic q);
  logic s, c, m, sy;
  always_ff @(posedge clk_a) s <= d;
  assign c = s & en;
  always_ff @(posedge clk_b) begin m <= c; sy <= m; q <= sy; end
endmodule
"""


def test_a_combinational_path_into_another_domain_is_a_crossing():
    """`comb` carries clk_a data into a clk_b flop with no synchroniser.

    Before the fix the crossing list held only `s` (synchronised), so `clean` was
    True. Clause 3.1 puts "combinational logic going into synchronizers" on the
    asynchronous data path, and Table 3's `-logic` default assumes a direct
    sequential connection unless synchronisation is shown — so an unreported
    combinational path is exactly the case that must not be called clean.
    """
    a = analyse_text(COMB_PATH, "t.sv")
    comb = [c for c in a.crossings if c.signal == "comb"]
    assert comb, "the combinational path into clk_b produced no crossing at all"
    c = comb[0]
    assert (c.from_clock, c.to_clock) == ("clk_a", "clk_b")
    assert c.verdict == "unsynchronised"
    assert "combinational" in c.detail
    assert a.clean is False, "clean must be False while that path is unsynchronised"


def test_a_combinational_path_into_a_2ff_chain_is_not_called_clean():
    """The fix must not turn a legitimate combo-into-synchroniser path into a hard
    failure: `c` feeds `m -> sy` on clk_b, so the verdict stays `synchronised`.

    It must NOT be called clean, though. This test originally asserted
    `a.clean is True`, and that was an overclaim: Clause 4.3.10 separates
    `internal_sync` from `combo`/`glitch_free_combo` on the path, and a glitch on
    the input presents a transition the synchroniser then passes on faithfully.
    `graph/cdc.py` already reports this shape as `through_combinational` and never
    as safe; the two tools now agree that it is not clean, while disagreeing on
    the wording — which is a documentation question, not a safety one.
    """
    a = analyse_text(COMB_INTO_SYNC, "t.sv")
    c = [x for x in a.crossings if x.signal == "c"][0]
    assert c.verdict == "synchronised", "the 2-FF is there; do not call it broken"
    assert "combinational" in c.detail, "the report must still say the path is combinational"
    assert a.clean is False, "a combinational path into a synchroniser is not clean"


# ---- finding 2: a comparison is not an assignment ---------------------
# `r <= 4` is a comparison. Read as an assignment, it made `r` look written by
# clk_b: the signal dropped out of clk_b's read set (so no crossing was reported)
# and appeared in clk_b's domain instead of clk_a's.
COMPARE_IN_IF = """
module cmpx(input logic clk_a, input logic clk_b, input logic [3:0] d,
            output logic q);
  logic [3:0] r;
  always_ff @(posedge clk_a) r <= d;
  always_ff @(posedge clk_b) if (r <= 4) q <= 1'b1; else q <= r[0];
endmodule
"""


def test_a_comparison_in_an_if_condition_is_not_an_assignment():
    """Clause 4.3.8: data between two flops in asynchronous domains is a crossing.
    `r` is written on clk_a and read on clk_b; the `<=' in the condition must not
    hide that."""
    rep = detect(COMPARE_IN_IF, "cmpx")
    hits = [c for c in rep.crossings
            if c.signal == "r" and (c.from_domain, c.to_domain) == ("clk_a", "clk_b")]
    assert hits, "the crossing r: clk_a -> clk_b vanished"
    assert "r" not in rep.domains.get("clk_b", []), \
        "r is written on clk_a; a comparison in a condition put it in clk_b"
    assert rep.domains.get("clk_a") == ["r"]
    assert rep.domains.get("clk_b") == ["q"]


# ---- finding 3: the whole if-guarded body is one statement ------------
# The read of `s` lives in the second assignment of the begin/end body. The old
# reader stopped at the first `;`, so `sync <= s` was never seen and the crossing
# disappeared.
IF_GUARDED_BODY = """
module truncx(input logic clk_a, input logic clk_b, input logic en, input logic d,
              output logic q);
  logic s, meta, sync;
  always_ff @(posedge clk_a) s <= d;
  always_ff @(posedge clk_b) if (en) begin meta <= 1'b0; sync <= s; end
endmodule
"""


def test_an_if_guarded_begin_end_body_keeps_every_assignment():
    """`sync <= s` is inside the same statement as `meta <= 1'b0`."""
    rep = detect(IF_GUARDED_BODY, "truncx")
    assert [c for c in rep.crossings
            if c.signal == "s" and (c.from_domain, c.to_domain) == ("clk_a", "clk_b")], \
        "the crossing on s was lost with the truncated body"
    assert "sync" in rep.domains.get("clk_b", []), \
        "sync is written on clk_b inside the begin/end body"
    assert "sync" not in rep.domains.get("clk_a", [])


# ---- finding 4: a mixed-domain combinational node ---------------------
# `comb` is driven from both domains. Reading it on clk_b used to be skipped
# outright because clk_b was among its sources — which discarded the clk_a
# contribution that is the actual crossing.
MIXED_COMB = """
module mixedx(input logic clk_a, input logic clk_b, input logic a, input logic b,
              output logic q);
  logic ra, rb, comb;
  always_ff @(posedge clk_a) ra <= a;
  always_ff @(posedge clk_b) rb <= b;
  assign comb = ra & rb;
  always_ff @(posedge clk_b) q <= comb;
endmodule
"""


def test_a_mixed_domain_combinational_node_still_yields_the_crossing():
    """Only the same-domain case may be skipped. `comb` carries clk_a data into a
    clk_b flop, so clk_a -> clk_b must be reported (Clause 3.1: combinational
    logic on the asynchronous data path)."""
    rep = detect(MIXED_COMB, "mixedx")
    hits = [c for c in rep.crossings if c.signal == "comb"]
    assert hits, "every crossing into the mixed-domain node was suppressed"
    assert {(c.from_domain, c.to_domain) for c in hits} == {("clk_a", "clk_b")}
    assert hits[0].kind == "through_combinational"
    # and the same-domain contribution must not be invented as a crossing
    assert not [c for c in rep.crossings if c.from_domain == c.to_domain]


# ---- the guard the audit insists on ----------------------------------
# A correct 2-FF synchroniser must stay synchronised and clean in both tools, or
# the classifier is as useless as one that flags nothing.
GOOD_2FF = """
module good2ff(input logic clk_a, input logic clk_b, input logic d,
               output logic q);
  logic s, m, sy;
  always_ff @(posedge clk_a) s <= d;
  always_ff @(posedge clk_b) begin m <= s; sy <= m; q <= sy; end
endmodule
"""


def test_a_correct_2ff_stays_synchronised_in_both_tools():
    a = analyse_text(GOOD_2FF, "t.sv")
    assert [c.verdict for c in a.crossings] == ["synchronised"]
    assert a.clean is True

    rep = detect(GOOD_2FF, "good2ff")
    assert [(c.signal, c.from_domain, c.to_domain) for c in rep.crossings] == \
        [("s", "clk_a", "clk_b")]
    # `d` is a module input with no clock of its own; the detector says so rather
    # than guessing (it is the only name it cannot place).
    assert rep.unresolved == ["d"]
