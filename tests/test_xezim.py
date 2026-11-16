"""Test the Xezim command, evidence classification and optional live replay."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from wengold.cli import main
from wengold.tools.adapters.xezim import XezimAdapter, _simulation_verdict
from wengold.tools.outcome import ToolOutcome, run_tool

FINISHED = "Simulation finished at time 26 ($finish called)"
UVM_ZERO = "--- UVM Report Summary ---\nUVM_ERROR : 0\nUVM_FATAL : 0"
EXAMPLE = Path(__file__).resolve().parents[1] / "examples/dv_workflow"


@pytest.mark.parametrize("log,rc,marker,uvm,want", [
    ("PASS\n" + FINISHED, 0, "PASS", False, ToolOutcome.PASS),
    (FINISHED, 0, None, False, ToolOutcome.INCONCLUSIVE),
    ("NOT PASS\n" + FINISHED, 0, "PASS", False, ToolOutcome.INCONCLUSIVE),
    (FINISHED + "\nPASS", 0, "PASS", False, ToolOutcome.INCONCLUSIVE),
    ("PASS\nSimulation finished at time 26", 0, "PASS", False, ToolOutcome.INCONCLUSIVE),
    ("[WARN] settle limit was exhausted 2 times\nPASS\n" + FINISHED, 0, "PASS", False,
     ToolOutcome.INCONCLUSIVE),
    ("Error: an unknown top", 1, None, False, ToolOutcome.ERROR),
    (FINISHED, 1, "PASS", False, ToolOutcome.FAIL),
    ("PASS\n" + FINISHED, 3, "PASS", False, ToolOutcome.ERROR),
    ("PASS\n" + FINISHED, -11, "PASS", False, ToolOutcome.ERROR),
    (UVM_ZERO + "\n" + FINISHED, 0, None, True, ToolOutcome.PASS),
    (UVM_ZERO.replace("ERROR : 0", "ERROR : 1") + "\n" + FINISHED, 0, None, True,
     ToolOutcome.FAIL),
    ("UVM_FATAL @ 0: reporter [INVTST]\n" + FINISHED, 0, None, True, ToolOutcome.FAIL),
    ("UVM_ERROR\n" + FINISHED, 0, None, True, ToolOutcome.FAIL),
    (UVM_ZERO.replace("UVM_FATAL : 0", "") + "\n" + FINISHED, 0, None, True,
     ToolOutcome.INCONCLUSIVE),
    ("UVM_ERROR : 0\nUVM_FATAL : 0\n" + FINISHED, 0, None, True, ToolOutcome.INCONCLUSIVE),
    (UVM_ZERO + "\n" + FINISHED, 0, "COUNTER4_UVM_PASS", True, ToolOutcome.INCONCLUSIVE),
])
def test_verdict_requires_evidence(log, rc, marker, uvm, want):
    assert _simulation_verdict(log, rc, pass_marker=marker, uvm=uvm) is want


@pytest.mark.skipif(os.name == "nt", reason="executable fixture uses a Unix shebang")
def test_cli_runs_ordered_sources_without_shell_and_records_binary(tmp_path, capsys, monkeypatch):
    fake = tmp_path / "xezim"
    fake.write_text(f"""#!{sys.executable}
import json
import os
import sys
if sys.argv[1:] == ["-V"]:
    print("xezim version 0.11.6")
else:
    print(json.dumps(sys.argv[1:]))
    assert "XEZIM_INIT_REG" not in os.environ
    print("PASS")
    print({FINISHED!r})
