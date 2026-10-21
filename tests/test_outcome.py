"""Tool outcomes must distinguish missing, timeout, crash, fail and inconclusive."""
from wengold.tools.outcome import (Outcome, ToolOutcome, outcome_from_cocotb,
                                   parse_cocotb_results, parse_sby_status, run_tool)


def test_missing_tool():
    o = run_tool("definitely-not-a-real-binary-xyz", [])
    assert o.outcome is ToolOutcome.TOOL_MISSING
    assert o.verdict() == "tool_missing"


def test_timeout_is_not_a_pass_or_fail():
    o = run_tool("python3", ["-c", "import time; time.sleep(5)"], timeout=0.3)
    assert o.outcome is ToolOutcome.TIMEOUT
    assert o.verdict() == "timeout"


def test_pass_and_fail_from_rc():
    assert run_tool("python3", ["-c", "raise SystemExit(0)"]).outcome is ToolOutcome.PASS
    assert run_tool("python3", ["-c", "raise SystemExit(1)"]).outcome is ToolOutcome.FAIL


def test_interpret_override_wins():
    o = run_tool("python3", ["-c", "raise SystemExit(0)"],
                 interpret=lambda log, rc: ToolOutcome.INCONCLUSIVE)
    assert o.outcome is ToolOutcome.INCONCLUSIVE


def test_sby_status_parsing():
    assert parse_sby_status("... DONE (PASS, rc=0)") is ToolOutcome.PASS
    assert parse_sby_status("... DONE (FAIL, rc=1)") is ToolOutcome.FAIL
    assert parse_sby_status("... DONE (UNKNOWN, rc=2)") is ToolOutcome.INCONCLUSIVE
    assert parse_sby_status("Status: PASS") is ToolOutcome.PASS
    assert parse_sby_status("nothing useful here") is None


def test_cocotb_results_parsing(tmp_path):
    xml = tmp_path / "results.xml"
    xml.write_text('<?xml version="1.0"?><testsuite name="c" tests="4" failures="1" '
                   'errors="0" skipped="1"><testcase name="a"/></testsuite>')
    counts = parse_cocotb_results(xml)
    assert counts["tests"] == 4 and counts["failures"] == 1 and counts["passed"] == 2
    assert outcome_from_cocotb(counts, ToolOutcome.PASS) is ToolOutcome.FAIL
    assert outcome_from_cocotb({"tests": 0, "failures": 0, "errors": 0, "skipped": 0,
                                "passed": 0}, ToolOutcome.PASS) is ToolOutcome.INCONCLUSIVE
    assert parse_cocotb_results(tmp_path / "nope.xml") is None


def test_outcome_verdict_mapping():
    assert Outcome("t", "a", ToolOutcome.INCONCLUSIVE).verdict() == "unknown"
    assert Outcome("t", "a", ToolOutcome.ERROR).verdict() == "error"
    assert Outcome("t", "a", ToolOutcome.PASS).settled is True
