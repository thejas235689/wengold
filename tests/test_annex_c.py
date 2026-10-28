"""Annex C — the standard's own testcase list, as regression fixtures.

Annex C is **informative**: it lists unit testcases keyed to figures, with the code
hosted separately. So each fixture here is one row of Table 12, named after its
figure, and each test asserts the *purpose* that row states.

The fixtures found two real parser defects while being written:

  * `-polarity` was missing from the port attribute set, so `-type async_reset
    -polarity low` parsed the type as `"async_reset -polarity low"`.
  * `-polarity` is **mandatory** for `async_reset` (Clause 4) and the checker did
    not say so.

Both are fixed, and both have a test below so they cannot come back.
"""
from pathlib import Path

import pytest

from wengold.cdc_standard import check, parse

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "cdc"


def load(name):
    return parse((FIXTURES / f"{name}.tcl").read_text())


def test_every_fixture_is_present():
    names = sorted(p.stem for p in FIXTURES.glob("*.tcl"))
    assert len(names) >= 17, names


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.tcl")),
                         ids=lambda p: p.stem)
def test_every_annex_c_fixture_is_conformant(path):
    """Each row of Table 12 describes a well-formed IP, so none may have errors."""
    rep = check(parse(path.read_text()))
    assert not rep.errors, [f"{f.rule}: {f.detail}" for f in rep.errors]


# ---- one test per row, asserting that row's stated purpose ----------------
def test_fig02_module_domain_attribute():
    c = load("fig02_module")
    assert c.module == "fig02_module"


def test_fig03_a_virtual_clock_applies_name_direction_and_type():
    c = load("fig03_virtual_clock_named")
    v = c.ports["vclk_rx"]
    assert v.type == "virtual_clock" and v.direction == "input"
    assert v.name == "vclk_rx"


def test_fig04_associated_from_clocks_lands_on_the_port():
    assert load("fig04_associated_from_clocks").ports["data0_o"].associated_from_clocks \
        == ["clk0_i"]


def test_fig05_a_virtual_clock_is_applied():
    c = load("fig05_virtual_clock")
    assert "vclk0_o" in c.clocks()
    assert c.ports["data0_i"].associated_to_clocks == ["vclk0_o"]


def test_fig06_both_reset_associations_are_applied():
    c = load("fig06_associated_resets")
    assert c.ports["data0_i"].associated_from_reset == ["rst0_i"]
    assert c.ports["data0_o"].associated_to_reset == ["rst0_i"]


@pytest.mark.parametrize("name,port", [("fig07_ignore_hanging", "data1_i"),
                                       ("fig08_ignore_blocked", "data0_i")])
def test_fig07_fig08_ignore_is_applied(name, port):
    assert load(name).ports[port].ignore is True


def test_fig09_cdc_static_is_applied():
    assert "cdc_static" in load("fig09_cdc_static").ports["cfg_i"].raw


def test_fig10_constant_is_applied():
    p = load("fig10_constant").ports["mode_i"]
    assert p.type == "constant" and "constant" in p.raw


def test_fig12_logic_is_applied():
    assert load("fig12_logic").ports["d_i"].logic == "internal_sync"


@pytest.mark.parametrize("name,port,polarity", [
    ("fig13_active_low_reset", "rst_ni", "low"),
    ("fig14_active_high_reset", "rst_i", "high"),
])
def test_fig13_fig14_reset_polarity_from_a_virtual_clock(name, port, polarity):
    c = load(name)
    p = c.ports[port]
    assert p.type == "async_reset"
    assert p.polarity == polarity
    assert p.associated_from_clocks == ["vclk_rx"]


def test_fig17_reset_with_both_clock_associations():
    p = load("fig17_reset_with_clocks").ports["rst_i"]
    assert p.associated_from_clocks == ["clk0_i"]
    assert p.associated_to_clocks == ["clk1_i"]


@pytest.mark.parametrize("name,count", [("fig22_clock_group_a", 2),
                                        ("fig23_clock_group_b", 3)])
def test_fig22_fig23_async_clock_groups(name, count):
    c = load(name)
    assert sum(len(g.clocks) for g in c.clock_groups.values()) == count


def test_fig24_mixed_synchronous_and_asynchronous_groups():
    c = load("fig24_clock_group_c")
    assert len(c.clock_groups) == 2
    assert c.clock_groups["sync_01"].polarity == "same"


def test_fig26_reset_assertion_sequence_is_recorded():
    assert load("fig26_reset_assertion_sequence").resets


# ---- the two defects the fixtures exposed --------------------------------
def test_polarity_is_a_port_attribute():
    """It was missing, so `-type async_reset -polarity low` parsed the type as
    the string 'async_reset -polarity low'."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name r -direction input "
              "-type async_reset -polarity low")
    assert c.ports["r"].type == "async_reset"
    assert c.ports["r"].polarity == "low"


def test_polarity_is_mandatory_for_async_reset():
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name r -direction input -type async_reset")
    assert any(f.rule == "polarity missing" for f in check(c).errors)


def test_a_polarity_outside_the_defined_values_is_an_error():
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name r -direction input "
              "-type async_reset -polarity active_low")
    assert any(f.rule == "polarity not defined" for f in check(c).errors)
