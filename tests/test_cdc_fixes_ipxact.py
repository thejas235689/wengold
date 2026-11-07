"""Clause 7 fixes — round-trip tests for `wengold.cdc_ipxact`.

Every test here writes IP-XACT and reads it back (or checks the emitted document
against the standard's own text) and asserts that nothing was lost. Each one
FAILS on the pre-fix module and PASSES on the fixed one.

Authority for every claim: `CDC_Standard_text.txt`, quoted in the test docstrings.

  * Clause 7.8 + Table 11 — five semantic consistency rules
  * Clause 7.3 — "all attributes required for CDC are captured in the extension,
    accellera-cdc:data"
  * Clause 7.5 — "In addition to the accellera-cdc:logic attribute in the
    accellera-cdc:asyncReset extension, there are additional available
    attributes; e.g., polarity, associatedFromClocks, and associatedToClocks"
  * Clause 7.6 — accellera-cdc:cdcControl / accellera-cdc:rdcControl and
    accellera-cdc:controlFromClock (Example 47)
  * Clause 7.4 / Example 45 — a virtual clock is written direction "phantom"
  * Clause 4.3.4 — a virtual clock's direction is meaningful (internal -> output,
    external -> input)
  * Clause 7.8 / Example 48 — "<!-- Specify VLNV -->"
"""
import xml.etree.ElementTree as ET

from wengold import cdc_ipxact as ipx
from wengold.cdc_ipxact import (ACCELERA_NS, IPXACT_NS, check_scr, from_ipxact,
                                to_ipxact, to_tcl)
from wengold.cdc_standard import Collateral, Param, Port, parse


def q(ns, tag):
    return f"{{{ns}}}{tag}"


def ports_by_name(xml):
    root = ET.fromstring(xml)
    out = {}
    for pe in root.iter(q(IPXACT_NS, "port")):
        out[pe.find(q(IPXACT_NS, "name")).text] = pe
    return out


# --------------------------------------------------------------------------
# Finding 1 — Table 11 has FIVE rules, not three
# --------------------------------------------------------------------------
#: Quoted from CDC_Standard_text.txt lines 3575-3636 (Table 11):
#:
#:   CDCPortReferenceExists  A port reference identified by clockPortReference,
#:                           resetPortReference, inputPortReference, or
#:                           outputPortReference shall match the name of an
#:                           existing wire port.
#:   CDCClockPortReference   A clockPortReference shall reference an existing
#:                           port that specifies the clock qualifier.
#:   CDCResetPortReference   A resetPortReference shall reference an existing
#:                           port that specifies the reset qualifier.
#:   CDCInputPortReference   An inputPortReference shall reference an existing
#:                           port that specifies the data qualifier with a
#:                           direction of "in".
#:   CDCOutputPortReference  An outputPortReference shall reference an existing
#:                           port that specifies the data qualifier with the
#:                           direction of "out".


def test_the_five_table_11_rules_are_all_implemented():
    """Table 11 names five rules; the code must know about all five."""
    assert list(ipx.TABLE11_RULES) == [
        "CDCPortReferenceExists",
        "CDCClockPortReference",
        "CDCResetPortReference",
        "CDCInputPortReference",
        "CDCOutputPortReference",
    ]
    rep = check_scr(to_ipxact(parse("accellera_cdc::set_module -name m\n"
                                    "accellera_cdc::set_port -name c "
                                    "-direction input -type clock")))
    assert rep.ok
    assert "five" in rep.render()


def _doc(ports_xml):
    return f"""<ipxact:component xmlns:ipxact="{IPXACT_NS}"
      xmlns:accellera-cdc="{ACCELERA_NS}">
      <ipxact:name>m</ipxact:name>
      <ipxact:model><ipxact:ports>{ports_xml}</ipxact:ports></ipxact:model>
    </ipxact:component>"""


DATA_IN = """<ipxact:port><ipxact:name>d_in</ipxact:name>
  <ipxact:wire><ipxact:direction>in</ipxact:direction>
    <ipxact:qualifier><ipxact:isData>true</ipxact:isData></ipxact:qualifier>
  </ipxact:wire></ipxact:port>"""
