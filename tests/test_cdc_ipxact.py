"""Clause 7 — the CDC IP-XACT format, and the semantic consistency rules.

The mapping is from the standard: `data`/`clock`/`asyncReset` elements, the
`phantom` direction for a virtual clock, `clockPortReference` children under
`associatedFromClocks`/`associatedToClocks`, and `componentCDCDef/clockGroups`
for clock groups.

One asymmetry is the standard's, not a shortcut here: `reset` and `async_reset`
share a single IP-XACT element, so a round trip collapses one into the other. A
test pins that so it cannot be quietly "fixed" into a silent data loss.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from wengold.cdc_ipxact import (ACCELERA_NS, IPXACT_NS, check_scr, from_ipxact,
                                to_ipxact, to_tcl)
from wengold.cdc_standard import parse

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples/cdc/mixed_clocks_cdc.tcl"


@pytest.fixture()
def col():
    return parse(EXAMPLE.read_text())


def q(ns, tag):
    return f"{{{ns}}}{tag}"


# ---- Tcl -> IP-XACT --------------------------------------------------------
def test_it_emits_a_wellformed_component(col):
    xml = to_ipxact(col)
    root = ET.fromstring(xml)
    assert root.tag == q(IPXACT_NS, "component")
    assert root.find(q(IPXACT_NS, "name")).text == "mixed_clocks"


def test_every_port_survives_the_conversion(col):
    root = ET.fromstring(to_ipxact(col))
    names = {p.find(q(IPXACT_NS, "name")).text
             for p in root.iter(q(IPXACT_NS, "port"))}
    assert names == set(col.ports)


def test_a_clock_port_carries_the_clock_qualifier(col):
    root = ET.fromstring(to_ipxact(col))
    for pe in root.iter(q(IPXACT_NS, "port")):
        if pe.find(q(IPXACT_NS, "name")).text == "clk_a":
            qual = pe.find(f".//{q(IPXACT_NS, 'qualifier')}")
            assert qual is not None
            assert qual.find(q(IPXACT_NS, "isClock")).text == "true"


def test_a_virtual_clock_uses_the_phantom_direction():
    """The standard writes a virtual clock as direction 'phantom'."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name v -direction output "
              "-type virtual_clock")
    root = ET.fromstring(to_ipxact(c))
    wire = root.find(f".//{q(IPXACT_NS, 'wire')}")
    assert wire.find(q(IPXACT_NS, "direction")).text == "phantom"


def test_associated_clocks_become_port_references(col):
    root = ET.fromstring(to_ipxact(col))
    refs = [r.text for r in root.iter(q(ACCELERA_NS, "clockPortReference"))]
    assert "clk_a" in refs


def test_a_clock_group_becomes_a_component_cdc_def(col):
    root = ET.fromstring(to_ipxact(col))
    groups = list(root.iter(q(ACCELERA_NS, "clockGroup")))
    assert len(groups) == 1
    assert groups[0].find(q(ACCELERA_NS, "name")).text == "async_pair"


def test_the_standard_prefix_is_used(col):
    xml = to_ipxact(col)
    assert "accellera-cdc:" in xml
    assert "accellera-cdc:wireCDCDef" in xml


# ---- IP-XACT -> Tcl --------------------------------------------------------
def test_a_round_trip_preserves_module_ports_clocks_and_groups(col):
    back = from_ipxact(to_ipxact(col))
    assert back.module == col.module
    assert set(back.ports) == set(col.ports)
    assert back.clocks() == col.clocks()
    assert {g: v.clocks for g, v in back.clock_groups.items()} == \
           {g: v.clocks for g, v in col.clock_groups.items()}


def test_a_reset_round_trips_as_async_reset_and_says_so():
    """The IP-XACT format has one reset element, so this collapse is the
    standard's doing. Pinned so it is not silently 'fixed'."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name r -direction input -type reset")
    back = from_ipxact(to_ipxact(c))
    assert back.ports["r"].type == "async_reset"
    assert "async_reset" in to_tcl(back)
    assert "share one IP-XACT element" in to_tcl(back)


def test_a_virtual_clock_round_trips_as_virtual_clock():
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name v -direction output "
              "-type virtual_clock")
    back = from_ipxact(to_ipxact(c))
    assert back.ports["v"].type == "virtual_clock"


def test_associated_clocks_survive_the_round_trip(col):
    back = from_ipxact(to_ipxact(col))
    assert back.ports["d_in"].associated_to_clocks == ["clk_a"]


# ---- Clause 7.8 semantic consistency rules ---------------------------------
def test_a_good_document_passes_all_three_rules(col):
    rep = check_scr(to_ipxact(col))
    assert rep.ok, rep.render()


def test_a_reference_to_a_missing_port_is_caught():
    xml = f"""<ipxact:component xmlns:ipxact="{IPXACT_NS}"
      xmlns:accellera-cdc="{ACCELERA_NS}">
      <ipxact:name>m</ipxact:name>
      <ipxact:model><ipxact:ports>
        <ipxact:port><ipxact:name>d</ipxact:name>
          <ipxact:wire><ipxact:direction>in</ipxact:direction></ipxact:wire>
          <ipxact:vendorExtensions><accellera-cdc:wireCDCDef>
            <accellera-cdc:data><accellera-cdc:associatedToClocks>
              <accellera-cdc:clockPortReference>nope</accellera-cdc:clockPortReference>
            </accellera-cdc:associatedToClocks></accellera-cdc:data>
          </accellera-cdc:wireCDCDef></ipxact:vendorExtensions>
        </ipxact:port>
      </ipxact:ports></ipxact:model>
    </ipxact:component>"""
    rep = check_scr(xml)
    assert not rep.ok
    assert any(r == "CDCPortReferenceExists" for r, _ in rep.violations)


def test_a_clock_reference_to_a_non_clock_port_is_caught():
    xml = f"""<ipxact:component xmlns:ipxact="{IPXACT_NS}"
      xmlns:accellera-cdc="{ACCELERA_NS}">
      <ipxact:name>m</ipxact:name>
      <ipxact:model><ipxact:ports>
        <ipxact:port><ipxact:name>notclk</ipxact:name>
          <ipxact:wire><ipxact:direction>in</ipxact:direction></ipxact:wire>
        </ipxact:port>
        <ipxact:port><ipxact:name>d</ipxact:name>
          <ipxact:wire><ipxact:direction>in</ipxact:direction></ipxact:wire>
          <ipxact:vendorExtensions><accellera-cdc:wireCDCDef>
            <accellera-cdc:data><accellera-cdc:associatedToClocks>
              <accellera-cdc:clockPortReference>notclk</accellera-cdc:clockPortReference>
            </accellera-cdc:associatedToClocks></accellera-cdc:data>
          </accellera-cdc:wireCDCDef></ipxact:vendorExtensions>
        </ipxact:port>
      </ipxact:ports></ipxact:model>
    </ipxact:component>"""
    rep = check_scr(xml)
    assert any(r == "CDCClockPortReference" for r, _ in rep.violations)


def test_malformed_xml_is_reported_not_raised():
    rep = check_scr("<not xml")
    assert not rep.ok
    assert "well-formed" in rep.violations[0][1]
