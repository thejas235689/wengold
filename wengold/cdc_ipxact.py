"""Clause 7 — the CDC IP-XACT format, and back to Tcl.

The standard defines two representations of the same information: the Tcl
tool-level format (Clause 6) and an IP-XACT vendor extension (Clause 7) for
packaging an IP. This module converts between them so an IP's CDC collateral can
be consumed by a tool that speaks either.

Mapping, from Clause 7 (element names quoted from the standard's own examples
where the text shows them):

    Tcl                              IP-XACT
    ------------------------------   ------------------------------------------
    set_module -name m               ipxact:component VLNV named after m
                                     (7.8, Example 48: "<!-- Specify VLNV -->")
    set_port -name p                 ipxact:port/ipxact:name
    -direction input                 ipxact:wire/ipxact:direction (in/out/inout)
    -type data                       accellera-cdc:wireCDCDef/accellera-cdc:data
                                     + ipxact:qualifier/ipxact:isData
    -type clock                      .../accellera-cdc:clock + ipxact:isClock
    -type virtual_clock              .../accellera-cdc:clock + direction phantom
                                     (7.4, Example 45)
    -type reset / async_reset        .../accellera-cdc:asyncReset + ipxact:isReset
    -type virtual_reset              .../accellera-cdc:asyncReset + direction phantom
    -type cdc_control                .../accellera-cdc:cdcControl (7.6)
    -type rdc_control                .../accellera-cdc:rdcControl (7.6)
    -cdc_data_from_clock c           .../cdcControl/accellera-cdc:controlFromClock
                                     /accellera-cdc:clockPortReference (7.6,
                                     Example 47)
    -associated_from_clocks a b      accellera-cdc:associatedFromClocks with
                                     accellera-cdc:clockPortReference children
    -associated_to_clocks            accellera-cdc:associatedToClocks
    -associated_from_reset / _to_    accellera-cdc:associatedFromReset /
                                     associatedToReset with resetPortReference
                                     children (Table 11 names resetPortReference)
    every other Table 3 port        the camelCase element of the same name inside
    attribute                        the port-type extension (7.3: "all attributes
                                     required for CDC are captured in the
                                     extension, accellera-cdc:data")
    set_clock_group                  componentCDCDef/clockGroups/clockGroup
    set_param                        ipxact:parameters/ipxact:parameter

Clause 7.8: "Accellera IP-XACT CDC vendor extensions shall obey the semantic
consistency rules (SCRs) listed in Table 11 to be valid." Table 11 defines
**five** rules, all of which `check_scr()` implements:

    CDCPortReferenceExists     a clockPortReference, resetPortReference,
                               inputPortReference or outputPortReference shall
                               match the name of an existing wire port
    CDCClockPortReference      a clockPortReference shall reference an existing
                               port that specifies the clock qualifier
    CDCResetPortReference      a resetPortReference shall reference an existing
                               port that specifies the reset qualifier
    CDCInputPortReference      an inputPortReference shall reference an existing
                               port that specifies the data qualifier with a
                               direction of "in"
    CDCOutputPortReference     an outputPortReference shall reference an existing
                               port that specifies the data qualifier with the
                               direction of "out"

Two asymmetries, both deliberate and both stated rather than hidden:

  * `reset` and `async_reset` both map to `accellera-cdc:asyncReset`, because the
    IP-XACT format has no separate element for them. Round-tripping therefore
    collapses a `reset` into an `async_reset`. That is the standard's doing, not
    a shortcut here, and `to_tcl()` says so in a comment.
  * Clause 4.3.4 gives a virtual clock a meaningful direction ("If the virtual
    clock is internal to the block, define its direction as output. If it is
    external to the block, define its direction as input"), but Clause 7.4
    Example 45 writes every virtual clock with `ipxact:direction` = `phantom`,
    and the schema in Figure 34 has no second slot for the declared direction.
    This module therefore writes `phantom` (so the document stays conformant)
    and records the declared direction in a WENGOLD-private attribute,
    `wengold:declaredDirection`, on the clock element. The attribute is in its
    own namespace, `urn:wengold:cdc-ipxact:1.0`, precisely so it is not mistaken
    for an Accellera element. Without it the 4.3.4 direction is unrecoverable.

Where the standard's schema is a figure (Figure 33, the data extension) the
element name for a Table 3 attribute is not visible in the extracted text; those
names here are the standard's own camelCase convention, which its examples show
(`associatedFromClocks` for `-associated_from_clocks`, `controlFromClock` for
`-cdc_data_from_clock`).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .cdc_standard import Collateral, ClockGroup, Param, Port

__all__ = ["to_ipxact", "from_ipxact", "check_scr", "SCRReport",
           "IPXACT_NS", "ACCELERA_NS", "WENGOLD_NS", "TABLE11_RULES",
           "TABLE3_PORT_ATTRIBUTES"]

IPXACT_NS = "http://www.accellera.org/XMLSchema/IPXACT/1685-2022"
ACCELERA_NS = "http://www.accellera.org/XMLSchema/CDC/1.0"
WENGOLD_NS = "urn:wengold:cdc-ipxact:1.0"
VENDOR = "accellera-cdc"   # the prefix the standard uses

#: Clause 7.4 Example 45 / 7.6: `ipxact:direction` = "phantom" for a port that
#: does not exist at the module interface.
PHANTOM = "phantom"
#: The private attribute that keeps the 4.3.4 direction of a phantom port.
DECLARED_DIRECTION = "declaredDirection"

TYPE_TO_ELEMENT = {
    "data": "data",
    "clock": "clock",
    "virtual_clock": "clock",
    "reset": "asyncReset",
    "async_reset": "asyncReset",
    "virtual_reset": "asyncReset",
    "constant": "data",
    "static": "data",
    "cdc_control": "cdcControl",
    "rdc_control": "rdcControl",
}
ELEMENT_TO_TYPE = {
    "data": "data",
    "clock": "clock",
    "asyncReset": "async_reset",
    "cdcControl": "cdc_control",
    "rdcControl": "rdc_control",
}
CLOCK_LIKE = ("clock", "virtual_clock")
#: Port types that carry `ipxact:qualifier/ipxact:isData`. Table 11 rules
#: CDCInputPortReference/CDCOutputPortReference are written against "the data
#: qualifier", so the writer has to emit it for the rule to be checkable at all.
DATA_LIKE = ("data", "constant", "static")
PHANTOM_TYPES = ("virtual_clock", "virtual_reset")

DIRECTION_OUT = {"input": "in", "output": "out", "inout": "inout"}
DIRECTION_IN = {"in": "input", "out": "output", "inout": "inout"}

#: Table 11, in the order the standard lists it.
TABLE11_RULES = (
    "CDCPortReferenceExists",
    "CDCClockPortReference",
    "CDCResetPortReference",
    "CDCInputPortReference",
    "CDCOutputPortReference",
)

#: Clause 4, Table 3 — the port domain attributes — as they appear inside the
#: port-type extension. `name`, `direction` and `type` are carried by the
#: IP-XACT core elements (ipxact:name, ipxact:wire/ipxact:direction and the
#: port-type element itself), so they are not repeated in the extension.
#:
#: kind:  "scalar"         one text node
#:        "list"           Table 3 type "space-separated list" of names
#:        "clockref"       repeated accellera-cdc:clockPortReference
#:        "resetref"       repeated accellera-cdc:resetPortReference
#:        "clockref_single" one accellera-cdc:clockPortReference (Table 3:
#:                         cdc_data_from_clock "Supports only one clock")
TABLE3_PORT_ATTRIBUTES = (
    ("logic", "logic", "scalar"),
    ("polarity", "polarity", "scalar"),
    ("sampling_edge", "samplingEdge", "scalar"),
    ("blocking_polarity", "blockingPolarity", "scalar"),
    ("ignore", "ignore", "scalar"),
    ("constant", "constant", "scalar"),
    ("hamming1", "hamming1", "scalar"),
    ("clock_period", "clockPeriod", "scalar"),
    ("cdc_control_setup", "cdcControlSetup", "scalar"),
    ("cdc_control_hold", "cdcControlHold", "scalar"),
    ("rdc_clock_gate_location", "rdcClockGateLocation", "scalar"),
    ("cdc_data_from_clock", "controlFromClock", "clockref_single"),
    ("associated_from_clocks", "associatedFromClocks", "clockref"),
    ("associated_to_clocks", "associatedToClocks", "clockref"),
    ("associated_from_reset", "associatedFromReset", "resetref"),
    ("associated_to_reset", "associatedToReset", "resetref"),
    ("associated_inputs", "associatedInputs", "list"),
    ("associated_outputs", "associatedOutputs", "list"),
    ("cdc_control", "cdcControl", "list"),
    ("cdc_static", "cdcStatic", "list"),
    ("rdc_control", "rdcControl", "list"),
    ("rdc_data_from_reset", "rdcDataFromReset", "list"),
    ("rdc_data_to_reset", "rdcDataToReset", "list"),
    ("rdc_data_to_clock", "rdcDataToClock", "list"),
)
REF_KINDS = ("clockref", "resetref", "clockref_single")
REF_ELEMENT = {"clockref": "clockPortReference",
               "clockref_single": "clockPortReference",
               "resetref": "resetPortReference"}


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _sub(parent, ns, tag, text=None, **attrs):
    el = ET.SubElement(parent, _q(ns, tag), {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


def _local(tag: str) -> str:
    return tag.split("}")[-1]


# --------------------------------------------------------------------------
# Tcl -> IP-XACT
# --------------------------------------------------------------------------
def to_ipxact(col: Collateral, version: str = "1.0") -> str:
    """Render the collateral as an IP-XACT component with CDC extensions.

    `version` is the version of the Accellera standard quoted in the header
    comment; the VLNV version is carried separately (it is the IP's version, not
    the standard's) and is preserved across a round trip when the collateral
    came from `from_ipxact()`.
    """
    ET.register_namespace("ipxact", IPXACT_NS)
    ET.register_namespace(VENDOR, ACCELERA_NS)
    ET.register_namespace("wengold", WENGOLD_NS)

    vlnv = getattr(col, "vlnv", None) or {}
    name = vlnv.get("name") or col.module or "unnamed"

    root = ET.Element(_q(IPXACT_NS, "component"))
    # Clause 7.8, Example 48: "<ipxact:component> <!-- Specify VLNV -->". A
    # component without a VLNV is not addressable, and 1685-2022 requires the
    # four VLNV elements first and in this order.
    _sub(root, IPXACT_NS, "vendor", vlnv.get("vendor") or "wengold")
    _sub(root, IPXACT_NS, "library", vlnv.get("library") or "cdc")
    _sub(root, IPXACT_NS, "name", name)
    _sub(root, IPXACT_NS, "version", vlnv.get("version") or "1.0")

    model = _sub(root, IPXACT_NS, "model")
    ports_el = _sub(model, IPXACT_NS, "ports")
    for p in col.ports.values():
        pe = _sub(ports_el, IPXACT_NS, "port")
        _sub(pe, IPXACT_NS, "name", p.name)
        wire = _sub(pe, IPXACT_NS, "wire")
        direction = DIRECTION_OUT.get(p.direction, p.direction or "in")
        declared = None
        if p.type in PHANTOM_TYPES:
            # Clause 7.4 Example 45: a virtual clock is written "phantom".
            # Clause 4.3.4 still gives it a direction, so keep it aside.
            declared = direction if p.direction else None
            direction = PHANTOM
        _sub(wire, IPXACT_NS, "direction", direction)
        qual = None
        if p.type in CLOCK_LIKE:
            qual = _sub(wire, IPXACT_NS, "qualifier")
            _sub(qual, IPXACT_NS, "isClock", "true")
        elif p.type in ("reset", "async_reset", "virtual_reset"):
            qual = _sub(wire, IPXACT_NS, "qualifier")
            _sub(qual, IPXACT_NS, "isReset", "true")
        elif p.type in DATA_LIKE:
            # Table 11 CDCInputPortReference/CDCOutputPortReference are written
            # against "the data qualifier"; emit it so the rules are decidable.
            qual = _sub(wire, IPXACT_NS, "qualifier")
            _sub(qual, IPXACT_NS, "isData", "true")

        ext = _sub(pe, IPXACT_NS, "vendorExtensions")
        def_el = _sub(ext, ACCELERA_NS, "wireCDCDef")
        body = _sub(def_el, ACCELERA_NS, TYPE_TO_ELEMENT.get(p.type, "data"))
        if declared:
            body.set(_q(WENGOLD_NS, DECLARED_DIRECTION), declared)
        _write_port_attributes(body, p)

    if col.params:
        params = _sub(root, IPXACT_NS, "parameters")
        for p in col.params.values():
            pe = _sub(params, IPXACT_NS, "parameter")
            _sub(pe, IPXACT_NS, "name", p.name)
            _sub(pe, IPXACT_NS, "value", p.value or "")
            if p.type:
                _sub(pe, IPXACT_NS, "type", p.type)

    if col.clock_groups:
        ext = _sub(root, IPXACT_NS, "vendorExtensions")
        cdef = _sub(ext, ACCELERA_NS, "componentCDCDef")
        groups = _sub(cdef, ACCELERA_NS, "clockGroups")
        for g in col.clock_groups.values():
            ge = _sub(groups, ACCELERA_NS, "clockGroup")
            _sub(ge, ACCELERA_NS, "name", g.name)
            for c in g.clocks:
                _sub(ge, ACCELERA_NS, "clockPortReference", c)
            if g.polarity:
                _sub(ge, ACCELERA_NS, "polarity", g.polarity)
            if g.logic:
                _sub(ge, ACCELERA_NS, "logic", g.logic)

    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode")
    header = (f"<!-- CDC/RDC collateral for {name}, IP-XACT form.\n"
              f"     Generated by WENGOLD from the Tcl form (Accellera CDC/RDC\n"
              f"     Interface Standard v{version}, Clause 7). -->\n")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + header + xml + "\n"


def _write_port_attributes(body, p: Port) -> None:
    """Write every Clause 4 / Table 3 attribute the port carries.

    Clause 7.3: "When a port represents a data signal, all attributes required
    for CDC are captured in the extension, accellera-cdc:data". The same holds
    for the other port types (7.4 for clock, 7.5 for asyncReset, 7.6 for
    control), so the attributes are written for every type — `-logic` is not a
    clock-only attribute (Table 3 lists it for the port domain, conditions of
    usage "Optional", with no restriction to clock ports).
    """
    for tcl_name, xml_name, kind in TABLE3_PORT_ATTRIBUTES:
        if kind in ("clockref", "resetref"):
            refs = getattr(p, tcl_name, None) or []
            if not refs:
                # a Port built with only `raw` still carries the references
                refs = (p.raw.get(tcl_name) or "").split()
            if not refs:
                continue
            holder = _sub(body, ACCELERA_NS, xml_name)
            for r in refs:
                _sub(holder, ACCELERA_NS, REF_ELEMENT[kind], r)
            continue
        value = (p.raw.get(tcl_name) or "").strip()
        if not value:
            if tcl_name == "ignore" and p.ignore:
                # `-ignore` may be written with no value; the attribute is the
                # fact, not the string.
                _sub(body, ACCELERA_NS, xml_name)
            continue
        if kind == "clockref_single":
            holder = _sub(body, ACCELERA_NS, xml_name)
            _sub(holder, ACCELERA_NS, "clockPortReference", value.split()[0])
        elif kind == "list":
            _sub(body, ACCELERA_NS, xml_name, " ".join(value.split()))
        else:
            _sub(body, ACCELERA_NS, xml_name, value)


# --------------------------------------------------------------------------
# IP-XACT -> Tcl
# --------------------------------------------------------------------------
def _text(el, ns, tag) -> str:
    if el is None:
        return ""
    found = el.find(_q(ns, tag))
    return (found.text or "").strip() if found is not None else ""


def from_ipxact(xml: str) -> Collateral:
    """Read an IP-XACT component with CDC extensions back into the Tcl model."""
    col = Collateral()
    root = ET.fromstring(xml)
    ns = root.tag[1:].split("}")[0] if root.tag.startswith("{") else IPXACT_NS
    acc = ACCELERA_NS

    col.module = _text(root, ns, "name")
    vlnv = {k: _text(root, ns, k)
            for k in ("vendor", "library", "name", "version")}
    if any(vlnv.values()):
        # Collateral has no VLNV field of its own and this module may not change
        # cdc_standard.py, so the VLNV rides along as an attribute on the
        # instance. to_ipxact() reads it back.
        col.vlnv = vlnv

    for pe in root.iter(_q(ns, "parameter")):
        nm = _text(pe, ns, "name")
        if nm:
            col.params[nm] = Param(nm, _text(pe, ns, "type"), _text(pe, ns, "value"))

    for pe in root.iter(_q(ns, "port")):
        nm = _text(pe, ns, "name")
        if not nm:
            continue
        wire = pe.find(_q(ns, "wire"))
        raw_direction = _text(wire, ns, "direction")
        qual = wire.find(_q(ns, "qualifier")) if wire is not None else None
        is_clock = _text(qual, ns, "isClock") == "true"
        is_reset = _text(qual, ns, "isReset") == "true"
        is_data = _text(qual, ns, "isData") == "true"

        p = Port(name=nm)
        declared = _read_port_extension(pe, p, acc)

        if raw_direction == PHANTOM:
            # Clause 4.3.4: the declared direction survives in the private
            # attribute; without it, "internal" (output) is the 4.3.4 default
            # for a virtual clock.
            p.direction = DIRECTION_IN.get(declared, "output")
            if p.type in ("clock", ""):
                p.type = "virtual_clock"
            elif p.type in ("async_reset", ""):
                p.type = "virtual_reset"
        else:
            p.direction = DIRECTION_IN.get(raw_direction, raw_direction)

        if not p.type:
            if is_clock:
                p.type = "clock"
            elif is_reset:
                p.type = "async_reset"
            elif is_data:
                p.type = "data"
        col.ports[nm] = p

    for ge in root.iter(_q(acc, "clockGroup")):
        gname = _text(ge, acc, "name")
        if not gname:
            continue
        col.clock_groups[gname] = ClockGroup(
            gname,
            [(r.text or "").strip()
             for r in ge.findall(_q(acc, "clockPortReference"))],
            _text(ge, acc, "polarity"),
            _text(ge, acc, "logic"))
    return col


def _read_port_extension(pe, p: Port, acc: str) -> str:
    """Fill `p` from the wireCDCDef extension; return the declared direction."""
    def_el = pe.find(f".//{_q(acc, 'wireCDCDef')}")
    if def_el is None:
        return ""
    for child in list(def_el):
        tag = _local(child.tag)
        if tag not in ELEMENT_TO_TYPE:
            continue
        p.type = ELEMENT_TO_TYPE[tag]
        declared = (child.get(_q(WENGOLD_NS, DECLARED_DIRECTION)) or "").strip()
        for tcl_name, xml_name, kind in TABLE3_PORT_ATTRIBUTES:
            el = child.find(_q(acc, xml_name))
            if el is None:
                continue
            if kind in ("clockref", "resetref"):
                setattr(p, tcl_name,
                        [(r.text or "").strip()
                         for r in el.findall(_q(acc, REF_ELEMENT[kind]))])
            elif kind == "clockref_single":
                r = el.find(_q(acc, "clockPortReference"))
                if r is not None and (r.text or "").strip():
                    p.raw[tcl_name] = (r.text or "").strip()
            else:
                text = (el.text or "").strip()
                if kind == "list":
                    text = " ".join(text.split())
                if text:
                    p.raw[tcl_name] = text
        if "ignore" in p.raw:
            p.ignore = True
        return declared
    return ""


def to_tcl(col: Collateral) -> str:
    """Render back to the Clause 6 Tcl format.

    Not lossless, and the header says why: `reset` and `async_reset` share one
    IP-XACT element, so a round trip through IP-XACT returns both as
    `async_reset`.
    """
    lines = ["# Generated by WENGOLD from the IP-XACT form (Clause 7).",
             "# `reset` and `async_reset` share one IP-XACT element, so a round",
             "# trip reports both as async_reset.", ""]
    lines.append(f"accellera_cdc::set_module -name {col.module}")
    for p in col.params.values():
        lines.append(f"accellera_cdc::set_param -name {p.name}"
                     f" -type {p.type or 'string'} -value {p.value or '0'}")
    for p in col.ports.values():
        parts = [f"accellera_cdc::set_port -name {p.name}",
                 f"-direction {p.direction}", f"-type {p.type}"]
        for tcl_name, _xml_name, kind in TABLE3_PORT_ATTRIBUTES:
            if kind in ("clockref", "resetref"):
                refs = getattr(p, tcl_name, None) or []
                if refs:
                    parts.append(f"-{tcl_name} " + " ".join(refs))
                continue
            value = (p.raw.get(tcl_name) or "").strip()
            if value:
                parts.append(f"-{tcl_name} {value}")
            elif tcl_name == "ignore" and p.ignore:
                parts.append("-ignore")
        lines.append(" ".join(parts))
    for g in col.clock_groups.values():
        line = (f"accellera_cdc::set_clock_group -name {g.name} "
                f"-clocks {{{' '.join(g.clocks)}}}")
        if g.polarity:
            line += f" -polarity {g.polarity}"
        if g.logic:
            line += f" -logic {g.logic}"
        lines.append(line)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Clause 7.8 — semantic consistency rules
# --------------------------------------------------------------------------
class SCRReport:
    """The five rules from Table 11."""

    def __init__(self):
        self.violations: list = []

    def add(self, rule: str, detail: str):
        self.violations.append((rule, detail))

    @property
    def ok(self) -> bool:
        return not self.violations

    def rules_checked(self) -> tuple:
        return TABLE11_RULES

    def render(self) -> str:
        if self.ok:
            return ("  SCR: all five semantic consistency rules of Table 11 hold"
                    f" ({', '.join(TABLE11_RULES)})")
        return "  SCR: " + f"{len(self.violations)} violation(s)\n" + "\n".join(
            f"    {r}: {d}" for r, d in self.violations)


def check_scr(xml: str) -> SCRReport:
    """Apply all five rules of Table 11.

    Clause 7.8: "Accellera IP-XACT CDC vendor extensions shall obey the semantic
    consistency rules (SCRs) listed in Table 11 to be valid."
    """
    rep = SCRReport()
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        rep.add("CDCPortReferenceExists", f"not well-formed XML: {exc}")
        return rep
    ns = root.tag[1:].split("}")[0] if root.tag.startswith("{") else IPXACT_NS

    ports, clock_ports, reset_ports, data_ports, directions = {}, set(), set(), set(), {}
    for pe in root.iter(_q(ns, "port")):
        nm = _text(pe, ns, "name")
        if not nm:
            continue
        ports[nm] = pe
        wire = pe.find(_q(ns, "wire"))
        qual = wire.find(_q(ns, "qualifier")) if wire is not None else None
        if _text(qual, ns, "isClock") == "true":
            clock_ports.add(nm)
        if _text(qual, ns, "isReset") == "true":
            reset_ports.add(nm)
        if _text(qual, ns, "isData") == "true":
            data_ports.add(nm)
        directions[nm] = _text(wire, ns, "direction")

    for ref in root.iter():
        tag = _local(ref.tag)
        if tag not in ("clockPortReference", "resetPortReference",
                       "inputPortReference", "outputPortReference"):
            continue
        target = (ref.text or "").strip()
        if not target:
            continue
        if target not in ports:
            # Rule 1: the name shall match an existing wire port.
            rep.add("CDCPortReferenceExists",
                    f"{tag} names {target!r}, which is not a port")
        elif tag == "clockPortReference" and target not in clock_ports:
            rep.add("CDCClockPortReference",
                    f"{tag} names {target!r}, which has no clock qualifier")
        elif tag == "resetPortReference" and target not in reset_ports:
            rep.add("CDCResetPortReference",
                    f"{tag} names {target!r}, which has no reset qualifier")
        elif tag == "inputPortReference" and not (
                target in data_ports and directions.get(target) == "in"):
            rep.add("CDCInputPortReference",
                    f"{tag} names {target!r}, which does not specify the data "
                    f"qualifier with a direction of \"in\"")
        elif tag == "outputPortReference" and not (
                target in data_ports and directions.get(target) == "out"):
            rep.add("CDCOutputPortReference",
                    f"{tag} names {target!r}, which does not specify the data "
                    f"qualifier with the direction of \"out\"")
    return rep