DATA_OUT = """<ipxact:port><ipxact:name>d_out</ipxact:name>
  <ipxact:wire><ipxact:direction>out</ipxact:direction>
    <ipxact:qualifier><ipxact:isData>true</ipxact:isData></ipxact:qualifier>
  </ipxact:wire></ipxact:port>"""


def test_an_input_port_reference_to_an_output_port_is_caught():
    """Rule CDCInputPortReference: the target must be data-qualified, direction
    "in". An inputPortReference naming an *output* port must be a violation."""
    xml = _doc(DATA_IN + DATA_OUT + """<ipxact:port><ipxact:name>ff</ipxact:name>
      <ipxact:wire><ipxact:direction>out</ipxact:direction></ipxact:wire>
      <ipxact:vendorExtensions><accellera-cdc:wireCDCDef>
        <accellera-cdc:data><accellera-cdc:associatedInputs>
          <accellera-cdc:inputPortReference>d_out</accellera-cdc:inputPortReference>
        </accellera-cdc:associatedInputs></accellera-cdc:data>
      </accellera-cdc:wireCDCDef></ipxact:vendorExtensions></ipxact:port>""")
    rep = check_scr(xml)
    assert not rep.ok
    assert [r for r, _ in rep.violations] == ["CDCInputPortReference"]


def test_an_output_port_reference_to_an_input_port_is_caught():
    """Rule CDCOutputPortReference: data qualifier, direction "out"."""
    xml = _doc(DATA_IN + DATA_OUT + """<ipxact:port><ipxact:name>ff</ipxact:name>
      <ipxact:wire><ipxact:direction>in</ipxact:direction></ipxact:wire>
      <ipxact:vendorExtensions><accellera-cdc:wireCDCDef>
        <accellera-cdc:data><accellera-cdc:associatedOutputs>
          <accellera-cdc:outputPortReference>d_in</accellera-cdc:outputPortReference>
        </accellera-cdc:associatedOutputs></accellera-cdc:data>
      </accellera-cdc:wireCDCDef></ipxact:vendorExtensions></ipxact:port>""")
    rep = check_scr(xml)
    assert not rep.ok
    assert [r for r, _ in rep.violations] == ["CDCOutputPortReference"]


def test_correct_input_and_output_port_references_pass():
    xml = _doc(DATA_IN + DATA_OUT + """<ipxact:port><ipxact:name>ff</ipxact:name>
      <ipxact:wire><ipxact:direction>in</ipxact:direction></ipxact:wire>
      <ipxact:vendorExtensions><accellera-cdc:wireCDCDef>
        <accellera-cdc:data>
          <accellera-cdc:associatedInputs>
            <accellera-cdc:inputPortReference>d_in</accellera-cdc:inputPortReference>
          </accellera-cdc:associatedInputs>
          <accellera-cdc:associatedOutputs>
            <accellera-cdc:outputPortReference>d_out</accellera-cdc:outputPortReference>
          </accellera-cdc:associatedOutputs>
        </accellera-cdc:data>
      </accellera-cdc:wireCDCDef></ipxact:vendorExtensions></ipxact:port>""")
    rep = check_scr(xml)
    assert rep.ok, rep.render()


