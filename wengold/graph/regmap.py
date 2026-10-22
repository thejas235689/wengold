"""Register-map front-end: SystemRDL and IP-XACT to graph nodes.

A register map is a dependency too. Change a field's access policy and every test
that exercises it is in doubt; move a register and the address decode changes.
This module parses the two formats chip teams actually keep their maps in, builds
a normalised `AddressMap`, and adds register/field nodes to the graph with their
addresses and access policy so a change propagates.

Parsing is deliberately tolerant but never silent: an address collision or an
overlapping field is reported, not ignored.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .model import EdgeKind, Node, NodeKind

RDL_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<num>0[xX][0-9a-fA-F_]+|\d[\d_]*)
  | (?P<id>[A-Za-z_]\w*)
  | (?P<str>"[^"]*")
  | (?P<op>[{}\[\]:;=@,+*.\-])
""", re.VERBOSE | re.DOTALL)

_ACCESS_KEYS = {"sw", "hw", "r", "w", "rw", "onread", "onwrite"}


@dataclass
class Field:
    name: str
    msb: int
    lsb: int
    sw: str = "rw"
    hw: str = "r"
    reset: int | None = None

    @property
    def width(self) -> int:
        return abs(self.msb - self.lsb) + 1

    @property
    def mask(self) -> int:
        return ((1 << self.width) - 1) << min(self.msb, self.lsb)

    def as_dict(self) -> dict:
        return {"name": self.name, "msb": self.msb, "lsb": self.lsb, "width": self.width,
                "sw": self.sw, "hw": self.hw, "reset": self.reset}


@dataclass
class Register:
    name: str
    address: int
    width: int = 32
    fields: list[Field] = field(default_factory=list)

    @property
    def byte_size(self) -> int:
        return max(4, (self.width + 7) // 8)

    def as_dict(self) -> dict:
        return {"name": self.name, "address": hex(self.address), "width": self.width,
                "fields": [f.as_dict() for f in self.fields]}


@dataclass
class AddressMap:
    name: str
    registers: list[Register] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"name": self.name, "registers": [r.as_dict() for r in self.registers],
                "issues": self.issues}

    def check(self) -> list[str]:
        """Address collisions and overlapping fields."""
        issues = list(self.issues)
        spans = sorted((r.address, r.address + r.byte_size, r.name) for r in self.registers)
        for (a1, e1, n1), (a2, e2, n2) in zip(spans, spans[1:]):
            if a2 < e1:
                issues.append(f"address overlap: {n1} @ {hex(a1)}..{hex(e1)} and "
                              f"{n2} @ {hex(a2)}")
        for r in self.registers:
            used = 0
            for f in r.fields:
                if f.mask & used:
                    issues.append(f"field overlap in {r.name}: {f.name}")
                used |= f.mask
        return issues


