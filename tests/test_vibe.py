"""Vibe coding: describe it, get RTL, and see it simulated.

The value is not that a sentence becomes Verilog. It is that **nothing reaches you
unverified** — the generated block is simulated, and its registers are written and
read back before you see it.

The tests are mostly about the testbench the module generates, because a generated
checker that cannot fail is worse than no checker: it reports every design as
correct. Several of these exist because the first version was vacuous.

Both inputs — a YAML spec and a sentence — are loaded through the same path and end
up as a `ModuleSpec`, so the testbench is built from one representation rather than
two dict shapes that could drift apart.
"""
import re

import pytest

from wengold.generate.spec import load_spec
from wengold.vibe import _masks, make_testbench, render, vibe

# `match_o` needs a driver: an output nothing drives is X after reset, and the
# generated testbench correctly fails it. The first version of this fixture had
# that bug and the checker caught it.
TIMER_YAML = """
module: timer
clock: clk_i
reset: rst_ni
ports:
  - {name: clk_i, dir: input, width: 1}
  - {name: rst_ni, dir: input, width: 1}
  - {name: tick_i, dir: input, width: 1}
  - {name: match_o, dir: output, width: 1}
assigns:
  - {target: match_o, expr: "tick_i"}
"""

REGS_YAML = """
module: regs
clock: clk_i
reset: rst_ni
ports:
  - {name: clk_i, dir: input, width: 1}
  - {name: rst_ni, dir: input, width: 1}
registers:
  - name: CTRL
    addr: 0x0
    fields:
      - {name: EN, bits: "0", access: rw, reset: 0}
      - {name: MODE, bits: "3:1", access: rw, reset: 3}
  - name: IRQ
    addr: 0x4
    fields:
      - {name: PENDING, bits: "0", access: w1c, reset: 0}
  - name: STATUS
    addr: 0x8
    fields:
      - {name: COUNT, bits: "15:0", access: ro, reset: 0}
"""


def mspec(tmp_path, text):
    """A ModuleSpec through the same loader `vibe` uses."""
    p = tmp_path / "s.yaml"
    p.write_text(text)
    return load_spec(str(p))


# ---- the masks -----------------------------------------------------------
def test_rw_w1c_and_ro_are_separated(tmp_path):
    """`w1c` must not be treated as `rw`: writing 1 clears, it does not store."""
    s = mspec(tmp_path, REGS_YAML)
    ctrl, irq, status = s.registers

    m = _masks(ctrl)
    assert m["rw"] == 0b1111 and m["w1c"] == 0 and m["ro"] == 0

    i = _masks(irq)
    assert i["w1c"] == 1 and i["rw"] == 0

    st = _masks(status)
    assert st["ro"] == 0xFFFF and st["rw"] == 0


def test_reset_values_come_from_the_fields(tmp_path):
    s = mspec(tmp_path, REGS_YAML)
    assert _masks(s.registers[0])["reset"] == 0b0110, "MODE resets to 3 in bits 3:1"


# ---- the generated testbench --------------------------------------------
def test_a_block_without_a_bus_gets_no_register_tasks(tmp_path):
    """Emitting write/read tasks for ports that do not exist is a testbench that
    cannot compile — which reads as 'the generated RTL is broken'."""
    s = mspec(tmp_path, TIMER_YAML)
    tb = make_testbench(s, s.all_ports)
    assert "task automatic wr" not in tb
    assert "reg_wr_i" not in tb
    assert "$fatal" in tb, "it must still be able to fail"


def test_a_block_with_a_bus_gets_register_tasks(tmp_path):
    s = mspec(tmp_path, REGS_YAML)
    tb = make_testbench(s, s.all_ports)
    assert "task automatic wr" in tb and "task automatic rd" in tb
    assert "reg_wdata_i" in tb


def test_the_bus_comes_from_the_module_spec_not_the_raw_spec(tmp_path):
    """The generator adds the register bus; a YAML spec never lists it. Building the
    testbench from the raw spec produced one with no bus at all that compiled, ran,
    and checked nothing."""
    s = mspec(tmp_path, REGS_YAML)
    without = make_testbench(s)                    # no all_ports -> spec ports only
    assert "reg_wr_i" not in without
    with_ports = make_testbench(s, s.all_ports)
    assert "reg_wr_i" in with_ports


