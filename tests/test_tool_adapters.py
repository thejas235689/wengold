"""Tool adapters, checked against the option strings real tools accept.

These were all wrong until the adapters were run against actual verilator,
yosys, sby and cocotb — which is why they are pinned here.
"""
from wengold.tools import adapters
from wengold.tools.adapters import cocotb as cocotb_mod
from wengold.tools.adapters import symbiyosys as sby_mod
from wengold.tools.adapters import verilator as vl_mod
from wengold.tools.adapters import yosys as yosys_mod
from wengold.tools.outcome import Outcome, ToolOutcome, outcome_from_cocotb


def _capture(monkeypatch, module):
    """Record the argv a adapter passes to run_tool, without running anything."""
    seen = {}

    def fake(binary, argv, **kw):
        seen["binary"] = binary
        seen["argv"] = list(argv)
        seen["kw"] = kw
        return Outcome(kw.get("tool", binary), kw.get("action", "run"), ToolOutcome.PASS)

    monkeypatch.setattr(module, "run_tool", fake)
    return seen


# ---- verilator ---------------------------------------------------------
def test_verilator_lint_has_no_bare_werror(monkeypatch):
    seen = _capture(monkeypatch, vl_mod)
    vl_mod.VerilatorAdapter().lint(top="counter", files=["counter.sv"])
    assert "-Werror" not in seen["argv"]          # verilator rejects it
    assert "--lint-only" in seen["argv"] and "--top-module" in seen["argv"]


def test_verilator_warnings_as_errors_off_uses_wno_fatal(monkeypatch):
    seen = _capture(monkeypatch, vl_mod)
    vl_mod.VerilatorAdapter().lint(top="t", files=["t.sv"], warnings_as_errors=False)
    assert "-Wno-fatal" in seen["argv"]
    assert "-Werror" not in seen["argv"]


# ---- yosys -------------------------------------------------------------
def test_yosys_reads_systemverilog(monkeypatch):
    seen = _capture(monkeypatch, yosys_mod)
    yosys_mod.YosysAdapter().synthesize(top="counter", files=["counter.sv"])
    script = seen["argv"][seen["argv"].index("-p") + 1]
    assert script.startswith("read_verilog -sv ")   # -sv is required for `logic`
    assert "synth -top counter" in script


# ---- sby ---------------------------------------------------------------
def test_sby_verdict_comes_from_status_not_rc():
    from wengold.tools.outcome import parse_sby_status
    assert parse_sby_status("SBY [t] DONE (PASS, rc=0)") is ToolOutcome.PASS
    assert parse_sby_status("SBY [t] DONE (FAIL, rc=2)") is ToolOutcome.FAIL
    assert parse_sby_status("SBY [t] DONE (UNKNOWN, rc=0)") is ToolOutcome.INCONCLUSIVE


# ---- cocotb: the counts -> outcome mapping -----------------------------
def test_failing_testbench_is_not_a_pass():
    counts = {"tests": 1, "passed": 0, "failures": 1, "errors": 0, "skipped": 0}
    assert outcome_from_cocotb(counts, ToolOutcome.PASS) is ToolOutcome.FAIL


def test_passing_testbench_is_a_pass():
    counts = {"tests": 1, "passed": 1, "failures": 0, "errors": 0, "skipped": 0}
    assert outcome_from_cocotb(counts, ToolOutcome.INCONCLUSIVE) is ToolOutcome.PASS


def test_no_results_is_never_a_pass():
    # an exit code of 0 with nothing parsed proves nothing
    assert outcome_from_cocotb({}, ToolOutcome.PASS) is not ToolOutcome.PASS


def test_cocotb_available_without_make_when_runner_present(monkeypatch):
    # a stand-in for cocotb, so this does not depend on it being installed here
    import sys
    import types
    monkeypatch.setitem(sys.modules, "cocotb", types.SimpleNamespace())
    monkeypatch.setattr(cocotb_mod, "_runner_available", lambda: True)
    monkeypatch.setattr(cocotb_mod.shutil, "which", lambda _n: None)   # no make, no sim
    assert cocotb_mod.CocotbAdapter().available() is True


def test_cocotb_run_reports_tool_missing_without_make_or_runner(monkeypatch):
    monkeypatch.setattr(cocotb_mod, "_runner_available", lambda: False)
    monkeypatch.setattr(cocotb_mod.shutil, "which", lambda _n: None)
    o = cocotb_mod.CocotbAdapter().run(workdir="/tmp", toplevel="t")
    assert o.outcome is ToolOutcome.TOOL_MISSING
    assert o.spec.get("binary") == "make"
