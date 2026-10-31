"""Suggesting better code, from checks that actually ran.

The point of this module is what it refuses to do. It does not have opinions about
your RTL. Every suggestion is a diff whose justification is **a check that ran and
a result it produced** — and the strongest of them is proved by execution:

| suggestion | the check | what it said |
| --- | --- | --- |
| reset a flop | the simulation | `output q is X after reset` |
| add a 2-FF synchroniser | the CDC analysis | the crossing is `unsynchronised` |
| do not 2-FF a bus | the CDC analysis | the crossing is multi-bit |

The test that matters most is not that a suggestion is produced. It is that
**applying it turns the failing check into a passing one** — otherwise the
suggestion is just a nicer-looking guess.
"""
import re

import pytest

from wengold.review import Suggestion, _clocked_blocks, _unreset_flops, render, review

UNRESET = """module cnt(input logic clk, input logic rst_n, input logic en,
             output logic [3:0] q);
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      // q is deliberately missing
    end else if (en) begin
      q <= q + 4'd1;
    end
  end
endmodule
"""

UNRESET_TB = """module cnt_tb;
  logic clk = 0, rst_n = 0, en = 0;
  logic [3:0] q;
  cnt dut(.clk(clk), .rst_n(rst_n), .en(en), .q(q));
  always #5 clk = ~clk;
  initial begin
    repeat(3) @(posedge clk);
    rst_n = 1; #1;
    if (^q === 1'bx) $fatal(1, "output q is X after reset");
    $finish;
  end
endmodule
"""

CROSSING = """module mixed_clocks (
    input  logic       clk_a,
    input  logic       clk_b,
    input  logic       d_in
);
    logic [7:0] a_reg, b_reg, comb;
    always_ff @(posedge clk_a) begin a_reg <= d_in; end
    always_ff @(posedge clk_b) begin b_reg <= a_reg; end
    assign comb = a_reg + 1;
endmodule
"""


# ---- the block matcher ---------------------------------------------------
def test_a_clocked_block_is_matched_by_nesting():
    """A non-greedy regex to the first `end` stops inside the reset branch —
    exactly the part we need to see past."""
    blocks = _clocked_blocks(UNRESET)
    assert len(blocks) == 1
    assert "end else if" in blocks[0], "the whole block, not just the reset branch"


def test_the_flop_missing_from_reset_is_found():
    sigs = [s for s, _ in _unreset_flops(UNRESET)]
    assert sigs == ["q"]


def test_a_fully_reset_block_reports_nothing():
    src = """module ok(input logic clk, input logic rst_n, output logic q);
  always_ff @(posedge clk) begin
    if (!rst_n) q <= 1'b0;
    else q <= 1'b1;
  end
endmodule
"""
    assert _unreset_flops(src) == []


# ---- the suggestion ------------------------------------------------------
def test_the_reset_suggestion_inserts_inside_the_branch():
    """Dropping the trailing whitespace pasted the assignment onto the `end` line,
    producing a diff that would not compile."""
    import pathlib
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "cnt.sv").write_text(UNRESET)
    (d / "cnt_tb.sv").write_text(UNRESET_TB)
    rep = review(str(d))
    sug = [s for s in rep["suggestions"] if s.id == "reset-q"]
    if not sug:
        pytest.skip("no simulator, so no execution evidence")
    text = sug[0].new_text
    assert re.search(r"q <= 4'd0;\s*\n\s*end", text), text
    assert "end else if" in text


def test_the_width_comes_from_the_declaration():
    """`[3:0] q` in a port list has no trailing semicolon; a lookup that required
    one reset the signal to a single bit."""
    import pathlib
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "cnt.sv").write_text(UNRESET)
    (d / "cnt_tb.sv").write_text(UNRESET_TB)
    rep = review(str(d))
    sug = [s for s in rep["suggestions"] if s.id == "reset-q"]
    if not sug:
        pytest.skip("no simulator")
    assert "4'd0" in sug[0].new_text


def test_a_multibit_crossing_is_told_not_to_use_2ff():
    """2-FF settles each bit independently; it does not make a bus coherent."""
    import pathlib
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "m.sv").write_text(CROSSING)
    rep = review(str(d))
    cdc = [s for s in rep["suggestions"] if s.id.startswith("cdc-")]
    assert cdc, "the crossing should be reported"
    assert any("2-FF" in s.title or "2-FF" in s.why for s in cdc)
    assert any("gray" in s.why or "handshake" in s.why for s in cdc)


# ---- the honesty guards --------------------------------------------------
def test_nothing_is_suggested_when_no_check_ran(tmp_path):
    (tmp_path / "quiet.sv").write_text(
        "module quiet(input logic clk, output logic q);\n"
        "  always_ff @(posedge clk) q <= 1'b1;\nendmodule\n")
    rep = review(str(tmp_path))
    if rep["suggestions"]:
        pytest.skip("a check produced a real finding")
    assert "not the same as" in render(rep)


def test_an_empty_directory_says_so(tmp_path):
    rep = review(str(tmp_path))
    assert rep["suggestions"] == []
    assert any("no HDL files" in s for s in rep["skipped"])


def test_the_render_names_the_checks_that_ran():
    rep = {"ran": ["cdc", "simulation"], "suggestions": [], "skipped": []}
    assert "checks that ran: cdc, simulation" in render(rep)


# ---- the test that matters ----------------------------------------------
def test_applying_the_suggestion_turns_the_failure_into_a_pass(tmp_path):
    """A suggestion is worth nothing unless applying it fixes the check."""
    import shutil
    if not (shutil.which("iverilog") and shutil.which("vvp")):
        pytest.skip("iverilog/vvp not installed")

    (tmp_path / "cnt.sv").write_text(UNRESET)
    (tmp_path / "cnt_tb.sv").write_text(UNRESET_TB)

    from wengold.agent.runners import ToolRunner, Toolchain
    from wengold.cli import _collect
    from wengold.graph.builder import GraphBuilder
    from wengold.kernel.validity import Result

    def sim() -> str:
        g = GraphBuilder().build_from_files(_collect(str(tmp_path)),
                                            backend="auto")
        tr = ToolRunner(g, {"x": Result("x", "sim", depends_on={"cnt"})},
                        str(tmp_path), toolchain=Toolchain())
        return tr("x", "sim")["outcome"]

    assert sim() == "fail", "the design should fail before the fix"

    rep = review(str(tmp_path))
    sug = [s for s in rep["suggestions"] if s.id == "reset-q"]
    assert sug, "the failure should produce a suggestion"
    (tmp_path / "cnt.sv").write_text(sug[0].new_text)

    assert sim() == "pass", "applying the suggestion should fix the check"


# ---- the app -------------------------------------------------------------
def test_the_app_command_set_includes_review():
    from wengold.desktop import CLI_COMMANDS
    assert "review" in CLI_COMMANDS
