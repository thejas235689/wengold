"""Accellera CDC/RDC Interface Standard v1.0 — parser and conformance check.

The standard's own rule is the one that matters here: "All CDC/RDC-related
declarations must be explicitly defined and referentially consistent." So a port
naming a clock nobody declared is an **error**, not a warning.

What this module deliberately does not do: decide whether a crossing is safe. That
needs the synchroniser structure, which the standard leaves to the tool.
"""
import pytest

from wengold.cdc_standard import (Collateral, Port, check, parse,
                                  DIRECTIONS, PORT_TYPES)

GOOD = """
accellera_cdc::set_module -name uart
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name clk1_i -direction input -type clock
accellera_cdc::set_port -name d_i -direction input -type data \\
  -associated_to_clocks clk0_i
accellera_cdc::set_clock_group -name g -clocks {clk0_i clk1_i}
"""


# ---- parsing ---------------------------------------------------------------
def test_the_standard_commands_parse():
    c = parse(GOOD)
    assert c.module == "uart"
    assert set(c.ports) == {"clk0_i", "clk1_i", "d_i"}
    assert c.clocks() == {"clk0_i", "clk1_i"}
    assert c.clock_groups["g"].clocks == ["clk0_i", "clk1_i"]


def test_a_backslash_continuation_joins_one_command():
    c = parse(GOOD)
    assert c.ports["d_i"].associated_to_clocks == ["clk0_i"], \
        "the continuation line was not joined to its command"


def test_braces_group_a_list_into_one_value():
    c = parse("accellera_cdc::set_clock_group -name g -clocks {a b c}")
    assert c.clock_groups["g"].clocks == ["a", "b", "c"]


def test_comments_are_ignored():
    c = parse("# a comment\naccellera_cdc::set_module -name m\n")
    assert c.module == "m"


def test_an_unknown_command_is_recorded_not_raised():
    c = parse("accellera_cdc::set_nonsense -name x")
    assert c.unknown_commands and c.unknown_commands[0][1] == "set_nonsense"


def test_a_port_slice_refers_to_its_base_port():
    c = parse("accellera_cdc::set_port -name {DATA[7:4]} -direction input -type data")
    assert list(c.ports.values())[0].base_name == "DATA"


# ---- conformance -----------------------------------------------------------
def test_a_conformant_file_has_no_errors():
    r = check(parse(GOOD))
    assert r.errors == []
    assert "conformant" in r.render()


def test_an_undeclared_clock_is_an_error():
    """The standard requires referential consistency, so this is not a warning."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name d -direction input -type data "
              "-associated_to_clocks nosuch")
    r = check(c)
    assert any(f.rule == "undeclared clock" for f in r.errors)


def test_a_reference_to_a_non_clock_is_an_error():
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name d -direction input -type data\n"
              "accellera_cdc::set_port -name notaclock -direction input -type data\n"
              "accellera_cdc::set_port -name e -direction input -type data "
              "-associated_to_clocks notaclock")
    r = check(c)
    assert any(f.rule == "not a clock" for f in r.errors)


@pytest.mark.parametrize("attr", ["-direction", "-type"])
def test_a_mandatory_attribute_is_required(attr):
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name p -direction input -type data\n"
              "accellera_cdc::set_port -name q")
    r = check(c)
    assert any("missing" in f.rule for f in r.errors)


def test_a_missing_module_name_is_an_error():
    r = check(parse("accellera_cdc::set_port -name p -direction input -type data"))
    assert any(f.rule == "module name missing" for f in r.errors)


def test_values_outside_the_defined_sets_are_errors():
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name p -direction sideways -type wrong")
    r = check(c)
    rules = {f.rule for f in r.errors}
    assert "direction not defined" in rules and "type not defined" in rules


def test_the_defined_sets_match_the_standard():
    assert PORT_TYPES == {"clock", "data", "reset", "async_reset",
                          "virtual_clock", "constant", "static"}
    assert {"input", "output", "inout"} <= DIRECTIONS


# ---- cross-check against the RTL -------------------------------------------
def test_ports_declared_but_absent_from_the_rtl_are_warnings():
    c = parse(GOOD)
    r = check(c, rtl_ports={"clk0_i", "clk1_i"})
    assert any(f.rule == "declared, not in RTL" and "d_i" in f.detail
               for f in r.warnings)


def test_rtl_ports_with_no_declaration_are_warnings():
    c = parse(GOOD)
    r = check(c, rtl_ports={"clk0_i", "clk1_i", "d_i", "surprise_o"})
    assert any(f.rule == "in RTL, not declared" and "surprise_o" in f.detail
               for f in r.warnings)


def test_a_virtual_clock_is_not_expected_in_the_rtl():
    """A virtual clock is explicitly a port that does not exist at the interface."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name vclk -direction output "
              "-type virtual_clock\n"
              "accellera_cdc::set_port -name clk -direction input -type clock")
    r = check(c, rtl_ports={"clk"})
    assert not any("vclk" in f.detail for f in r.warnings)


# ---- the shipped example ---------------------------------------------------
def test_the_example_collateral_is_conformant():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    col = parse((root / "examples/cdc/mixed_clocks_cdc.tcl").read_text())
    assert check(col).errors == []
