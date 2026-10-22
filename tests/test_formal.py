"""Formal verification: the IR, the RTL front-end, both engines and the loop."""
import pytest

from wengold.formal import (Property, PropertyKind, UnsupportedConstruct, parse_module,
                            prove, to_model)
from wengold.formal.engine import FormalStatus, check, explicit_check, z3_check
from wengold.formal.ir import sva_module
from wengold.kernel.contract import Establishes, MethodKind

COUNTER = """
module counter (input logic clk, input logic rst_n, input logic en);
    parameter MAX = 4;
    logic [2:0] count;
    always_ff @(posedge clk) begin
        if (!rst_n) count <= 0;
        else if (en) count <= (count == MAX) ? 0 : count + 1;
    end
endmodule
"""

SHIFT = """
module shift (input logic clk, input logic din);
    logic [3:0] sr;
    always_ff @(posedge clk) sr <= (sr << 1) | din;
endmodule
"""

UNBOUNDED = """
module counter_bad (input logic clk, input logic rst_n, input logic en);
    parameter MAX = 4;
    logic [2:0] count;
    always_ff @(posedge clk) begin
        if (!rst_n) count <= 0;
        else if (en) count <= count + 1;
    end
endmodule
"""

UNSUPPORTED = """
module weird (input logic clk);
    logic [7:0] mem [0:15];
    always_ff @(posedge clk) mem[0] <= 8'd1;
endmodule
"""


def _model(text):
    return to_model(parse_module(text))


# ---- IR -----------------------------------------------------------------
def test_property_ir_and_sva():
    p = Property.safety("bound", "count <= MAX", clock="clk", reset="rst_n")
    sva = p.to_sva()
    assert "assert property" in sva and "posedge clk" in sva and "disable iff (!rst_n)" in sva
    assert Property.cover("c", "x == 1").kind is PropertyKind.COVER
    assert Property.assume("a", "en == 1").kind is PropertyKind.ASSUME
    mod = sva_module("counter", [p])
    assert "module counter_props;" in mod
    assert p.digest().startswith("sha256:")


# ---- front-end ----------------------------------------------------------
def test_parse_module_structure():
    rtl = parse_module(COUNTER)
    assert rtl.name == "counter"
    assert sorted(rtl.registered) == ["count"]
    assert sorted(rtl.inputs) == ["en", "rst_n"]        # clk is not enumerated
    assert rtl.params == {"MAX": 4}
    assert rtl.signals["count"] == 3


def test_model_stepping():
    m = _model(COUNTER)
    assert m.state0 == {"count": 0}
    nxt = m.step({"count": 4}, {"en": 1, "rst_n": 1})
    assert nxt["count"] == 0                            # wraps at MAX
    assert m.step({"count": 2}, {"en": 0, "rst_n": 1})["count"] == 2
    assert m.step({"count": 3}, {"en": 1, "rst_n": 0})["count"] == 0


def test_unsupported_construct_is_explicit():
    with pytest.raises(UnsupportedConstruct):
        parse_module(UNSUPPORTED)
    with pytest.raises(UnsupportedConstruct):
        parse_module("module m; always_comb y = a & b; endmodule")


# ---- explicit engine ----------------------------------------------------
def test_explicit_proves_and_covers():
    props = [Property.safety("bound", "count <= MAX", clock="clk"),
             Property.cover("wrap", "count == MAX", clock="clk")]
    res = {r.property: r for r in explicit_check(_model(COUNTER), props)}
    assert res["bound"].status is FormalStatus.PROOF
    assert res["bound"].establishes is Establishes.PROOF
    assert res["wrap"].status is FormalStatus.PROOF


def test_explicit_finds_counterexample():
    props = [Property.safety("bound", "count <= MAX", clock="clk")]
    r = explicit_check(_model(UNBOUNDED), props)[0]
    assert r.status is FormalStatus.FAIL
    assert r.trace and len(r.trace) >= 2
    assert r.establishes is Establishes.NONE


def test_explicit_bounded_when_state_cap_hits():
    props = [Property.safety("s", "sr != 15", clock="clk")]
    r = explicit_check(_model(SHIFT), props, max_states=2)[0]
    assert r.status in (FormalStatus.BOUNDED, FormalStatus.FAIL)


# ---- z3 engine ----------------------------------------------------------
HAVE_Z3 = z3_check.__module__ and __import__("wengold.formal.engine", fromlist=["_HAVE_Z3"])._HAVE_Z3


@pytest.mark.skipif(not HAVE_Z3, reason="z3 not installed")
def test_z3_proves_by_induction():
    props = [Property.safety("bound", "count <= MAX", clock="clk")]
    r = z3_check(_model(COUNTER), props, depth=8)[0]
    assert r.status is FormalStatus.PROOF
    assert r.establishes is Establishes.PROOF


@pytest.mark.skipif(not HAVE_Z3, reason="z3 not installed")
def test_z3_finds_counterexample_and_masks_inputs():
    props = [Property.safety("bound", "count <= MAX", clock="clk")]
    r = z3_check(_model(UNBOUNDED), props, depth=8)[0]
    assert r.status is FormalStatus.FAIL
    # inputs are reported at their declared width, not the solver's
    assert all(v in (0, 1) for step in r.trace for v in step["inputs"].values())


@pytest.mark.skipif(not HAVE_Z3, reason="z3 not installed")
def test_engines_agree():
    props = [Property.safety("bound", "count <= MAX", clock="clk"),
             Property.cover("wrap", "count == MAX", clock="clk")]
    m = _model(COUNTER)
    ex = {r.property: r.status for r in explicit_check(m, props)}
    z3r = {r.property: r.status for r in z3_check(m, props, depth=8)}
    assert ex == z3r


# ---- the loop -----------------------------------------------------------
def test_loop_proves_a_good_design():
    out = prove(COUNTER, [Property.safety("bound", "count <= MAX", clock="clk")],
                engine="explicit")
    assert out["proved"] is True
    assert out["counterexamples"] == []
    c = out["contracts"][0]
    assert c.method.kind is MethodKind.PROOF
    assert out["result_objects"][0].establishes is Establishes.PROOF
    assert "module counter_props;" in out["sva"]


def test_loop_repairs_on_counterexample():
    def repair(text, failure):
        return text.replace("else if (en) count <= count + 1;",
                            "else if (en) count <= (count == MAX) ? 0 : count + 1;")

    out = prove(UNBOUNDED, [Property.safety("bound", "count <= MAX", clock="clk")],
                engine="explicit", repair=repair, budget=3)
    assert out["repaired"] is True
    assert out["proved"] is True
    assert len(out["iterations"]) == 2


def test_loop_records_to_ledger(tmp_path):
    from wengold.ledger.store import Ledger
    led = Ledger(tmp_path / "l.tof")
    prove(UNBOUNDED, [Property.safety("b", "count <= MAX", clock="clk")],
          engine="explicit", ledger=led)
    kinds = {r["kind"] for r in led}
    assert {"formal_run", "formal_end"} <= kinds
    assert led.verify() is True


def test_loop_reports_unknown_for_unparsable():
    out = prove(UNSUPPORTED, [Property.safety("x", "1'b1", clock="clk")])
    assert out["results"][0].status == "unknown"
    assert out["proved"] is False
