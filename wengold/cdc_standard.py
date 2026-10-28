"""Accellera CDC/RDC Interface Standard, v1.0 (March 2026).

The standard defines a case-sensitive Tcl format for describing the clock and
reset domain crossing intent of an IP block, so that CDC collateral can move
between tools. Its commands are:

    accellera_cdc::set_module   -name <module>
    accellera_cdc::set_param    -name <p> -type <int|string|Boolean> -value <v>
    accellera_cdc::set_port     -name <p> -direction <in|out|inout> -type <t> ...
    accellera_cdc::set_clock_group -name <g> -clocks <c1 c2 ...> ...
    accellera_cdc::set_reset_assertion_sequence ...

Port types are `clock`, `data`, `reset`, `async_reset`, `virtual_clock`,
`constant` and `static`.

What this module does, and does not, do
---------------------------------------
It **parses** the format and **checks it against itself and against the RTL**:

  * referential consistency — the standard requires every referenced name to be
    explicitly declared, so a port naming an undeclared clock is an error
  * mandatory attributes — `set_module` needs `-name`; `set_port` needs
    `-name`, `-direction` and `-type`
  * value validity — direction and type must come from the defined sets
  * virtual clocks must be declared, not merely referenced
  * the declared port set must match the RTL's port set

It does **not** decide whether a crossing is safe. That needs the synchroniser
structure, which this standard deliberately leaves to the tool. A report from
here says the collateral and the RTL disagree; it never says "CDC clean".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["Port", "Param", "ClockGroup", "Collateral", "Conformance",
           "parse", "check", "PORT_TYPES", "DIRECTIONS"]

PORT_TYPES = {"clock", "data", "reset", "async_reset", "virtual_clock",
              "constant", "static"}
DIRECTIONS = {"input", "output", "inout", "in", "out"}

# every command the standard defines, and the attributes each accepts
COMMANDS = {
    "set_module": {"-name"},
    "set_param": {"-name", "-type", "-value"},
    "set_port": {"-name", "-direction", "-type", "-associated_from_clocks",
                 "-associated_to_clocks", "-associated_from_reset",
                 "-associated_to_reset", "-ignore", "-cdc_static", "-constant",
                 "-associated_outputs", "-associated_inputs", "-logic",
                 "-rdc_control", "-cdc_control", "-cdc_data_from_clock",
                 "-rdc_data_from_reset", "-rdc_data_to_reset", "-rdc_data_to_clock",
                 "-blocking_polarity", "-sampling_edge"},
    "set_clock_group": {"-name", "-clocks", "-polarity", "-logic"},
    "set_reset_assertion_sequence": {"-name"},
}


@dataclass
class Param:
    name: str
    type: str = ""
    value: str = ""


@dataclass
class Port:
    name: str
    direction: str = ""
    type: str = ""
    associated_from_clocks: list = field(default_factory=list)
    associated_to_clocks: list = field(default_factory=list)
    associated_from_reset: list = field(default_factory=list)
    associated_to_reset: list = field(default_factory=list)
    ignore: bool = False
    raw: dict = field(default_factory=dict)

    @property
    def base_name(self) -> str:
        """`DATA[7:4]` -> `DATA`. A slice still refers to one RTL port."""
        return re.split(r"[\[:]", self.name.strip())[0]


@dataclass
class ClockGroup:
    name: str
    clocks: list = field(default_factory=list)
    polarity: str = ""
    logic: str = ""


@dataclass
class Collateral:
    """One IP's CDC/RDC description."""

    module: str = ""
    params: dict = field(default_factory=dict)
    ports: dict = field(default_factory=dict)
    clock_groups: dict = field(default_factory=dict)
    resets: list = field(default_factory=list)
    unknown_commands: list = field(default_factory=list)

    def clocks(self) -> set:
        return {n for n, p in self.ports.items()
                if p.type in ("clock", "virtual_clock")}


def _split_args(line: str) -> list:
    """Split on whitespace, honouring `{...}` and `"..."` grouping."""
    out, buf, depth, quote = [], "", 0, None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf += ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif ch in "\"'" and depth == 0:
            quote = ch
        elif ch.isspace() and depth == 0:
            if buf:
                out.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        out.append(buf)
    return out


def _logical_lines(text: str) -> list:
    """Join `\\` continuations and drop comments, keeping line numbers."""
    lines, buf, start = [], "", 0
    for i, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not buf and (not s or s.startswith("#")):
            continue
        if not buf:
            start = i
        if s.endswith("\\"):
            buf += " " + s[:-1].strip()
            continue
        buf += " " + s
        lines.append((start, buf.strip()))
        buf = ""
    if buf:
        lines.append((start, buf.strip()))
    return lines