def test_the_writer_emits_the_data_qualifier_the_two_new_rules_need():
    """Table 11 rules 4 and 5 are written against "the data qualifier", so a
    document this module writes must carry it or the rules are undecidable."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name d -direction input -type data")
    wire = ports_by_name(to_ipxact(c))["d"].find(q(IPXACT_NS, "wire"))
    qual = wire.find(q(IPXACT_NS, "qualifier"))
    assert qual.find(q(IPXACT_NS, "isData")).text == "true"


# --------------------------------------------------------------------------
# Finding 2 — control ports lost their type on the round trip
# --------------------------------------------------------------------------
def test_a_cdc_control_port_round_trips_as_cdc_control():
    """Clause 7.6: "When a port represents a CDC or RDC control signal, the
    corresponding attributes are captured in the extension
    accellera-cdc:cdcControl or accellera-cdc:rdcControl"."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name v -direction input -type cdc_control "
              "-polarity high\n"
              "accellera_cdc::set_port -name r -direction input -type rdc_control "
              "-polarity low -blocking_polarity 1")
    xml = to_ipxact(c)
    assert "accellera-cdc:cdcControl" in xml
    assert "accellera-cdc:rdcControl" in xml
    back = from_ipxact(xml)
    assert back.ports["v"].type == "cdc_control"
    assert back.ports["r"].type == "rdc_control"
    assert back.ports["v"].raw["polarity"] == "high"
    assert back.ports["r"].raw["blocking_polarity"] == "1"
    assert "-type cdc_control" in to_tcl(back)


# --------------------------------------------------------------------------
# Finding 3 — controlFromClock was neither written nor read
# --------------------------------------------------------------------------
def test_control_from_clock_is_written_and_read():
    """Clause 7.6, Example 47:
    <accellera-cdc:cdcControl><accellera-cdc:controlFromClock>
      <accellera-cdc:clockPortReference>i_clk</accellera-cdc:clockPortReference>
    </accellera-cdc:controlFromClock></accellera-cdc:cdcControl>
    Table 3: cdc_data_from_clock "Supports only one clock"."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name i_clk -direction input -type clock\n"
              "accellera_cdc::set_port -name r_valid -direction input "
              "-type cdc_control -polarity high -cdc_data_from_clock i_clk")
    xml = to_ipxact(c)
    root = ET.fromstring(xml)
    ctrl = root.find(f".//{q(ACCELERA_NS, 'cdcControl')}")
    assert ctrl is not None
    ref = ctrl.find(f"{q(ACCELERA_NS, 'controlFromClock')}/"
                    f"{q(ACCELERA_NS, 'clockPortReference')}")
    assert ref is not None and ref.text == "i_clk"
    back = from_ipxact(xml)
    assert back.ports["r_valid"].raw["cdc_data_from_clock"] == "i_clk"
    assert "-cdc_data_from_clock i_clk" in to_tcl(back)
    # the reference is a clockPortReference, so rule CDCClockPortReference bites
    assert check_scr(xml).ok


# --------------------------------------------------------------------------
# Finding 4 — -logic was written only for clock-like ports
# --------------------------------------------------------------------------
def test_logic_survives_on_data_and_reset_ports():
    """Table 3 lists `logic` for the port domain with no restriction to clocks;
    Clause 7.5 says the asyncReset extension carries accellera-cdc:logic."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name d -direction input -type data "
              "-logic internal_sync\n"
              "accellera_cdc::set_port -name r -direction input "
              "-type async_reset -polarity low -logic glitch_free_combo")
    xml = to_ipxact(c)
    root = ET.fromstring(xml)
    assert root.find(f".//{q(ACCELERA_NS, 'data')}/"
                     f"{q(ACCELERA_NS, 'logic')}").text == "internal_sync"
    assert root.find(f".//{q(ACCELERA_NS, 'asyncReset')}/"
                     f"{q(ACCELERA_NS, 'logic')}").text == "glitch_free_combo"
    back = from_ipxact(xml)
    assert back.ports["d"].raw["logic"] == "internal_sync"
    assert back.ports["r"].raw["logic"] == "glitch_free_combo"


