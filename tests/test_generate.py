"""Spec -> SystemVerilog -> conformance check.

The point of these tests is not that the generator runs, but that the *checker*
refuses bad output. Half of them mutate generated RTL and assert the mutation is
caught; a checker that passes everything would fail them.
"""
import textwrap

import pytest

from wengold.generate import conform
from wengold.generate.emit import emit_map, emit_props, emit_rtl
from wengold.generate.spec import SpecError, load_spec

SPEC = textwrap.dedent("""
    module: demo
    ports:
      - {name: clk_i,  dir: input,  width: 1}
      - {name: rst_ni, dir: input,  width: 1}
      - {name: out_o,  dir: output, width: 4}
    parameters:
      - {name: DEPTH, value: 8}
    registers:
      - name: CTRL
        addr: 0x0
        fields:
          - {name: EN,   bits: "0",   access: rw, reset: 0}
          - {name: MODE, bits: "3:1", access: rw, reset: 5}
      - name: STATUS
        addr: 0x4
        fields:
          - {name: BUSY, bits: "0", access: ro, reset: 0}
    assigns:
      - {target: out_o, expr: "ctrl_mode_q"}
""")


@pytest.fixture
def spec(tmp_path):
    p = tmp_path / "demo.spec.yaml"
    p.write_text(SPEC)
    return load_spec(p)


# ---- spec -----------------------------------------------------------------
def test_spec_parses_fields_and_reset(spec):
    assert spec.name == "demo"
    ctrl = spec.registers[0]
    assert [(f.name, f.hi, f.lo) for f in ctrl.fields] == [("EN", 0, 0), ("MODE", 3, 1)]
    assert ctrl.reset_value == 0b1010          # MODE=5 at bits 3:1
    assert spec.address_map == {"CTRL": 0x0, "STATUS": 0x4}


def test_spec_adds_the_register_bus_ports(spec):
    names = [p.name for p in spec.all_ports]
    assert names[-5:] == ["reg_wr_i", "reg_rd_i", "reg_addr_i",
                          "reg_wdata_i", "reg_rdata_o"]


@pytest.mark.parametrize("bad, message", [
    ("registers:\n  - {name: A, addr: 0x0, fields: [{name: F, bits: '1:0', access: nope}]}",
     "access"),
    ("registers:\n  - {name: A, addr: 0x2, fields: [{name: F, bits: '0'}]}", "multiple of 4"),
    ("registers:\n  - {name: A, addr: 0x0, fields: [{name: F, bits: '0'}, "
     "{name: G, bits: '0'}]}", "both claim bit 0"),
    ("registers:\n  - {name: A, addr: 0x0, fields: [{name: F, bits: '0:3'}]}", "reversed"),
])
def test_spec_rejects_nonsense(tmp_path, bad, message):
    p = tmp_path / "bad.yaml"
    p.write_text("module: m\nports:\n  - {name: clk_i}\n  - {name: rst_ni}\n" + bad)
    with pytest.raises(SpecError) as exc:
        load_spec(p)
    assert message in str(exc.value)


def test_spec_refuses_what_it_cannot_express(tmp_path):
    """A state machine is not in the format, so it is refused, not dropped.

    Silently ignoring `fsm:` would hand back a module with no FSM in it and no
    warning — the opposite of what the rest of WENGOLD does.
    """
    p = tmp_path / "fsm.yaml"
    p.write_text("module: traffic\nports:\n  - {name: clk_i}\n"
                 "fsm:\n  states: [IDLE, GRANT]\n")
    with pytest.raises(SpecError) as exc:
        load_spec(p)
    assert "fsm" in str(exc.value)
    assert "refused rather than silently dropped" in str(exc.value)


def test_spec_refuses_an_unknown_field_key(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text("module: m\nports:\n  - {name: clk_i}\n  - {name: rst_ni}\n"
                 "registers:\n  - name: R\n    addr: 0x0\n    fields:\n"
                 "      - {name: F, bits: '0', enum: [A, B]}\n")
    with pytest.raises(SpecError, match="unsupported key"):
        load_spec(p)


def test_spec_requires_the_clock_to_be_a_port(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text("module: m\nclock: nope\nports:\n  - {name: rst_ni}\n")
    with pytest.raises(SpecError, match="not a port"):
        load_spec(p)


# ---- emit -----------------------------------------------------------------
def test_emission_is_deterministic(spec):
    assert emit_rtl(spec) == emit_rtl(spec)


def test_emitted_rtl_parses_with_slang(spec):
    from pyslang import syntax as S
    tree = S.SyntaxTree.fromText(emit_rtl(spec), name="demo.sv")
    assert list(tree.diagnostics) == []


def test_emitted_rtl_carries_the_field_slices(spec):
    rtl = emit_rtl(spec)
    assert "assign ctrl_en_q = ctrl_q[0];" in rtl
    assert "assign ctrl_mode_q = ctrl_q[3:1];" in rtl
    assert "ctrl_q[3:1] <= reg_wdata_i[3:1];" in rtl


def test_read_only_fields_get_no_write_path(spec):
    rtl = emit_rtl(spec)
    assert "status_q[" not in rtl.split("read path")[0].split("else begin")[-1]


def test_props_and_map_are_emitted(spec):
    assert "ap_ctrl_en_stable" in emit_props(spec)
    assert "ap_status_busy_ro" in emit_props(spec)
    assert emit_map(spec)["registers"][0]["name"] == "CTRL"


# ---- the checker must catch bad output ------------------------------------
def test_generated_rtl_passes_its_own_check(spec):
    report = conform.check(emit_rtl(spec), spec)
    assert report.ok, report.summary()
    assert len(report.checks) > 15


@pytest.mark.parametrize("old, new, caught", [
    ("ctrl_q[3:1]", "ctrl_q[2:0]", "CTRL.MODE slice"),
    ("CTRL_ADDR = 32'h00000000", "CTRL_ADDR = 32'h00000008", "CTRL address"),
    ("ctrl_q <= 32'h0000000a", "ctrl_q <= 32'h00000000", "CTRL reset"),
    ("output logic [3:0] out_o", "output logic [1:0] out_o", "port out_o"),
    ("parameter int unsigned DEPTH = 8", "parameter int unsigned DEPTH = 4",
     "parameter DEPTH"),
])
def test_checker_catches_mutations(spec, old, new, caught):
    rtl = emit_rtl(spec)
    assert old in rtl, f"test fixture drifted: {old!r} not in the generated RTL"
    report = conform.check(rtl.replace(old, new), spec)
    assert not report.ok
    assert caught in [c.item for c in report.failures]


def test_checker_catches_a_read_only_field_that_got_written(spec):
    rtl = emit_rtl(spec)
    mutated = rtl.replace("                ctrl_q[0] <= reg_wdata_i[0];",
                          "                ctrl_q[0] <= reg_wdata_i[0];\n"
                          "                status_q[0] <= reg_wdata_i[0];")
    assert mutated != rtl
    report = conform.check(mutated, spec)
    assert "STATUS.BUSY read-only" in [c.item for c in report.failures]


def test_checker_catches_an_undriven_output(spec):
    rtl = emit_rtl(spec)
    report = conform.check(rtl.replace("assign out_o = ctrl_mode_q;", ""), spec)
    assert "output out_o driven" in [c.item for c in report.failures]


def test_checker_reports_the_method_it_used(spec):
    report = conform.check(emit_rtl(spec), spec)
    methods = {c.method for c in report.checks}
    assert methods == {"parse tree", "source scan"}