# ---------------------------------------------------------------- SystemRDL
def _rdl_tokens(text: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    out, i = [], 0
    while i < len(text):
        m = RDL_TOKEN.match(text, i)
        if not m:
            i += 1
            continue
        i = m.end()
        if m.lastgroup not in ("ws", "comment"):
            out.append(m.group(0))
    return out


def _int(tok: str) -> int:
    return int(tok.replace("_", ""), 16 if tok.lower().startswith("0x") else 10)


def _match_block(toks: list[str], i: int) -> tuple[list[str], int]:
    """Return (tokens inside the brace block starting at i), index after '}'."""
    if toks[i] != "{":
        raise ValueError(f"expected '{{' at {toks[i]!r}")
    depth, j, inner = 1, i + 1, []
    while j < len(toks) and depth:
        if toks[j] == "{":
            depth += 1
        elif toks[j] == "}":
            depth -= 1
            if depth == 0:
                break
        inner.append(toks[j])
        j += 1
    return inner, j + 1


def _parse_fields(toks: list[str]) -> list[Field]:
    fields: list[Field] = []
    i = 0
    while i < len(toks):
        if toks[i] != "field":
            i += 1
            continue
        i += 1
        props: dict[str, str] = {}
        if i < len(toks) and toks[i] == "{":
            inner, i = _match_block(toks, i)
            k = 0
            while k < len(inner):
                if inner[k] in ("sw", "hw") and k + 2 < len(inner) and inner[k + 1] == "=":
                    props[inner[k]] = inner[k + 2]
                    k += 3
                else:
                    k += 1
        name = toks[i] if i < len(toks) else f"f{len(fields)}"
        i += 1
        msb = lsb = 0
        if i < len(toks) and toks[i] == "[":
            j = i + 1
            inner2 = []
            while j < len(toks) and toks[j] != "]":
                inner2.append(toks[j])
                j += 1
            if ":" in inner2:
                msb = _int(inner2[0])
                lsb = _int(inner2[-1])
            else:
                msb, lsb = _int(inner2[0]) - 1, 0
            i = j + 1
        reset = None
        if i < len(toks) and toks[i] == "=":
            reset = _int(toks[i + 1])
            i += 2
        if i < len(toks) and toks[i] == ";":
            i += 1
        fields.append(Field(name, msb, lsb, props.get("sw", "rw"), props.get("hw", "r"), reset))
    return fields


def parse_rdl(text: str) -> AddressMap:
    toks = _rdl_tokens(text)
    if not toks or toks[0] != "addrmap":
        raise ValueError("no addrmap found in the SystemRDL")
    name = toks[1]
    inner, _ = _match_block(toks, 2)
    amap = AddressMap(name=name)
    _parse_rdl_body(inner, amap, base=0, prefix="")
    amap.issues += amap.check()
    return amap


def _parse_rdl_body(toks: list[str], amap: AddressMap, base: int, prefix: str) -> None:
    i = 0
    next_addr = base
    while i < len(toks):
        tok = toks[i]
        if tok in ("reg", "regfile", "mem"):
            kind = tok
            i += 1
            inner, i = _match_block(toks, i)
            rname = toks[i] if i < len(toks) else f"{kind}{len(amap.registers)}"
            i += 1
            addr = next_addr
            if i < len(toks) and toks[i] == "@":
                addr = base + _int(toks[i + 1])
                i += 2
            if i < len(toks) and toks[i] in (";", "}"):
                i += 1
            if kind == "reg":
                fields = _parse_fields(inner)
                width = max([32] + [f.msb + 1 for f in fields])
                amap.registers.append(Register(f"{prefix}{rname}", addr, width, fields))
                next_addr = addr + max(4, (width + 7) // 8)
            else:
                _parse_rdl_body(inner, amap, base=addr, prefix=f"{prefix}{rname}.")
        else:
            i += 1


# ---------------------------------------------------------------- IP-XACT
def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _find(el, name):
    for child in el.iter():
        if _local(child.tag) == name:
            return child
    return None


def _findall(el, name):
    return [c for c in el.iter() if _local(c.tag) == name]


def _text(el, name, default=None):
    child = _find(el, name)
    if child is None or child.text is None:
        return default
    return child.text.strip()


def parse_ipxact(text: str) -> AddressMap:
    root = ET.fromstring(text)
    mm = _find(root, "memoryMap")
    if mm is None:
        raise ValueError("no memoryMap found in the IP-XACT document")
    amap = AddressMap(name=_text(mm, "name", "memoryMap") or "memoryMap")
    for block in _findall(mm, "addressBlock"):
        base = _int(_text(block, "baseAddress", "0") or "0")
        for reg in _findall(block, "register"):
            name = _text(reg, "name", "reg")
            offset = _int(_text(reg, "addressOffset", "0") or "0")
            size = int(_text(reg, "size", "32") or "32")
            fields = []
            for f in _findall(reg, "field"):
                bit_off = int(_text(f, "bitOffset", "0") or "0")
                bit_w = int(_text(f, "bitWidth", "1") or "1")
                access = _text(f, "access", "read-write") or "read-write"
                sw = "r" if access.startswith("read") and "write" not in access else "rw"
                fields.append(Field(_text(f, "name", "field"), bit_off + bit_w - 1,
                                    bit_off, sw=sw))
            amap.registers.append(Register(name, base + offset, size, fields))
    amap.issues += amap.check()
    return amap


# ---------------------------------------------------------------- graph
def add_regmap_to_graph(graph, amap: AddressMap, driver: str | None = None) -> list[str]:
    """Add register/field nodes and edges; return any issues found."""
    for reg in amap.registers:
        rid = f"reg.{reg.name}"
        graph.add_node(Node(id=rid, kind=NodeKind.REGMAP,
                            meta={"address": hex(reg.address), "width": reg.width,
                                  "size": reg.byte_size}))
        if driver:
            graph.add_edge(driver, rid, EdgeKind.DRIVES)
        for f in reg.fields:
            fid = f"{rid}.{f.name}"
            graph.add_node(Node(id=fid, kind=NodeKind.REGMAP,
                                meta={"msb": f.msb, "lsb": f.lsb, "sw": f.sw,
                                      "hw": f.hw, "reset": f.reset}))
            graph.add_edge(rid, fid, EdgeKind.DRIVES)
    for issue in amap.check():
        graph.mark_unresolved(amap.name, issue) if amap.name in graph.nodes else \
            graph.notes.append(f"regmap {amap.name}: {issue}")
    return amap.check()


def registers_from_rdl(text: str) -> list[str]:      # kept for compatibility
    return [r.name for r in parse_rdl(text).registers]