# --------------------------------------------------------------------------
# Finding 5 — a virtual clock's direction was lost
# --------------------------------------------------------------------------
def test_a_virtual_clock_keeps_its_declared_direction():
    """Clause 7.4 / Example 45 write the direction as "phantom"; Clause 4.3.4
    still says "If the virtual clock is internal to the block, define its
    direction as output. If it is external to the block, define its direction as
    input." Both must survive."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name vout -direction output "
              "-type virtual_clock\n"
              "accellera_cdc::set_port -name vin -direction input "
              "-type virtual_clock")
    xml = to_ipxact(c)
    for nm in ("vout", "vin"):
        wire = ports_by_name(xml)[nm].find(q(IPXACT_NS, "wire"))
        assert wire.find(q(IPXACT_NS, "direction")).text == "phantom"
    back = from_ipxact(xml)
    assert back.ports["vout"].type == "virtual_clock"
    assert back.ports["vout"].direction == "output"
    assert back.ports["vin"].type == "virtual_clock"
    assert back.ports["vin"].direction == "input"
    assert "-direction input -type virtual_clock" in to_tcl(back)


# --------------------------------------------------------------------------
# Finding 6 — the extension carried 4 of the Table 3 attributes
# --------------------------------------------------------------------------
#: Every port-domain attribute of Clause 4, Table 3 that is not carried by an
#: IP-XACT core element. `name`, `direction` and `type` travel as ipxact:name,
#: ipxact:wire/ipxact:direction and the port-type element.
TABLE3_VALUES = {
    "logic": "combo",
    "polarity": "low",
    "sampling_edge": "pos",
    "blocking_polarity": "1",
    "ignore": "blocked",
    "constant": "8'hFF",
    "hamming1": "1",
    "clock_period": "10",
    "cdc_control_setup": "3",
    "cdc_control_hold": "-2",
    "rdc_clock_gate_location": "internal",
    "cdc_data_from_clock": "clk",
    "associated_inputs": "a b",
    "associated_outputs": "y",
    "cdc_control": "valid",
    "cdc_static": "clk",
    "rdc_control": "blk",
    "rdc_data_from_reset": "rst",
    "rdc_data_to_reset": "rst",
    "rdc_data_to_clock": "clk",
}


def test_every_table_3_port_attribute_round_trips():
    """Clause 7.3: "When a port represents a data signal, all attributes required
    for CDC are captured in the extension, accellera-cdc:data"."""
    col = Collateral(module="t3")
    col.ports["clk"] = Port("clk", "input", "clock")
    col.ports["rst"] = Port("rst", "input", "async_reset",
                            raw={"polarity": "low"})
    col.ports["valid"] = Port("valid", "input", "cdc_control",
                              raw={"polarity": "high",
                                   "cdc_data_from_clock": "clk"})
    col.ports["d"] = Port("d", "input", "data", raw=dict(TABLE3_VALUES))
    xml = to_ipxact(col)
    back = from_ipxact(xml)
    assert set(back.ports) == set(col.ports)
    for name, value in TABLE3_VALUES.items():
        assert back.ports["d"].raw.get(name) == value, name


def test_every_table_3_attribute_name_is_known_to_the_module():
    """The module must cover the whole of Table 3's port domain, not a sample."""
    covered = {"name", "direction", "type"}
    covered |= {tcl for tcl, _xml, _kind in ipx.TABLE3_PORT_ATTRIBUTES}
    table3 = {
        "name", "direction", "type", "logic", "cdc_data_from_clock",
        "associated_from_clocks", "associated_to_clocks", "associated_inputs",
        "associated_outputs", "cdc_control", "cdc_control_setup",
        "cdc_control_hold", "sampling_edge", "polarity", "blocking_polarity",
        "ignore", "cdc_static", "constant", "hamming1", "clock_period",
        "associated_from_reset", "associated_to_reset", "rdc_control",
        "rdc_data_from_reset", "rdc_data_to_reset", "rdc_data_to_clock",
        "rdc_clock_gate_location",
    }
    assert table3 - covered == set()


def test_reset_references_use_reset_port_reference_elements():
    """Table 11 rule CDCResetPortReference exists because the format carries
    resetPortReference elements; associatedFromReset/ToReset must use them."""
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name rst -direction input "
              "-type async_reset -polarity low\n"
              "accellera_cdc::set_port -name d -direction output -type data "
              "-associated_from_reset rst")
    xml = to_ipxact(c)
    root = ET.fromstring(xml)
    ref = root.find(f".//{q(ACCELERA_NS, 'resetPortReference')}")
    assert ref is not None and ref.text == "rst"
    assert from_ipxact(xml).ports["d"].associated_from_reset == ["rst"]
    assert check_scr(xml).ok


