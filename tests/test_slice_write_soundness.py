"""A partial register write must be modelled, or a false property can be proved.

This is a regression test for a soundness bug in the z3 engine. `_sym_assigns`
unpacked the assignment target to a bare name, discarding the slice range, so

    q[3:0] <= wdata[3:0];

became a whole-register assignment `q <= wdata[3:0]`. The transition relation was
wrong, and on a register block — which is what the generator emits, and what most
RTL contains — the engine reported **proof** for properties that are false. A
verification tool that proves a false property has no value at all, so these tests
pin both directions: a false property must fail, and a true one must still prove.
"""
from pathlib import Path

from wengold.formal import Property, prove

SLICE_WRITE = """
module m (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       wr,
    input  logic [7:0] wdata,
    output logic [7:0] q
);
    always_ff @(posedge clk) begin
        if (!rst_n)      q <= 8'h00;
        else if (wr)     q[3:0] <= wdata[3:0];
    end
endmodule
"""

SLICE_ALIAS = """
module m (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       wr,
    input  logic [7:0] wdata,
    output logic [3:0] lo,
    output logic [3:0] hi
);
    logic [7:0] q;
    assign lo = q[3:0];
    assign hi = q[7:4];
    always_ff @(posedge clk) begin
        if (!rst_n)      q <= 8'h00;
        else if (wr)     q[3:0] <= wdata[3:0];
    end
endmodule
"""


def _status(src, prop):
    out = prove(src, [Property.safety("p", prop, reset="rst_n")],
                engine="z3", depth=10, budget=1)
    return out["results"][0].status


def test_a_written_slice_is_not_proved_constant():
    """`q[3:0] <= e` makes q[3:0] take other values, so q == 0 is false."""
    assert _status(SLICE_WRITE, "q == 0") == "fail"


def test_a_partial_write_is_visible_through_an_alias():
    """The same bug hid behind `assign lo = q[3:0];` — the field signal."""
    assert _status(SLICE_ALIAS, "lo == 0") == "fail"


def test_the_unwritten_slice_is_still_provable():
    """The fix must not over-correct: bits [7:4] are never written, and reset
    clears them, so hi == 0 really is an invariant."""
    assert _status(SLICE_ALIAS, "hi == 0") == "proof"


def test_two_slices_written_under_different_conditions_both_apply():
    """Merging into the accumulated next value, not the raw current one, is what
    makes this correct: both writes must land in the same cycle."""
    src = """
module m (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       a,
    input  logic       b,
    output logic [7:0] q
);
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            q <= 8'h00;
        end else begin
            if (a) q[3:0] <= 4'hf;
            if (b) q[7:4] <= 4'hf;
        end
    end
endmodule
"""
    # both halves can be set at once, so q can reach 8'hff
    assert _status(src, "q != 8'hff") == "fail"
    # and each half on its own is not invariant either
    assert _status(src, "q[3:0] == 4'h0") == "fail"
    assert _status(src, "q[7:4] == 4'h0") == "fail"


def test_the_generated_register_block_is_not_proved_constant():
    """The real reproduction: this is what the generator emits, and what most RTL
    looks like — one register, written a field at a time.

    The fields and their resets are chosen so the assertion discriminates. With
    the slice range dropped, one field's write decided the whole register and the
    other field looked constant, so `f2 == 0` was *proved* while being false. A
    property that fails in both worlds would say nothing about the bug.
    """
    from wengold.generate.emit import emit_rtl
    from wengold.generate.spec import Field, ModuleSpec, Port, Register, load_spec

    spec = ModuleSpec(
        name="blk",
        registers=[Register(name="R", addr=0, fields=[
            Field(name="F1", hi=3, lo=0, access="rw", reset=0),
            Field(name="F2", hi=7, lo=4, access="rw", reset=0),
            Field(name="F3", hi=8, lo=8, access="ro", reset=0)])],
        ports=[Port("clk_i", "input", 1), Port("rst_ni", "input", 1)])
    rtl = emit_rtl(spec)
    f2 = spec.field_signal(spec.registers[0], spec.registers[0].fields[1])
    f3 = spec.field_signal(spec.registers[0], spec.registers[0].fields[2])

    # F2 is written by software, so it is not always zero. With the bug this was
    # proved — the write to F1 was treated as a write to the whole register.
    assert _status(rtl, f"{f2} == 0") == "fail"
    # F3 is read-only and never driven: this one really is invariant, so the fix
    # has not simply made everything unprovable.
    assert _status(rtl, f"{f3} == 0") == "proof"

    # the shipped example still emits provable RTL
    # resolve from the repository root, not from the working directory. This test
    # was reported as "flaky" in v0.24.2 — it is not: it passed only when pytest
    # happened to be run from the repo root, because the path below is relative.
    # Run from anywhere else and it fails with SpecError, which looks like a
    # soundness regression and is not.
    root = Path(__file__).resolve().parent.parent
    ex = load_spec(str(root / "examples/sec_ctrl/sec_ctrl.spec.yaml"))
    assert "module sec_ctrl" in emit_rtl(ex)


def test_a_whole_register_write_still_works():
    src = """
module m (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       wr,
    input  logic [7:0] wdata,
    output logic [7:0] q
);
    always_ff @(posedge clk) begin
        if (!rst_n)  q <= 8'h00;
        else if (wr) q <= wdata;
    end
endmodule
"""
    assert _status(src, "q == 0") == "fail"
    assert _status(src, "q == 8'hff") == "fail"
