"""Vibe coding: describe it, get RTL, and see it simulated.

The value is not that a sentence becomes Verilog. It is that **nothing reaches you
unverified** — the generated block is simulated, and its registers are written and
read back before you see it.

The tests here are mostly about the testbench the module generates, because a
generated checker that cannot fail is worse than no checker: it reports every
design as correct. Two of these tests exist specifically because the first version
was vacuous.
"""
import pytest

from wengold.vibe import _masks, make_testbench, render, vibe

TIMER = {
    "module": "timer", "clock": "clk_i", "reset": "rst_ni",
    "ports": [
        {"name": "clk_i", "dir": "input", "width": 1},
        {"name": "rst_ni", "dir": "input", "width": 1},
        {"name": "tick_i", "dir": "input", "width": 1},
        {"name": "match_o", "dir": "output", "width": 1},
    ],
    "registers": [],
}

REGS = {
    "module": "regs", "clock": "clk_i", "reset": "rst_ni",
    "ports": [
        {"name": "clk_i", "dir": "input", "width": 1},
        {"name": "rst_ni", "dir": "input", "width": 1},
    ],
    "registers": [
        {"name": "CTRL", "addr": 0, "fields": [
            {"name": "EN", "bits": "0", "access": "rw", "reset": 0},
            {"name": "MODE", "bits": "3:1", "access": "rw", "reset": 3}]},
        {"name": "IRQ", "addr": 4, "fields": [
            {"name": "PENDING", "bits": "0", "access": "w1c", "reset": 0}]},
        {"name": "STATUS", "addr": 8, "fields": [
            {"name": "COUNT", "bits": "15:0", "access": "ro", "reset": 0}]},
    ],
}

BUS_PORTS = [
    {"name": "clk_i", "dir": "input", "width": 1},
    {"name": "rst_ni", "dir": "input", "width": 1},
    {"name": "reg_wr_i", "dir": "input", "width": 1},
    {"name": "reg_rd_i", "dir": "input", "width": 1},
    {"name": "reg_addr_i", "dir": "input", "width": 32},
    {"name": "reg_wdata_i", "dir": "input", "width": 32},
    {"name": "reg_rdata_o", "dir": "output", "width": 32},
]


class P:
    """A stand-in for the generator's port objects."""
    def __init__(self, name, direction, width):
        self.name, self.direction, self.width = name, direction, width


def as_ports(dicts):
    return [P(d["name"], d["dir"], d["width"]) for d in dicts]


# ---- the masks -----------------------------------------------------------
def test_rw_w1c_and_ro_are_separated():
    """`w1c` must not be treated as `rw`: writing 1 clears, it does not store."""
    m = _masks(REGS["registers"][0])
    assert m["rw"] == 0b1111 and m["w1c"] == 0 and m["ro"] == 0

    irq = _masks(REGS["registers"][1])
    assert irq["w1c"] == 1 and irq["rw"] == 0

    st = _masks(REGS["registers"][2])
    assert st["ro"] == 0xFFFF and st["rw"] == 0


def test_reset_values_come_from_the_fields():
    m = _masks(REGS["registers"][0])
    assert m["reset"] == 0b0110, "MODE resets to 3 in bits 3:1"


# ---- the generated testbench --------------------------------------------
def test_a_block_without_a_bus_gets_no_register_tasks():
    """Emitting write/read tasks for ports that do not exist is a testbench that
    cannot compile — which reads as 'the generated RTL is broken'."""
    tb = make_testbench(TIMER, as_ports(TIMER["ports"]))
    assert "task automatic wr" not in tb
    assert "reg_wr_i" not in tb
    assert "$fatal" in tb, "it must still be able to fail"


def test_a_block_with_a_bus_gets_register_tasks():
    tb = make_testbench(REGS, as_ports(BUS_PORTS))
    assert "task automatic wr" in tb and "task automatic rd" in tb
    assert "reg_wdata_i" in tb


def test_the_bus_is_taken_from_the_module_spec_not_the_raw_spec():
    """The generator adds the register bus; the spec never lists it. Reading the
    spec produced a testbench with no bus at all that compiled, ran, and checked
    nothing."""
    raw = dict(REGS)
    raw["ports"] = [{"name": "clk_i", "dir": "input", "width": 1},
                    {"name": "rst_ni", "dir": "input", "width": 1}]
    without = make_testbench(raw)
    assert "reg_wr_i" not in without, "the raw spec has no bus"
    with_spec = make_testbench(raw, as_ports(BUS_PORTS))
    assert "reg_wr_i" in with_spec


def test_a_w1c_register_is_checked_for_clearing_not_storing():
    tb = make_testbench(REGS, as_ports(BUS_PORTS))
    assert "write-1-to-clear but did not clear" in tb
    assert "is read-only but changed" in tb


def test_reset_is_checked_for_every_register():
    tb = make_testbench(REGS, as_ports(BUS_PORTS))
    assert tb.count("reset: expected") == 3


# ---- the loop ------------------------------------------------------------
def test_a_spec_it_cannot_emit_is_refused_with_a_reason(tmp_path):
    bad = dict(REGS)
    bad["width"] = 8              # not a key the generator understands
    import yaml
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(bad))
    rec = vibe(str(p), str(tmp_path / "out"))
    assert rec["ok"] is False
    assert rec["stage"] == "generate"
    assert "refused" in rec["error"]


def test_a_sentence_outside_the_grammar_is_refused(tmp_path):
    rec = vibe("make me a fifo with three clocks and a reset", str(tmp_path / "out"))
    assert rec["ok"] is False
    assert rec["stage"] == "spec"
    assert "refused" in rec["error"]


def test_the_report_says_what_it_did_not_what_it_promised(tmp_path):
    bad = dict(REGS)
    bad["width"] = 8
    import yaml
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(bad))
    text = render(vibe(str(p), str(tmp_path / "out")))
    assert "could not build" in text
    assert "pass" not in text.split("could not build")[0]


# ---- end to end, when a simulator is available --------------------------
REAL_TOOLS = None
try:
    from wengold.agent.runners import Toolchain
    _tc = Toolchain()
    if _tc.has("iverilog") and _tc.has("vvp"):
        REAL_TOOLS = None      # ambient PATH is enough
except Exception:
    pass


@pytest.mark.skipif(REAL_TOOLS is None and not __import__("shutil").which("iverilog"),
                    reason="iverilog/vvp not installed")
def test_a_generated_block_passes_its_own_testbench(tmp_path):
    import yaml
    spec = {
        "module": "counter", "clock": "clk_i", "reset": "rst_ni",
        "ports": [{"name": "clk_i", "dir": "input", "width": 1},
                  {"name": "rst_ni", "dir": "input", "width": 1},
                  {"name": "en_i", "dir": "input", "width": 1},
                  {"name": "q_o", "dir": "output", "width": 8}],
        "registers": [{"name": "CTRL", "addr": 0, "fields": [
            {"name": "EN", "bits": "0", "access": "rw", "reset": 0},
            {"name": "STEP", "bits": "8:1", "access": "rw", "reset": 1}]}],
    }
    p = tmp_path / "counter.yaml"
    p.write_text(yaml.safe_dump(spec))
    rec = vibe(str(p), str(tmp_path / "out"))
    assert rec["stage"] == "simulate", rec
    assert rec["outcome"] == "pass", rec.get("log", "")[-600:]