# --------------------------------------------------------------------------
# Finding 7 — no VLNV
# --------------------------------------------------------------------------
def test_the_component_has_a_vlnv_and_it_round_trips():
    """Clause 7.8, Example 48: "<ipxact:component> <!-- Specify VLNV -->"."""
    c = parse("accellera_cdc::set_module -name alu")
    root = ET.fromstring(to_ipxact(c))
    for tag in ("vendor", "library", "name", "version"):
        el = root.find(q(IPXACT_NS, tag))
        assert el is not None and el.text, tag
    assert root.find(q(IPXACT_NS, "name")).text == "alu"
    # children must be the four VLNV elements, first and in order (1685-2022)
    assert [ch.tag for ch in list(root)[:4]] == [
        q(IPXACT_NS, t) for t in ("vendor", "library", "name", "version")]
    back = from_ipxact(to_ipxact(c))
    root2 = ET.fromstring(to_ipxact(back))
    assert root2.find(q(IPXACT_NS, "vendor")).text == \
        root.find(q(IPXACT_NS, "vendor")).text
    assert root2.find(q(IPXACT_NS, "version")).text == \
        root.find(q(IPXACT_NS, "version")).text


# --------------------------------------------------------------------------
# The whole document, twice through, loses nothing
# --------------------------------------------------------------------------
LIST_FIELDS = ("associated_from_clocks", "associated_to_clocks",
               "associated_from_reset", "associated_to_reset")

RICH_TCL = """
accellera_cdc::set_module -name rich
accellera_cdc::set_param -name W -type int -value 8
accellera_cdc::set_port -name clk_a -direction input -type clock -logic combo
accellera_cdc::set_port -name vclk_o -direction output -type virtual_clock -logic internal
accellera_cdc::set_port -name rst_n -direction input -type async_reset -polarity low \\
  -logic glitch_free_combo -associated_to_clocks clk_a
accellera_cdc::set_port -name d_in -direction input -type data \\
  -associated_to_clocks clk_a -logic internal_sync -sampling_edge pos \\
  -cdc_control_setup 3 -cdc_control_hold -2 -ignore hanging
accellera_cdc::set_port -name valid -direction input -type cdc_control \\
  -polarity high -cdc_data_from_clock clk_a
accellera_cdc::set_port -name d_out -direction output -type data \\
  -associated_from_clocks clk_a
accellera_cdc::set_clock_group -name grp -clocks {clk_a vclk_o}
"""


def test_a_rich_document_survives_two_round_trips():
    col = parse(RICH_TCL)
    once = from_ipxact(to_ipxact(col))
    twice = from_ipxact(to_ipxact(once))
    assert twice.module == col.module
    assert set(twice.ports) == set(col.ports)
    assert {k: (v.type, v.direction) for k, v in twice.ports.items()} == \
           {k: (v.type, v.direction) for k, v in col.ports.items()}
    for name, p in col.ports.items():
        q_ = twice.ports[name]
        assert (q_.associated_from_clocks, q_.associated_to_clocks,
                q_.associated_from_reset, q_.associated_to_reset) == \
               (p.associated_from_clocks, p.associated_to_clocks,
                p.associated_from_reset, p.associated_to_reset), name
        for attr, value in p.raw.items():
            if attr in ("name", "direction", "type"):
                continue          # carried by the IP-XACT core elements
            if attr in LIST_FIELDS:
                continue          # compared as Port fields, just above
            assert q_.raw.get(attr) == value, (name, attr)
    assert twice.params["W"] == Param("W", "int", "8")
    assert {g: v.clocks for g, v in twice.clock_groups.items()} == \
           {g: v.clocks for g, v in col.clock_groups.items()}
    assert check_scr(to_ipxact(twice)).ok


def test_a_param_without_a_type_keeps_its_value():
    """`set_param -name p -value 0` has no type; the value must not be dropped."""
    col = Collateral(module="m", params={"p": Param("p", "", "42")})
    back = from_ipxact(to_ipxact(col))
    assert back.params["p"].value == "42"
