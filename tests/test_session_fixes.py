"""The nine fixes from a seven-role verification run.

Each of these was a bad failure mode rather than a wrong answer: a false statement
about the environment, a raw traceback, advice blaming the wrong thing, an engine
that inverted logic, a runner that passed a vacuous testbench, a generator that
emitted uncompilable code, and a pane that styled an answer as a failure.
"""
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# 1 -------------------------------------------------------------------------
def test_the_regex_backend_does_not_blame_a_missing_pyslang():
    from wengold.graph.builder import GraphBuilder
    g = GraphBuilder().build_from_files(
        {"m.sv": "module m(input logic c, output logic q);\n assign q=c;\nendmodule\n"},
        backend="regex")
    notes = " ".join(g.notes)
    assert "not installed" not in notes, notes
    assert "regex backend was requested" in notes, notes


# 2 -------------------------------------------------------------------------
def test_a_z3_sort_mismatch_is_reported_not_raised():
    rtl = REPO / "examples/soc_top/rtl/sec_firewall.sv"
    if not rtl.exists():
        pytest.skip("example absent")
    r = subprocess.run([sys.executable, "-m", "wengold.cli", "formal", str(rtl),
                        "--property", "deny == addr[31]", "--engine", "z3"],
                       cwd=REPO, capture_output=True, text=True, timeout=180,
                       env={"PYTHONPATH": str(REPO), "PATH": "/usr/local/bin:/usr/bin:/bin"})
    out = r.stdout + r.stderr
    assert "Traceback" not in out
    assert "Z3Exception" not in out


# 3 -------------------------------------------------------------------------
def test_a_system_function_is_not_blamed_on_a_signal_name():
    rtl = REPO / "examples/soc_top/rtl/sec_firewall.sv"
    if not rtl.exists():
        pytest.skip("example absent")
    r = subprocess.run([sys.executable, "-m", "wengold.cli", "formal", str(rtl),
                        "--property", "$isunknown(deny) == 0"],
                       cwd=REPO, capture_output=True, text=True, timeout=180,
                       env={"PYTHONPATH": str(REPO), "PATH": "/usr/local/bin:/usr/bin:/bin"})
    out = r.stdout + r.stderr
    assert "system function" in out, out


# 4 -------------------------------------------------------------------------
def test_the_explicit_engine_refuses_negation_instead_of_inverting_it():
    from wengold.formal.rtl_model import UnsupportedConstruct, eval_int
    ast = ("un", "~", ("id", "a"))
    with pytest.raises(UnsupportedConstruct):
        eval_int(ast, {"a": 1}, {})


# 5 -------------------------------------------------------------------------
def test_a_constant_false_guard_is_not_a_pass():
    from wengold.agent.runners import ToolRunner
    tb = 'module t; initial begin\n  if (1\'b0) $fatal(1, "never");\nend endmodule\n'
    assert ToolRunner.DEAD_GUARD.search(tb), "a dead guard must be detected"
    live = 'module t; initial begin\n  if (q !== 1\'b0) $fatal(1, "real");\nend endmodule\n'
    assert not ToolRunner.DEAD_GUARD.search(live), "a live check must not be flagged"


# 6 -------------------------------------------------------------------------
def test_the_generated_testbench_drives_the_clock_the_module_declares():
    from wengold.vibe import make_testbench

    class P:
        def __init__(self, n, d, w=1):
            self.name, self.direction, self.width = n, d, w

    class S:
        name = "dma"
        ports = [P("clk", "input"), P("rst_n", "input"), P("deny", "output")]
        registers = []

    tb = make_testbench(S())
    assert "always #5 clk = ~clk;" in tb, tb
    assert "clk_i" not in tb
    assert "rst_ni" not in tb


# 7 -------------------------------------------------------------------------
def test_the_pane_renders_summary_as_a_table(tmp_path):
    from wengold.desktop import _exec, build_state
    (tmp_path / "m.sv").write_text("module m(input logic c, output logic q);\n assign q=c;\nendmodule\n")
    out = _exec(build_state(str(tmp_path)), "summary")["output"]
    assert out.splitlines()[0].strip().startswith("metric")
    assert "files 1  nodes" not in out


# 8 -------------------------------------------------------------------------
def test_explain_succeeds_without_a_model(tmp_path, monkeypatch):
    from wengold.desktop import _exec, build_state
    monkeypatch.delenv("WENGOLD_LLM_MODEL", raising=False)
    (tmp_path / "m.sv").write_text("module m; endmodule\n")
    r = _exec(build_state(str(tmp_path)), "explain")
    assert r["ok"] is True, r
    assert r.get("kind") == "note", r


def test_an_unknown_command_is_an_error_and_a_usage_hint_is_not(tmp_path):
    from wengold.desktop import _exec, build_state
    (tmp_path / "m.sv").write_text("module m; endmodule\n")
    st = build_state(str(tmp_path))
    assert _exec(st, "nosuchcmd").get("kind") == "error"
    assert _exec(st, "vibe").get("kind") == "usage"


# 9 -------------------------------------------------------------------------
def test_ci_covers_more_than_one_system():
    import yaml
    p = REPO / ".github/workflows/ci.yml"
    if not p.exists():
        pytest.skip("no workflow")
    d = yaml.safe_load(p.read_text())
    oses = d["jobs"]["test"]["strategy"]["matrix"]["os"]
    assert len(oses) >= 2, oses
    assert "install" in d["jobs"], "the installer must be tested"
    assert "no-dependencies" in d["jobs"], "the zero-install claim must be tested"
