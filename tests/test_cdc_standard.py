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
    """Clause 4 defines the port types; Clause 7.6 adds the two control types.

    `cdc_control` and `rdc_control` were missing until v0.58.0, so a conformant file
    declaring one was rejected — the same class of bug as the four missing
    attributes.
    """
    assert PORT_TYPES == {"clock", "data", "reset", "async_reset",
                          "virtual_clock", "constant", "static",
                          "cdc_control", "rdc_control", "virtual_reset"}
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


# ---- the attribute sets must match the standard --------------------------
def test_every_attribute_the_standard_names_is_accepted():
    """The code must accept every attribute the standard defines.

    A checker that rejects a conformant file is worse than one that misses an
    unknown attribute, and four were missing: `-frequency`, `-virtual_port` and
    `-rdc_clock_gate_location` on `set_port`, and `-assert_sequence` on
    `set_reset_assertion_sequence`. All four appear in the standard's own worked
    examples.
    """
    import json
    from pathlib import Path

    from wengold.cdc_standard import COMMANDS

    path = Path(__file__).parent / "fixtures" / "cdc_attributes.json"
    fixture = json.loads(path.read_text())
    checked = 0
    for cmd, attrs in fixture.items():
        if cmd.startswith("_"):
            continue
        for a in attrs:
            assert a in COMMANDS[cmd], (
                f"{cmd} rejects {a}, which the standard defines")
            checked += 1
    assert checked > 30, "the fixture must not be near-empty"


def test_a_port_using_a_newly_added_attribute_passes_the_checker():
    """End to end: a file the standard's own examples would produce.

    Before these four attributes were added this reported "unknown attribute",
    which is a checker failing a conformant input.
    """
    from wengold.cdc_standard import check, parse

    text = ("accellera_cdc::set_module -name top\n"
            "accellera_cdc::set_port -name CLK -direction input -type clock "
            "-virtual_port p2 -frequency 100\n"
            "accellera_cdc::set_reset_assertion_sequence -name reset_seq_1 "
            "-assert_sequence {rst1_n_i rst0_n_i}\n")
    conformance = check(parse(text), {"CLK"})
    # `Finding` here has `.detail`, not `.message` (that is the FSL class). This
    # comprehension read `.message` and so would have raised AttributeError the
    # moment any finding existed — it passed only because this input produces
    # none, which means it could never have failed for the reason it names.
    # "unknown" is the `rule`, not the `detail` — match both, so the filter cannot
    # silently select nothing again.
    def unknown_of(r):
        return [f.detail for f in r.findings
                if "unknown" in (f.rule + " " + f.detail).lower()]

    unknown = unknown_of(conformance)
    assert not unknown, unknown
    # and prove the list is reachable, so a silent pass is impossible
    bad = check(parse(text + "accellera_cdc::set_port -name d -direction input "
                             "-type data -bogus_attr x\n"), {"CLK"})
    assert unknown_of(bad), \
        "the assertion above is vacuous unless an unknown attribute is reported"
