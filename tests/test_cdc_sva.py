"""Clause 8 — SVA emitted from the collateral.

The claim these assertions support is narrow, and the header says so: they check
that the data stability the collateral declares holds in the waveforms. They do
not prove a crossing is safe, because a closed box cannot see the synchroniser.

`-cdc_control_setup` / `-cdc_control_hold` are integer counts of destination
clock cycles (Table 3), not durations — so they are used directly, with no
repetition counts in SVA. This module refuses to invent a clock period: it emits a
parameter with the duration in a comment, because a wrong repetition count
produces an assertion that passes for the wrong reason.
"""
import pytest

from wengold.cdc_standard import parse
from wengold.cdc_sva import emit

FULL = """
accellera_cdc::set_module -name m
accellera_cdc::set_port -name clk_a -direction input -type clock
accellera_cdc::set_port -name d_in -direction input -type data \\
  -associated_to_clocks clk_a -sampling_edge neg \\
  -cdc_control wr_en -cdc_control_setup 2 -cdc_control_hold 1
accellera_cdc::set_port -name wr_en -direction input -type cdc_control -polarity high
"""

BARE = """
accellera_cdc::set_module -name m
accellera_cdc::set_port -name clk_a -direction input -type clock
accellera_cdc::set_port -name d_in -direction input -type data \\
  -associated_to_clocks clk_a
"""


def test_it_emits_a_module_named_after_the_ip():
    sv = emit(parse(FULL))
    assert "module m_cdc_checks" in sv


def test_a_crossing_gets_a_four_edge_stability_assertion():
    """Clause 8.2: stable for four destination clock edges."""
    sv = emit(parse(FULL))
    assert "$changed(d_in) |-> $stable(d_in)[*2]" in sv
    assert "four clk_a edges" in sv


def test_the_sampling_edge_is_honoured():
    sv = emit(parse(FULL))
    assert "@(negedge clk_a)" in sv
    assert "sampled on the neg edge" in sv


def test_an_undeclared_edge_defaults_to_pos_and_says_so():
    sv = emit(parse(BARE))
    assert "@(posedge clk_a)" in sv
    assert "sampling edge not declared" in sv


def test_setup_and_hold_become_assertions():
    sv = emit(parse(FULL))
    assert "a_cdc_setup_d_in" in sv and "a_cdc_hold_d_in" in sv
    assert "a_cdc_setup_d_in" in sv and "a_cdc_hold_d_in" in sv
    # the declared values are already cycle counts: no parameter, no default
    assert "SETUP_CYCLES" not in sv and "HOLD_CYCLES" not in sv


def test_a_non_integer_setup_value_is_reported_not_dropped():
    """Table 3 makes setup/hold integer cycle counts. A value like `2ns` is not
    that form; the emitter says so rather than silently emitting nothing."""
    out = emit(parse(FULL.replace("-cdc_control_setup 2",
                                  "-cdc_control_setup 2ns")))
    assert "is not an integer cycle count" in out


def test_the_declared_cycle_counts_are_kept_in_the_comments():
    """The declared count must appear in the generated file, so a reader can
    check the assertion against the collateral."""
    sv = emit(parse(FULL))
    assert "-cdc_control_setup = 2" in sv
    assert "-cdc_control_hold = 1" in sv


def test_it_does_not_invent_a_clock_period():
    """A guessed repetition count is an assertion that passes for the wrong reason."""
    sv = emit(parse(FULL))
    assert "SETUP_CYCLES" not in sv          # the declared value is a cycle count
    assert "NOT guessed here" in sv


def test_every_signal_named_is_a_port_of_the_generated_module():
    """The first version named the control in a property but not in the header,
    so the file did not compile."""
    sv = emit(parse(FULL))
    header = sv[sv.index("module m_cdc_checks"):sv.index(");")]
    for sig in ("clk_a", "d_in", "wr_en"):
        assert sig in header, f"{sig} used but not declared"


def test_no_crossing_means_an_empty_module_not_a_broken_one():
    col = parse("accellera_cdc::set_module -name m\n"
                "accellera_cdc::set_port -name c -direction input -type clock")
    sv = emit(col)
    assert "module m_cdc_checks;" in sv
    assert "no crossing" in sv.lower()


def test_the_header_states_the_limit():
    sv = emit(parse(FULL))
    assert "do not prove a crossing is safe" in sv
    assert "8.4" in sv, "Clause 8.4 (verification clock) must be stated"


def test_an_ignored_port_is_not_asserted_on():
    col = parse("accellera_cdc::set_module -name m\n"
                "accellera_cdc::set_port -name c -direction input -type clock\n"
                "accellera_cdc::set_port -name d -direction input -type data "
                "-associated_to_clocks c -ignore")
    assert "a_cdc_stable_d" not in emit(col)


@pytest.mark.parametrize("src", [FULL, BARE])
def test_the_output_parses_as_systemverilog(src):
    """Proven with a real SystemVerilog front-end, not by eye."""
    pyslang = pytest.importorskip("pyslang")
    tree = pyslang.syntax.SyntaxTree.fromText(emit(parse(src)))
    errors = [d for d in tree.diagnostics if d.isError()]
    assert not errors, [str(e) for e in errors[:3]]
