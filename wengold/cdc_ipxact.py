"""Clause 7 — the CDC IP-XACT format, and back to Tcl.

The standard defines two representations of the same information: the Tcl
tool-level format (Clause 6) and an IP-XACT vendor extension (Clause 7) for
packaging an IP. This module converts between them so an IP's CDC collateral can
be consumed by a tool that speaks either.

Mapping, from Clause 7:

    Tcl                              IP-XACT
    ------------------------------   ------------------------------------------
    set_module -name m               ipxact:component (VLNV named after m)
    set_port -name p                 ipxact:port/ipxact:name
    -direction input                 ipxact:wire/ipxact:direction
    -type data                       accellera-cdc:wireCDCDef/accellera-cdc:data
    -type clock                      .../accellera-cdc:clock
    -type virtual_clock              .../accellera-cdc:clock + direction phantom
    -type reset / async_reset        .../accellera-cdc:asyncReset
    -associated_from_clocks a b      accellera-cdc:associatedFromClocks with
                                     accellera-cdc:clockPortReference children
    -associated_to_clocks            accellera-cdc:associatedToClocks
    -logic / -polarity               accellera-cdc:logic / accellera-cdc:polarity
    set_clock_group                  componentCDCDef/clockGroups/clockGroup
    set_param                        ipxact:parameters/ipxact:parameter

Clause 7.8 also defines three semantic consistency rules, which `check_scr()`
implements: every port reference must name an existing wire port; a
`clockPortReference` must reference a port carrying the clock qualifier; a
`resetPortReference` must reference a port carrying the reset qualifier.

One deliberate asymmetry: `reset` and `async_reset` both map to
`accellera-cdc:asyncReset`, because the IP-XACT format has no separate element
for them. Round-tripping therefore collapses a `reset` into an `async_reset`.
That is the standard's doing, not a shortcut here, and `to_tcl()` says so in a
comment rather than pretending the round trip is lossless.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .cdc_standard import Collateral, ClockGroup, Param, Port

__all__ = ["to_ipxact", "from_ipxact", "check_scr", "SCRReport",
           "IPXACT_NS", "ACCELERA_NS"]

IPXACT_NS = "http://www.accellera.org/XMLSchema/IPXACT/1685-2022"
ACCELERA_NS = "http://www.accellera.org/XMLSchema/CDC/1.0"
VENDOR = "accellera-cdc"   # the prefix the standard uses

TYPE_TO_ELEMENT = {
    "data": "data",
    "clock": "clock",
    "virtual_clock": "clock",
    "reset": "asyncReset",
    "async_reset": "asyncReset",
    "constant": "data",
    "static": "data",
}
ELEMENT_TO_TYPE = {
    "data": "data",
    "clock": "clock",
    "asyncReset": "async_reset",
    "cdcControl": "data",
    "rdcControl": "data",
}
CLOCK_LIKE = ("clock", "virtual_clock")


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _sub(parent, ns, tag, text=None, **attrs):
    el = ET.SubElement(parent, _q(ns, tag), {k: str(v) for k, v in attrs.items()})
    if text is not None:
        el.text = str(text)
    return el


# --------------------------------------------------------------------------
# Tcl -> IP-XACT
# --------------------------------------------------------------------------
def to_ipxact(col: Collateral, version: str = "1.0") -> str:
    """Render the collateral as an IP-XACT component with CDC extensions."""
    ET.register_namespace("ipxact", IPXACT_NS)
    ET.register_namespace(VENDOR, ACCELERA_NS)

    root = ET.Element(_q(IPXACT_NS, "component"))
    name = col.module or "unnamed"

    vlnv = _sub(root, IPXACT_NS, "vendorExtensions")   # placeholder, replaced below
    root.remove(vlnv)
    _sub(root, IPXACT_NS, "name", name)

    if col.params:
        params = _sub(root, IPXACT_NS, "parameters")
        for p in col.params.values():
            pe = _sub(params, IPXACT_NS, "parameter")
            _sub(pe, IPXACT_NS, "name", p.name)
            if p.type:
                _sub(pe, IPXACT_NS, "value", p.value or "")
                _sub(pe, IPXACT_NS, "type", p.type)

    model = _sub(root, IPXACT_NS, "model")
    ports_el = _sub(model, IPXACT_NS, "ports")
    for p in col.ports.values():
        pe = _sub(ports_el, IPXACT_NS, "port")
        _sub(pe, IPXACT_NS, "name", p.name)
        wire = _sub(pe, IPXACT_NS, "wire")
        direction = {"input": "in", "output": "out", "inout": "inout"}.get(
            p.direction, p.direction or "in")
        if p.type == "virtual_clock":
            # a virtual clock is explicitly a port that does not exist at the
            # interface; the standard writes that as direction "phantom"
            direction = "phantom"
        _sub(wire, IPXACT_NS, "direction", direction)
        if p.type in ("clock", "virtual_clock"):
            qual = _sub(wire, IPXACT_NS, "qualifier")
            _sub(qual, IPXACT_NS, "isClock", "true")
        elif p.type in ("reset", "async_reset"):
            qual = _sub(wire, IPXACT_NS, "qualifier")
            _sub(qual, IPXACT_NS, "isReset", "true")

        ext = _sub(pe, IPXACT_NS, "vendorExtensions")
        def_el = _sub(ext, ACCELERA_NS, "wireCDCDef")
        el_name = TYPE_TO_ELEMENT.get(p.type, "data")
        body = _sub(def_el, ACCELERA_NS, el_name)

        if p.type in CLOCK_LIKE and p.raw.get("logic"):
            _sub(body, ACCELERA_NS, "logic", p.raw["logic"])
        if p.raw.get("polarity"):
            _sub(body, ACCELERA_NS, "polarity", p.raw["polarity"])
        for tcl_attr, xml_name in (("associated_from_clocks", "associatedFromClocks"),
                                   ("associated_to_clocks", "associatedToClocks")):
            refs = getattr(p, tcl_attr)
            if not refs:
                continue
            holder = _sub(body, ACCELERA_NS, xml_name)
            for r in refs:
                _sub(holder, ACCELERA_NS, "clockPortReference", r)

    if col.clock_groups:
        ext = _sub(root, IPXACT_NS, "vendorExtensions")
        cdef = _sub(ext, ACCELERA_NS, "componentCDCDef")
        groups = _sub(cdef, ACCELERA_NS, "clockGroups")
        for g in col.clock_groups.values():
            ge = _sub(groups, ACCELERA_NS, "clockGroup")
            _sub(ge, ACCELERA_NS, "name", g.name)
            for c in g.clocks:
                _sub(ge, ACCELERA_NS, "clockPortReference", c)

    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode")
    header = (f"<!-- CDC/RDC collateral for {name}, IP-XACT form.\n"
              f"     Generated by WENGOLD from the Tcl form (Accellera CDC/RDC\n"
              f"     Interface Standard v{version}, Clause 7). -->\n")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + header + xml + "\n"


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

    for pe in root.iter(_q(ns, "parameter")):
        nm = _text(pe, ns, "name")
        if nm:
            col.params[nm] = Param(nm, _text(pe, ns, "type"), _text(pe, ns, "value"))

    for pe in root.iter(_q(ns, "port")):
        nm = _text(pe, ns, "name")
        if not nm:
            continue
        wire = pe.find(_q(ns, "wire"))
        direction = _text(wire, ns, "direction")
        qual = wire.find(_q(ns, "qualifier")) if wire is not None else None
        is_clock = _text(qual, ns, "isClock") == "true"
        is_reset = _text(qual, ns, "isReset") == "true"

        p = Port(name=nm, direction={"in": "input", "out": "output",
                                     "inout": "inout", "phantom": "output"}.get(
                                         direction, direction))
        def_el = pe.find(f".//{_q(acc, 'wireCDCDef')}")
        if def_el is not None:
            for child in list(def_el):
                tag = child.tag.split("}")[-1]
                if tag in ELEMENT_TO_TYPE:
                    p.type = ELEMENT_TO_TYPE[tag]
                    logic = child.find(_q(acc, "logic"))
                    if logic is not None and (logic.text or "").strip():
                        p.raw["logic"] = logic.text.strip()
                    pol = child.find(_q(acc, "polarity"))
                    if pol is not None and (pol.text or "").strip():
                        p.raw["polarity"] = pol.text.strip()
                    for xml_name, attr in (
                            ("associatedFromClocks", "associated_from_clocks"),
                            ("associatedToClocks", "associated_to_clocks")):
                        holder = child.find(_q(acc, xml_name))
                        if holder is not None:
                            setattr(p, attr, [
                                (r.text or "").strip()
                                for r in holder.findall(_q(acc, "clockPortReference"))])
                    break
        if direction == "phantom" and is_clock:
            p.type = "virtual_clock"
        elif is_clock and not p.type:
            p.type = "clock"
        elif is_reset and not p.type:
            p.type = "async_reset"
        col.ports[nm] = p

    for ge in root.iter(_q(acc, "clockGroup")):
        gname = _text(ge, acc, "name")
        if not gname:
            continue
        col.clock_groups[gname] = ClockGroup(gname, [
            (r.text or "").strip() for r in ge.findall(_q(acc, "clockPortReference"))])
    return col


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
        lines.append(f"accellera_cdc::set_param -name {p.name} -type {p.type or 'string'}"
                     f" -value {p.value or '0'}")
    for p in col.ports.values():
        parts = [f"accellera_cdc::set_port -name {p.name}",
                 f"-direction {p.direction}", f"-type {p.type}"]
        if p.raw.get("logic"):
            parts.append(f"-logic {p.raw['logic']}")
        if p.raw.get("polarity"):
            parts.append(f"-polarity {p.raw['polarity']}")
        if p.associated_from_clocks:
            parts.append("-associated_from_clocks "
                         + " ".join(p.associated_from_clocks))
        if p.associated_to_clocks:
            parts.append("-associated_to_clocks " + " ".join(p.associated_to_clocks))
        lines.append(" ".join(parts))
    for g in col.clock_groups.values():
        lines.append(f"accellera_cdc::set_clock_group -name {g.name} "
                     f"-clocks {{{' '.join(g.clocks)}}}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Clause 7.8 — semantic consistency rules
# --------------------------------------------------------------------------
class SCRReport:
    """The three rules from Table 11."""

    def __init__(self):
        self.violations: list = []

    def add(self, rule: str, detail: str):
        self.violations.append((rule, detail))

    @property
    def ok(self) -> bool:
        return not self.violations

    def render(self) -> str:
        if self.ok:
            return "  SCR: all three semantic consistency rules hold"
        return "  SCR: " + f"{len(self.violations)} violation(s)\n" + "\n".join(
            f"    {r}: {d}" for r, d in self.violations)


def check_scr(xml: str) -> SCRReport:
    """Apply Table 11: port references must exist and carry the right qualifier."""
    rep = SCRReport()
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        rep.add("CDCPortReferenceExists", f"not well-formed XML: {exc}")
        return rep
    ns = root.tag[1:].split("}")[0] if root.tag.startswith("{") else IPXACT_NS

    ports, clock_ports, reset_ports = {}, set(), set()
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

    for ref in root.iter():
        tag = ref.tag.split("}")[-1]
        if tag not in ("clockPortReference", "resetPortReference",
                       "inputPortReference", "outputPortReference"):
            continue
        target = (ref.text or "").strip()
        if not target:
            continue
        if target not in ports:
            rep.add("CDCPortReferenceExists",
                    f"{tag} names {target!r}, which is not a port")
        elif tag == "clockPortReference" and target not in clock_ports:
            rep.add("CDCClockPortReference",
                    f"{tag} names {target!r}, which has no clock qualifier")
        elif tag == "resetPortReference" and target not in reset_ports:
            rep.add("CDCResetPortReference",
                    f"{tag} names {target!r}, which has no reset qualifier")
    return rep
