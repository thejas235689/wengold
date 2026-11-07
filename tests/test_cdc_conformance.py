"""Conformant input must be accepted — drawn verbatim from the standard.

This file exists to catch the failure mode that a fix for "rejects valid input"
can itself cause: a new mandatory check that fires on collateral the standard
allows. That is a worse bug than the one it fixes, because it makes the tool
unusable on correct files and the user has no way to tell which side is wrong.

Every snippet below is quoted from Accellera CDC/RDC Interface Standard v1.0 with
its example number. If the checker rejects one of these, the checker is wrong and
the standard is right.
"""
import pytest

from wengold.cdc_standard import check, parse


def ok(text: str) -> list:
    """Errors only — warnings are not rejections."""
    return [e for e in check(parse(text)).errors]


# ---- Example 34: the rdc_control port, verbatim ------------------------
# This is the §5.4 example. The audit found the scenario checker required an
# attribute this example does not have, which made the standard's own example
# fail its own scenario.
# Table 3 makes -polarity Conditional and "mandatory for async reset", so the reset
# ports carry it. A first version of this fixture omitted it and the checker was
# right to reject — the test was wrong, not the code.
EX34 = """
accellera_cdc::set_module -name top
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name rst0_n_i -direction input -type async_reset \
  -polarity low
accellera_cdc::set_port -name rst1_n_i -direction input -type async_reset \
  -polarity low
accellera_cdc::set_port -name rdcq0_i -direction input -type rdc_control \\
  -blocking_polarity low -associated_to_reset rst1_n_i \\
  -associated_to_clocks clk0_i -rdc_data_from_reset rst0_n_i
"""


def test_example_34_is_accepted():
    assert ok(EX34) == [], "the standard's own Example 34 must be accepted"


# ---- Example 42: set_clock_group, verbatim ----------------------------
EX42 = """
accellera_cdc::set_module -name ALU
accellera_cdc::set_port -name clk1_i -direction input -type clock
accellera_cdc::set_port -name clk2_i -direction input -type clock
accellera_cdc::set_clock_group -name ClkGroup1 -clocks {clk1_i clk2_i}
"""


def test_example_42_clock_group_is_accepted():
    assert ok(EX42) == []


# ---- Example 42: the port forms the standard shows --------------------
# Example 42 abbreviates with a trailing `...`, and Table 3 makes `direction`
# Mandatory — so the forms below carry the direction the example elides. The first
# version of this file omitted it and produced 12 "failures" that were the test's
# fault, not the checker's. That is what this file is for: it must be as strict
# about the standard as the checker is.
PORT_FORMS = [
    ("virtual port with frequency",
     "accellera_cdc::set_port -name CLK -direction input -type clock "
     "-virtual_port p2 -frequency 100"),
    ("vector",
     "accellera_cdc::set_port -name {RegA[7:0]} -direction input -type data"),
    ("parameterised vector",
     "accellera_cdc::set_port -name {RegA[WIDTH-1:0]} -direction input -type data"),
    ("2D",
     "accellera_cdc::set_port -name {RegA[7:0][4:0]} -direction input -type data"),
    ("parameterised 2D",
     "accellera_cdc::set_port -name {RegA[WIDTH-1:0][DEPTH-1:0]} -direction input "
     "-type data"),
    ("concatenation",
     "accellera_cdc::set_port -name {{RegA[7:5]} {RegA[2]} {RegA[0]}} "
     "-direction input -type data"),
    ("negative index",
     "accellera_cdc::set_port -name {RegA[MSB:-LSB]} -direction input -type data"),
    ("async reset with polarity",
     "accellera_cdc::set_port -name RESET -direction input -type async_reset "
     "-polarity high"),
]


@pytest.mark.parametrize("desc,line", PORT_FORMS, ids=[p[0] for p in PORT_FORMS])
def test_the_standards_own_port_forms_are_accepted(desc, line):
    text = "accellera_cdc::set_module -name m\n" + line + "\n"
    assert ok(text) == [], f"{desc} is shown by the standard and must be accepted"


# ---- 4.3.8: a -constant port needs only name and direction ------------
def test_a_constant_port_needs_no_type():
    """4.3.8 exempts -constant from the mandatory -type: only name and direction
    are required. Rejecting this is rejecting conformant input."""
    text = ("accellera_cdc::set_module -name m\n"
            "accellera_cdc::set_port -name vdd -direction input -constant\n")
    assert ok(text) == []


# ---- Table 3 attributes the checker did not accept --------------------
TABLE3_ATTRS = [
    # Table 3: hamming1 is Boolean, default 0/false, Optional — so the bare form
    # is legal and means true.
    ("hamming1",
     "accellera_cdc::set_port -name d -direction input -type data -hamming1"),
    # Table 3: clock_period is a string, Conditional.
    ("clock_period",
     "accellera_cdc::set_port -name c -direction input -type clock "
     "-clock_period 10"),
    ("virtual_reset",
     "accellera_cdc::set_port -name vr -direction input -type virtual_reset"),
]


@pytest.mark.parametrize("name,line", TABLE3_ATTRS, ids=[a[0] for a in TABLE3_ATTRS])
def test_table_3_attributes_are_accepted(name, line):
    text = "accellera_cdc::set_module -name m\n" + line + "\n"
    assert ok(text) == [], f"{name} is defined by the standard and must be accepted"


# ---- an unnamed clock group is legal (Table 6: -name is optional) -----
def test_a_clock_group_without_a_name_is_accepted():
    text = ("accellera_cdc::set_module -name m\n"
            "accellera_cdc::set_port -name c1 -direction input -type clock\n"
            "accellera_cdc::set_port -name c2 -direction input -type clock\n"
            "accellera_cdc::set_clock_group -clocks {c1 c2}\n")
    assert ok(text) == []


# ---- 6.3 b): set_param -ignore ---------------------------------------
def test_set_param_ignore_is_accepted():
    text = ("accellera_cdc::set_module -name m\n"
            "accellera_cdc::set_param -name P -ignore blocked\n")
    assert ok(text) == []


# ---- and the checker must still reject genuinely wrong input ----------
# A guard that accepts everything is not a guard. These must still fail.
def test_a_missing_type_on_a_data_port_is_still_rejected():
    text = ("accellera_cdc::set_module -name m\n"
            "accellera_cdc::set_port -name d -direction input\n")
    assert ok(text) != [], "a data port without -type is genuinely invalid"


def test_an_unknown_attribute_is_named_not_blamed_on_type():
    """An unknown token used to fold into the previous value, so a missing
    attribute was reported as a bogus 'type not defined'.

    A warning is the right severity: Clause 6.1's "cannot include non-standard
    extensions" is a NOTE, not a stated error condition. What must not happen is
    the attribute being reported as something it is not.
    """
    text = ("accellera_cdc::set_module -name m\n"
            "accellera_cdc::set_port -name d -direction input -type data "
            "-bogus_attr x\n")
    r = check(parse(text))
    joined = " ".join(str(f) for f in r.findings)
    assert "bogus_attr" in joined, f"the unknown attribute must be named: {joined}"
    assert "type not defined" not in joined, "it must not be blamed on -type"
    # and the port's real type must survive the unknown attribute
    assert r.errors == [], f"a warning, not a rejection: {r.errors}"