""")
    fake.chmod(0o755)
    (tmp_path / "ordinary.sv").touch()
    (tmp_path / "test with spaces.sv").touch()
    (tmp_path / "headers").mkdir()
    monkeypatch.setenv("XEZIM_INIT_REG", "random")
    assert main(["xezim", "--binary", str(fake), "--top", "tb", "--seed", "42",
                 "--project", str(tmp_path), "--pass-marker", "PASS", "--log", "results/run.log",
                 "-I", "headers", "-D", "ENABLE=1", "ordinary.sv", "test with spaces.sv"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["spec"]["version"] == "0.11.6" and result["spec"]["seed"] == 42
    expected = ["--simulate", "--strict-top", "--error-exit", "--no-cache", "-s", "tb",
                "-D", "ENABLE=1", "-I", str(tmp_path / "headers"),
                str(tmp_path / "ordinary.sv"), str(tmp_path / "test with spaces.sv"), "+seed=42"]
    assert json.loads(result["log"].splitlines()[0]) == expected
    assert (tmp_path / "results/run.log").read_text() == result["log"]


def test_timeout_with_partial_stdout_and_no_stderr(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda binary: binary)

    def expired(*args, **kwargs):
        raise subprocess.TimeoutExpired("xezim", 1, output=b"started\n")

    monkeypatch.setattr(subprocess, "run", expired)
    result = run_tool("xezim", [], timeout=1)
    assert result.outcome is ToolOutcome.TIMEOUT and result.log == "started\n"


def test_missing_binary_and_invalid_sources(tmp_path):
    (tmp_path / "tb.sv").touch()
    xezim = XezimAdapter(str(tmp_path / "missing-binary"))
    result = xezim.run(top="tb", files=["tb.sv"], cwd=tmp_path)
    assert result.outcome is ToolOutcome.TOOL_MISSING
    with pytest.raises(ValueError, match="project-relative"):
        xezim.run(top="tb", files=[str(tmp_path / "tb.sv")], cwd=tmp_path)
    with pytest.raises(ValueError, match="requires --uvm-dir"):
        xezim.run(top="tb", files=["tb.sv"], cwd=tmp_path, uvm_test="counter4_test")


@pytest.mark.skipif(shutil.which("xezim") is None, reason="Xezim is not installed")
def test_real_xezim_runs_self_checking_rtl(tmp_path):
    xezim = XezimAdapter()
    shutil.copytree(EXAMPLE / "rtl", tmp_path / "rtl")
    shutil.copytree(EXAMPLE / "tb", tmp_path / "tb")
    kwargs = dict(top="counter4_tb", files=["rtl/counter4.sv", "tb/counter4_tb.sv"],
                  cwd=tmp_path, pass_marker="REGRESSION_PASS")
    good = xezim.run(**kwargs)
    assert good.outcome is ToolOutcome.PASS, good.log
    assert "COVER:hold" in good.log
    tb = tmp_path / "tb/counter4_tb.sv"
    tb.write_text(tb.read_text().replace('4\'d1) $fatal(1, "INCREMENT_FAIL")',
                                        '4\'d7) $fatal(1, "INCREMENT_FAIL")'))
    bad = xezim.run(**kwargs)
    assert bad.outcome is ToolOutcome.FAIL and "INCREMENT_FAIL" in bad.log


@pytest.mark.skipif(shutil.which("xezim") is None, reason="Xezim is not installed")
def test_real_xezim_promotes_sv_error_even_with_pass_marker(tmp_path):
    (tmp_path / "tb.sv").write_text(
        'module tb; initial begin $error("CHECK_FAILED"); '
        '$display("PASS"); $finish; end endmodule\n')
    result = XezimAdapter().run(top="tb", files=["tb.sv"], cwd=tmp_path, pass_marker="PASS")
    assert result.outcome is ToolOutcome.FAIL, result.log
    assert "CHECK_FAILED" in result.log


@pytest.mark.skipif(not shutil.which("xezim") or not os.environ.get("WENGOLD_TEST_UVM_DIR"),
                    reason="requires Xezim and WENGOLD_TEST_UVM_DIR pointing to Accellera UVM")
def test_real_xezim_runs_uvm_and_rejects_a_scoreboard_error(tmp_path):
    xezim = XezimAdapter()
    shutil.copytree(EXAMPLE / "rtl", tmp_path / "rtl")
    shutil.copytree(EXAMPLE / "tb", tmp_path / "tb")
    kwargs = dict(top="counter4_uvm_tb", files=["rtl/counter4.sv", "tb/counter4_uvm_tb.sv"],
                  cwd=tmp_path, uvm_dir=os.environ["WENGOLD_TEST_UVM_DIR"],
                  uvm_test="counter4_test", pass_marker="COUNTER4_UVM_PASS",
                  defines=["UVM_NO_DPI", "UVM_REPORT_DISABLE_FILE_LINE"])
    good = xezim.run(**kwargs)
    assert good.outcome is ToolOutcome.PASS, good.log
    kwargs["defines"].append("INJECT_FAILURE")
    bad = xezim.run(**kwargs)
    assert bad.outcome is ToolOutcome.FAIL, bad.log
    assert "intentional mismatch" in bad.log


@pytest.mark.skipif(os.name == "nt" or shutil.which("xezim") is None,
                    reason="requires Xezim and the Unix Wengold launcher")
def test_real_xezim_regression_manifest_records_fresh_evidence(tmp_path, monkeypatch):
    from wengold.dv_pipeline import run_regression

    # Exercise the same manifest path as the Studio's DV Workflow tab.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launcher = bin_dir / "wengold"
    script = EXAMPLE.parents[1] / "wengold.sh"
    import shlex
    launcher.write_text(f'#!/bin/sh\nexec sh {shlex.quote(str(script))} "$@"\n')
    launcher.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bin_dir), os.environ["PATH"]]))

    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project)
    report = run_regression(project, "flows/xezim.json")
    assert report["ok"], report.get("log")
    assert report["gate"] == "tool_evidence_present"
    log = project / "results/xezim.log"
    assert "REGRESSION_PASS" in log.read_text()

    tb = project / "tb/counter4_tb.sv"
    tb.write_text(tb.read_text().replace("REGRESSION_PASS", "NO_COMPLETION_MARKER"))
    report = run_regression(project, "flows/xezim.json")
    assert not report["ok"]
    assert report["gate"] == "failed_or_missing_evidence"
    assert "REGRESSION_PASS" not in log.read_text()
