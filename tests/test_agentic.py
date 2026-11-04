"""Agentic coding: a loop with no model in it.

The tests here pin the two things that make this honest rather than impressive:

  * **every step names the fact that caused it** — a step without a fact is a
    guess wearing a lab coat;
  * **it stops when nothing is justified** — the failure mode of an agent without
    a model is inventing a fifth action, and the failure mode of one *with* a model
    is the same thing said more fluently.

There is one regression test worth naming: `propose_stubs` used to stub
`completeness()["unresolved"]`, which lists the modules that *contain* an unresolved
instantiation — the dependents, which are defined and fine. It wrote a second
definition of a module that already existed.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from wengold.agent.coding import CodingRun, code, render
from wengold.agent.propose import missing_modules, propose_stubs

ROOT = Path(__file__).resolve().parent.parent

TOP_WITH_MISSING = """\
module top(input logic clk, input logic rst_n, output logic q);
  logic inner;
  missing_block u_missing(.clk(clk), .rst_n(rst_n), .q(inner));
  assign q = inner;
endmodule
"""

CLEAN = """\
module solo(input logic c, output logic q);
  assign q = c;
endmodule
"""


@pytest.fixture
def broken(tmp_path):
    (tmp_path / "top.sv").write_text(TOP_WITH_MISSING)
    return tmp_path


@pytest.fixture
def clean(tmp_path):
    (tmp_path / "solo.sv").write_text(CLEAN)
    return tmp_path


# ---- the fact that makes the fix possible -------------------------------
def test_missing_modules_are_not_the_unresolved_dependents(broken):
    """`unresolved` names `top` — which is defined. The stub target is
    `missing_block`, which is not."""
    from wengold.desktop import build_state

    completeness = build_state(str(broken))["graph"].completeness()
    assert completeness["unresolved"] == ["top"], "the dependent is what is flagged"
    assert missing_modules(completeness) == ["missing_block"]


def test_a_stub_is_never_proposed_for_a_module_that_exists(broken):
    """The regression. A stub for `top` would be a duplicate definition."""
    from wengold.desktop import build_state

    state = build_state(str(broken))
    prop = propose_stubs(state["graph"], state["graph"].completeness())
    assert prop is not None
    declared = [ln.split()[1].split("(")[0]
                for ln in (prop.new_text or "").splitlines()
                if ln.startswith("module ")]
    assert declared == ["missing_block"], declared
    assert "top" not in declared


# ---- the loop -----------------------------------------------------------
def test_it_proposes_a_diff_and_writes_nothing_by_default(broken):
    run = code("make this design verify", str(broken))
    assert run.steps, "it should have found something to do"
    assert run.changed
    assert not run.applied
    assert not (broken / "wengold_stubs.sv").exists()
    assert "nothing was written" in run.render()


def test_it_writes_with_apply_and_then_says_what_is_left(broken):
    """The stub is written and the design elaborates, but the kernel still marks
    results open — so `done` would be a claim the tool cannot support."""
    run = code("make this design verify", str(broken), apply=True)
    assert run.applied
    assert (broken / "wengold_stubs.sv").exists()
    assert "no kernel-justified action" in run.reason, run.reason


def test_without_apply_it_stops_after_one_diff(broken):
    """Nothing changed, so re-perceiving would find the same fact. Repeating it
    six times is a stutter, not a loop."""
    run = code("make this design verify", str(broken), max_steps=6)
    assert len(run.steps) == 1, [s.thought for s in run.steps]


def test_a_clean_design_takes_no_steps_and_says_what_is_open(clean):
    """It used to report `done` here, and `done` was a false claim: `_failed` read
    `.verdict` off plain dicts, always got None, and the loop announced "no result
    invalidated" while the kernel had marked one INVALIDATED.

    The honest report is that nothing needs *fixing* (no unresolved module, no
    actionable failure) and one result is still open.
    """
    run = code("make this design verify", str(clean))
    assert run.steps == [], "a clean design needs no action"
    assert "no kernel-justified action" in run.reason
    assert "not valid" in run.reason, "name what is open rather than hiding it"


def test_a_missing_directory_stops_with_a_reason(tmp_path):
    run = code("anything", str(tmp_path / "nope"))
    assert not run.done
    assert "does not exist" in run.reason


# ---- the honesty guarantees --------------------------------------------
def test_every_step_names_the_fact_that_caused_it(broken):
    run = code("make this design verify", str(broken))
    for s in run.steps:
        assert s.fact.strip(), f"step {s.n} has no fact behind it"
        assert s.action.strip(), f"step {s.n} has no action"


def test_the_report_says_there_is_no_model(broken):
    text = code("make this design verify", str(broken)).render()
    assert "none is a model's guess" in text
    assert "does not write RTL logic" in text


def test_the_goal_is_carried_through(tmp_path):
    run = code("stub the vendor IP", str(tmp_path))
    assert run.goal == "stub the vendor IP"
    assert "stub the vendor IP" in run.render()


# ---- the app and the CLI ------------------------------------------------
def test_the_app_accepts_the_agent_command():
    from wengold.desktop import CLI_COMMANDS

    assert "agentic" in CLI_COMMANDS


def test_the_app_agent_command_runs_and_shows_the_trace(broken):
    from wengold.desktop import _exec, build_state

    out = _exec(build_state(str(broken)), "agentic")
    assert out["ok"]
    assert "fact:" in out["output"]


def test_the_app_agent_never_writes(broken):
    """The pane shows the diff; only the CLI takes it."""
    from wengold.desktop import _exec, build_state

    _exec(build_state(str(broken)), "agentic")
    assert not (broken / "wengold_stubs.sv").exists()


def test_vibe_and_review_are_still_there():
    """The point was to keep both, not to replace one with the other."""
    from wengold.desktop import CLI_COMMANDS

    assert "vibe" in CLI_COMMANDS
    assert "review" in CLI_COMMANDS
    assert "agentic" in CLI_COMMANDS


def test_the_cli_has_both_agentic_and_the_six_stage_agent():
    """`agentic` is the coding loop; `agent` is the older six-stage loop. They were
    briefly the same name, and one shadowed the other."""
    r = subprocess.run([sys.executable, "-m", "wengold.cli", "--help"],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert "agentic" in r.stdout
    assert "agent " in r.stdout or "agent\n" in r.stdout


def test_only_one_cmd_agent_is_defined():
    """Two functions with the same name in one module means the first is dead."""
    src = (ROOT / "wengold" / "cli.py").read_text()
    assert src.count("def cmd_agent(args)") == 1
