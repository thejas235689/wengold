"""Defects found by the four parallel CDC audits, and the ones fixed here.

The audits returned 64 findings. Five are fixed in this release; the rest are
recorded in `docs/CDC-AUDIT.md` with their severity, unfixed. What is pinned here
is the set that would let a real CDC bug through, plus the port type that made a
conformant file fail.
"""
import pytest

from wengold.cdc_standard import PORT_TYPES, check, parse
from wengold.cdc_sva import emit


HEAD = ("accellera_cdc::set_module -name m\n"
        "accellera_cdc::set_port -name clk_a -direction input -type clock\n"
        "accellera_cdc::set_port -name clk_b -direction input -type clock\n")


def sva(extra: str) -> str:
    return emit(parse(HEAD + extra))


# ---- Clause 8.3: the setup property was not legal SVA -------------------
def test_the_setup_check_uses_no_negative_repetition():
    """`$stable(x)[-N]` is not legal SVA — a repetition looks forward, so the
    setup requirement had no working assertion at all."""
    out = sva("accellera_cdc::set_port -name vld -direction input "
              "-type cdc_control -polarity high\n"
              "accellera_cdc::set_port -name d -direction input -type data "
              "-associated_to_clocks clk_b -cdc_control vld "
              "-cdc_control_setup 3\n")
    assert "[-" not in out, "a negative repetition is not legal SVA"
    assert "$past(d,1)" in out and "$past(d,3)" in out


def test_the_declared_setup_and_hold_are_used_not_a_default():
    """Table 3 makes these integer counts of destination clock cycles. They were
    discarded for a default of 1, so a declared 3 was checked as 1."""
    out = sva("accellera_cdc::set_port -name vld -direction input "
              "-type cdc_control -polarity high\n"
              "accellera_cdc::set_port -name d -direction input -type data "
              "-associated_to_clocks clk_b -cdc_control vld "
              "-cdc_control_setup 3 -cdc_control_hold 2\n")
    assert "SETUP_CYCLES" not in out, "the declared value is already a cycle count"
    assert "$stable(d)[*2]" in out          # the declared hold
    assert "$past(d,3)" in out              # the declared setup


def test_an_active_low_control_enables_on_the_falling_edge():
    """`-polarity` is mandatory for cdc_control. Assuming $rose fired the setup
    check on the wrong event for an active-low control."""
    low = sva("accellera_cdc::set_port -name vld -direction input "
              "-type cdc_control -polarity low\n"
              "accellera_cdc::set_port -name d -direction input -type data "
              "-associated_to_clocks clk_b -cdc_control vld "
              "-cdc_control_setup 2 -cdc_control_hold 2\n")
    assert "$fell(vld) |->" in low, "active-low enables on the falling edge"
    assert "$rose(vld) |->" in low, "and disables on the rising edge"

    high = sva("accellera_cdc::set_port -name vld -direction input "
               "-type cdc_control -polarity high\n"
               "accellera_cdc::set_port -name d -direction input -type data "
               "-associated_to_clocks clk_b -cdc_control vld "
               "-cdc_control_setup 2 -cdc_control_hold 2\n")
    assert "$rose(vld) |->" in high
    assert "$fell(vld) |->" in high


# ---- Clause 8.2: the window did not match its own message --------------
def test_the_stability_window_is_four_edges_not_six():
    """8.2 generalises to "stable for four clock edges". `[*3]` is six, so a
    design meeting the standard was reported failing — while the message claimed
    a four-edge window."""
    out = sva("accellera_cdc::set_port -name d -direction input -type data "
              "-associated_to_clocks clk_b\n")
    assert "$stable(d)[*2]" in out, "two periods is four edges"
    assert "[*3]" not in out
    assert "four" in out, "the comment and the assertion must agree"


# ---- Clause 4 / Table 3: a conformant port type was rejected -----------
def test_virtual_reset_is_a_port_type():
    """Table 3 and Clause 5 d) 2) define `virtual_reset`, used the same way as
    `virtual_clock`. It was missing, so a conformant declaration was rejected."""
    assert "virtual_reset" in PORT_TYPES
    r = check(parse(HEAD + "accellera_cdc::set_port -name vrst -direction input "
                           "-type virtual_reset\n"))
    assert not [e for e in r.errors if "virtual_reset" in str(e)]


def test_a_virtual_port_is_not_required_to_exist_in_the_rtl():
    """A virtual port by definition has no matching port in the module."""
    r = check(parse(HEAD + "accellera_cdc::set_port -name vrst -direction input "
                           "-type virtual_reset\n"), rtl_ports={"clk_a", "clk_b"})
    assert not [e for e in r.errors if "vrst" in str(e)]