def test_a_w1c_register_is_checked_for_clearing_not_storing(tmp_path):
    s = mspec(tmp_path, REGS_YAML)
    tb = make_testbench(s, s.all_ports)
    assert "write-1-to-clear but did not clear" in tb
    assert "is read-only but changed" in tb


def test_reset_is_checked_for_every_register(tmp_path):
    """One `chk` call per register, each naming the register.

    The checks used to be three lines each (read, mask-compare, fatal); they are
    one call to a named task now, so the count is of calls, not of a literal
    string inside a fatal message.
    """
    s = mspec(tmp_path, REGS_YAML)
    tb = make_testbench(s, s.all_ports)
    assert len(re.findall(r'chk\([^;]*"\w+ reset"\)', tb)) == 3


# ---- the loop ------------------------------------------------------------
def test_a_spec_it_cannot_emit_is_refused_with_a_reason(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(REGS_YAML + "\nwidth: 8\n")     # not a key the generator knows
    rec = vibe(str(bad), str(tmp_path / "out"))
    assert rec["ok"] is False
    assert rec["stage"] == "generate"
    assert "refused" in rec["error"]


def test_a_sentence_outside_the_grammar_is_refused(tmp_path):
    rec = vibe("make me a fifo with three clocks and a reset", str(tmp_path / "out"))
    assert rec["ok"] is False
    assert rec["stage"] == "spec"
    assert "refused" in rec["error"]


def test_the_report_says_what_it_did_not_what_it_promised(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(REGS_YAML + "\nwidth: 8\n")
    text = render(vibe(str(bad), str(tmp_path / "out")))
    assert "could not build" in text


# ---- the app ------------------------------------------------------------
def test_the_app_command_set_includes_vibe():
    """The feature is usable from the app's CLI pane, not only the shell."""
    from wengold.desktop import CLI_COMMANDS
    assert "vibe" in CLI_COMMANDS


def test_the_app_vibe_command_needs_a_target():
    from wengold.desktop import _exec
    r = _exec({"path": "."}, "vibe")
    assert r["ok"] is False
    assert "needs a spec file or a sentence" in r["output"]


# ---- end to end, when a simulator is available --------------------------
import shutil

HAS_SIM = bool(shutil.which("iverilog") and shutil.which("vvp"))


@pytest.mark.skipif(not HAS_SIM, reason="iverilog/vvp not installed")
def test_a_generated_block_passes_its_own_testbench(tmp_path):
    spec = tmp_path / "counter.yaml"
    spec.write_text("""
module: counter
clock: clk_i
reset: rst_ni
ports:
  - {name: clk_i, dir: input, width: 1}
  - {name: rst_ni, dir: input, width: 1}
  - {name: en_i, dir: input, width: 1}
  - {name: q_o, dir: output, width: 8}
registers:
  - name: CTRL
    addr: 0x0
    fields:
      - {name: EN, bits: "0", access: rw, reset: 0}
      - {name: STEP, bits: "8:1", access: rw, reset: 1}
""")
    rec = vibe(str(spec), str(tmp_path / "out"))
    assert rec["stage"] == "simulate", rec
    assert rec["outcome"] == "pass", rec.get("log", "")[-600:]


@pytest.mark.skipif(not HAS_SIM, reason="iverilog/vvp not installed")
def test_a_broken_block_fails_its_own_testbench(tmp_path):
    """The checker must be able to fail, or it proves nothing."""
    out = tmp_path / "out"
    spec = tmp_path / "counter.yaml"
    spec.write_text("""
module: counter
clock: clk_i
reset: rst_ni
ports:
  - {name: clk_i, dir: input, width: 1}
  - {name: rst_ni, dir: input, width: 1}
registers:
  - name: CTRL
    addr: 0x0
    fields:
      - {name: EN, bits: "0", access: rw, reset: 1}
""")
    rec = vibe(str(spec), str(out))
    assert rec["outcome"] == "pass", rec.get("log", "")[-400:]
    # corrupt the generated RTL and re-run the same testbench
    rtl = out / "counter.sv"
    rtl.write_text(rtl.read_text().replace("ctrl_q <=", "ctrl_q <= 32'd0; //", 1))
    from wengold.agent.runners import ToolRunner, Toolchain
    from wengold.graph.builder import GraphBuilder
    from wengold.kernel.validity import Result
    from wengold.cli import _collect
    g = GraphBuilder().build_from_files(_collect(str(out)), backend="auto")
    tr = ToolRunner(g, {"x": Result("x", "sim", depends_on={"counter"})},
                    str(out), toolchain=Toolchain())
    assert tr("x", "sim")["outcome"] == "fail"


# ---- the app shows the code ---------------------------------------------
def test_the_file_detail_carries_the_source(tmp_path):
    """A detail pane that describes a file without showing it is a strange thing
    for a tool whose job is reading RTL."""
    proj = tmp_path / "p"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "a.sv").write_text("module a; endmodule\n")
    from wengold.desktop import _file_detail, build_state
    d = _file_detail(build_state(str(proj)), "rtl/a.sv")
    assert d["source"].startswith("module a;")
    assert d["lines"] == 1


def test_a_long_file_is_truncated_and_says_so(tmp_path):
    proj = tmp_path / "p"
    (proj / "rtl").mkdir(parents=True)
    (proj / "rtl" / "big.sv").write_text("\n".join(
        f"// line {i}" for i in range(500)) + "\nmodule big; endmodule\n")
    from wengold.desktop import _file_detail, build_state
    d = _file_detail(build_state(str(proj)), "rtl/big.sv")
    assert d["truncated"] is True
    assert d["lines"] == 400


@pytest.mark.skipif(not HAS_SIM, reason="iverilog/vvp not installed")
def test_the_app_reports_the_files_it_wrote(tmp_path):
    """The window selects the generated file, so it needs the relative paths."""
    spec = tmp_path / "t.yaml"
    spec.write_text(TIMER_YAML)
    from wengold.desktop import _exec, build_state
    r = _exec(build_state(str(tmp_path)), f"vibe {spec}")
    assert r["ok"] is True, r["output"]
    assert any(w.endswith("timer.sv") for w in r["written"])
    assert any(w.endswith("timer_tb.sv") for w in r["written"])


def test_the_generated_header_names_the_input_the_user_gave(tmp_path):
    """After loading through a temporary file the header cited the temp path,
    which the reader never wrote and cannot find."""
    spec = tmp_path / "t.yaml"
    spec.write_text(TIMER_YAML)
    rec = vibe(str(spec), str(tmp_path / "out"))
    if rec.get("stage") not in ("simulate", None):
        pytest.skip("generator unavailable")
    text = (tmp_path / "out" / "timer.sv").read_text()
    assert ".spec.yaml" not in text, "the header should not cite a temporary file"


# ---- the line count is kept, not just shown ------------------------------
@pytest.mark.skipif(not HAS_SIM, reason="iverilog/vvp not installed")
def test_the_line_count_is_recorded_and_written_to_a_manifest(tmp_path):
    """The count used to be computed for the detail pane and thrown away, so
    closing the app lost it."""
    import json
    spec = tmp_path / "t.yaml"
    spec.write_text(TIMER_YAML)
    out = tmp_path / "out"
    rec = vibe(str(spec), str(out))
    assert rec["ok"], rec.get("output") or rec.get("note")

    assert rec["lines"]["timer.sv"] == len(
        (out / "timer.sv").read_text().splitlines())
    assert rec["total_lines"] == sum(rec["lines"].values())

    m = json.loads((out / "manifest.json").read_text())
    assert m["module"] == "timer"
    assert m["total_lines"] == rec["total_lines"]
    assert m["outcome"] == rec["outcome"]
    assert set(m["files"]) == {"timer.sv", "timer_tb.sv"}


def test_the_report_shows_the_line_count(tmp_path):
    rec = {"module": "m", "ok": True, "outcome": "pass", "tool": "iverilog",
           "spec_source": "file", "files": [], "note": "",
           "lines": {"m.sv": 40, "m_tb.sv": 20}, "total_lines": 60}
    text = render(rec)
    assert "60 lines" in text
    assert "m.sv 40" in text and "m_tb.sv 20" in text


def test_a_failed_run_does_not_write_a_manifest(tmp_path):
    """A manifest that claims a verdict for a run that never got there would be
    the same class of error as a test count nobody checked."""
    bad = tmp_path / "bad.yaml"
    bad.write_text(REGS_YAML + "\nwidth: 8\n")
    out = tmp_path / "out"
    rec = vibe(str(bad), str(out))
    assert rec["ok"] is False
    assert not (out / "manifest.json").exists()
