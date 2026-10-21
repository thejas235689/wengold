"""Agents: test generation, debugging, repair, and a complete verification loop."""
from wengold.agents.debugger import Debugger
from wengold.agents.orchestrator import Orchestrator
from wengold.agents.repair import Repairer
from wengold.agents.testgen import Port, TestGen
from wengold.demo import build_graph, prior_results
from wengold.ledger.store import Ledger
from wengold.tools.outcome import Outcome, ToolOutcome


# ---- test generation ---------------------------------------------------
def test_cocotb_testbench_is_runnable_shaped():
    ports = [Port("clk", "input"), Port("a", "input", 8),
             Port("y", "output", 8)]
    tb = TestGen().cocotb_testbench("alu", ports, clock="clk", reset="rst_n")
    assert "async def smoke" in tb
    assert "dut.a.value = random.getrandbits(8)" in tb
    assert "RisingEdge(dut.clk)" in tb
    assert 'dut.y' in tb


def test_sva_assertion():
    s = TestGen().assertion("a1", "m", "y == a + b")
    assert "assert property" in s and "a1" in s


# ---- debugging ---------------------------------------------------------
def test_debugger_tool_missing():
    d = Debugger().investigate(Outcome("vcs", "run", ToolOutcome.TOOL_MISSING))
    assert d["category"] == "tool_missing"


def test_debugger_elaboration_error_locates_file():
    out = Outcome("vcs", "run", ToolOutcome.FAIL, rc=1,
                  log="rtl/foo.sv:12: syntax error near 'endmodule'")
    d = Debugger().investigate(out)
    assert d["category"] == "elaboration_error"
    assert d["file"] == "rtl/foo.sv" and d["line"] == 12


def test_debugger_timeout_and_counterexample():
    assert Debugger().investigate(
        Outcome("sby", "prove", ToolOutcome.TIMEOUT))["category"] == "timeout"
    assert Debugger().investigate(
        Outcome("sby", "prove", ToolOutcome.FAIL,
                log="counterexample found"))["category"] == "formal_counterexample"


# ---- repair ------------------------------------------------------------
def test_repairer_missing_tool_has_no_diff():
    p = Repairer().propose({"category": "tool_missing"})
    assert p["find"] is None and p["confidence"] > 0.5


def test_repairer_applies_literal_edit():
    rp = Repairer()
    text = "assign q = a & b;"
    p = {"find": "a & b", "replace": "a | b"}
    assert rp.apply(text, p) == "assign q = a | b;"
    assert p["applied"] is True


def test_repairer_undeclared_signal_proposal():
    p = Repairer().propose({"category": "elaboration_error",
                            "log": "error: undeclared identifier `tmp`"})
    assert p["kind"] == "declare_signal" and "tmp" in p["replace"]


# ---- the loop ----------------------------------------------------------
def test_orchestrator_loop_runs_and_records(tmp_path):
    graph = build_graph()
    ledger = Ledger(tmp_path / "l.tof")
    orch = Orchestrator(graph, ledger, workdir=str(tmp_path))

    def runner(rid, kind):
        if kind in ("sim", "coverage"):
            return Outcome("cocotb", "run", ToolOutcome.PASS)
        return Outcome("symbiyosys", "prove", ToolOutcome.TOOL_MISSING)

    report = orch.run_loop({"sec_firewall"}, prior_results(), runner=runner, max_iters=2)
    assert "sec_acl_test" in report["rerun"]
    assert "a_secure_bit" in report["unsettled"]        # no engine -> reported
    assert report["settled"] is False
    assert ledger.verify() is True
    kinds = {r["kind"] for r in ledger}
    assert {"verdict", "run", "evidence", "loop_end"} <= kinds


def test_orchestrator_loop_settles_when_all_pass(tmp_path):
    graph = build_graph()
    ledger = Ledger(tmp_path / "l.tof")
    orch = Orchestrator(graph, ledger, workdir=str(tmp_path))
    report = orch.run_loop({"sec_firewall"}, prior_results(),
                           runner=lambda rid, kind: Outcome(kind, "run", ToolOutcome.PASS))
    assert report["settled"] is True
    assert report["unsettled"] == []