def parse(text: str) -> Collateral:
    """Parse the standard's Tcl format. Unknown commands are recorded, not raised."""
    col = Collateral()
    for lineno, line in _logical_lines(text):
        m = re.match(r"accellera_cdc::(\w+)\s*(.*)$", line)
        if not m:
            continue
        cmd, rest = m.group(1), m.group(2)
        if cmd not in COMMANDS:
            col.unknown_commands.append((lineno, cmd))
            continue
        tokens = _split_args(rest)
        attrs, key = {}, None
        for tok in tokens:
            if tok.startswith("-") and tok[1:] in {a[1:] for a in COMMANDS[cmd]}:
                key = tok[1:]
                attrs[key] = ""
            elif key is not None:
                attrs[key] = (attrs[key] + " " + tok).strip()
        if cmd == "set_module":
            col.module = attrs.get("name", "")
        elif cmd == "set_param":
            p = Param(attrs.get("name", ""), attrs.get("type", ""),
                      attrs.get("value", ""))
            if p.name:
                col.params[p.name] = p
        elif cmd == "set_port":
            p = Port(
                name=attrs.get("name", ""),
                direction=attrs.get("direction", ""),
                type=attrs.get("type", ""),
                associated_from_clocks=attrs.get("associated_from_clocks", "").split(),
                associated_to_clocks=attrs.get("associated_to_clocks", "").split(),
                associated_from_reset=attrs.get("associated_from_reset", "").split(),
                associated_to_reset=attrs.get("associated_to_reset", "").split(),
                ignore="ignore" in attrs,
                raw=attrs)
            if p.name:
                col.ports[p.name] = p
        elif cmd == "set_clock_group":
            g = ClockGroup(attrs.get("name", ""), attrs.get("clocks", "").split(),
                           attrs.get("polarity", ""), attrs.get("logic", ""))
            if g.name:
                col.clock_groups[g.name] = g
        elif cmd == "set_reset_assertion_sequence":
            col.resets.append(attrs)
    return col


@dataclass
class Finding:
    severity: str          # "error" | "warning"
    rule: str
    detail: str

    def render(self) -> str:
        return f"  {self.severity:<8}{self.rule:<28}{self.detail}"


@dataclass
class Conformance:
    findings: list = field(default_factory=list)
    module: str = ""
    ports: int = 0
    clocks: int = 0

    @property
    def errors(self) -> list:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list:
        return [f for f in self.findings if f.severity == "warning"]

    def render(self) -> str:
        head = (f"  module {self.module or '(unnamed)'}   {self.ports} port(s)   "
                f"{self.clocks} clock(s)")
        if not self.findings:
            return head + "\n  conformant: no referential or mandatory-attribute errors"
        body = "\n".join(f.render() for f in self.findings)
        return (head + f"\n  {len(self.errors)} error(s), {len(self.warnings)} "
                f"warning(s)\n" + body)


def check(col: Collateral, rtl_ports: set | None = None) -> Conformance:
    """Check the collateral against itself, and against the RTL if given.

    The standard requires every referenced declaration to exist, so a port that
    names an undeclared clock is an error rather than a warning. It does not say
    whether a crossing is safe, and neither does this.
    """
    out = Conformance(module=col.module, ports=len(col.ports),
                      clocks=len(col.clocks()))

    if not col.module:
        out.findings.append(Finding("error", "module name missing",
                                    "set_module -name is mandatory"))

    declared_clocks = col.clocks()
    for name, p in col.ports.items():
        if not p.direction:
            out.findings.append(Finding("error", "direction missing",
                                        f"port {name}: -direction is mandatory"))
        elif p.direction not in DIRECTIONS:
            out.findings.append(Finding("error", "direction not defined",
                                        f"port {name}: {p.direction!r} is not one of "
                                        f"{sorted(DIRECTIONS)}"))
        if not p.type:
            out.findings.append(Finding("error", "type missing",
                                        f"port {name}: -type is mandatory"))
        elif p.type not in PORT_TYPES:
            out.findings.append(Finding("error", "type not defined",
                                        f"port {name}: {p.type!r} is not one of "
                                        f"{sorted(PORT_TYPES)}"))
        for attr, refs in (("associated_from_clocks", p.associated_from_clocks),
                           ("associated_to_clocks", p.associated_to_clocks)):
            for ref in refs:
                if ref not in col.ports:
                    out.findings.append(Finding(
                        "error", "undeclared clock",
                        f"port {name}: -{attr} names {ref!r}, which is not declared"))
                elif col.ports[ref].type not in ("clock", "virtual_clock"):
                    out.findings.append(Finding(
                        "error", "not a clock",
                        f"port {name}: -{attr} names {ref!r}, declared as "
                        f"{col.ports[ref].type!r}"))
        for attr, refs in (("associated_from_reset", p.associated_from_reset),
                           ("associated_to_reset", p.associated_to_reset)):
            for ref in refs:
                if ref not in col.ports:
                    out.findings.append(Finding(
                        "error", "undeclared reset",
                        f"port {name}: -{attr} names {ref!r}, which is not declared"))

    for name, g in col.clock_groups.items():
        for c in g.clocks:
            if c not in col.ports:
                out.findings.append(Finding("error", "undeclared clock",
                                            f"clock_group {name}: {c!r} not declared"))

    if rtl_ports is not None:
        declared = {p.base_name for p in col.ports.values()
                    if p.type != "virtual_clock"}
        for missing in sorted(declared - set(rtl_ports)):
            out.findings.append(Finding(
                "warning", "declared, not in RTL",
                f"{missing}: declared in the collateral but absent from the RTL"))
        for extra in sorted(set(rtl_ports) - declared):
            out.findings.append(Finding(
                "warning", "in RTL, not declared",
                f"{extra}: an RTL port with no CDC declaration"))

    for lineno, cmd in col.unknown_commands:
        out.findings.append(Finding("warning", "unknown command",
                                    f"line {lineno}: accellera_cdc::{cmd} is not in "
                                    f"the standard"))
    return out
