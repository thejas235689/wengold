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

  * referential consistency — Clause 4: "All CDC/RDC-related declarations (such
    as modules, ports, and parameters) must be explicitly defined and
    referentially consistent." So a port naming an undeclared clock, port or
    control is an error
  * mandatory attributes — Clause 6.2 (`set_module -name`), Table 3
    (`set_port` `-name`, `-direction`, `-type`), with the Clause 4.3.8
    exemption for `-constant` ports
  * value validity — direction and type from the defined sets, and the
    enumerated attributes Table 3 and Table 2 define (`-ignore`, `-logic`,
    `-sampling_edge`, `-polarity`, parameter `-type`, parameter `-ignore`)
  * Clause 6.3 b) — a parameter declared `-ignore` and still referred to in a
    later command
  * Clause 6.4 b) — an attribute specified for a type of port it does not apply
    to
  * Clause 6.5 — every clock named by a clock group must exist in the design
  * virtual clocks and virtual resets must be declared, not merely referenced
  * the declared port set must match the RTL's port set

It does **not** decide whether a crossing is safe. That needs the synchroniser
structure, which this standard deliberately leaves to the tool. A report from
here says the collateral and the RTL disagree; it never says "CDC clean".

Every check below cites the clause it enforces. Where the standard states a
requirement but not an error condition, the check reports a *warning*: Clause
6.1's "the accellera_cdc namespace cannot include non-standard extensions" is a
NOTE, and a NOTE is not an error condition.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = ["Port", "Param", "ClockGroup", "Collateral", "Conformance",
           "parse", "check", "PORT_TYPES", "DIRECTIONS"]

PORT_TYPES = {"clock", "data", "reset", "async_reset", "virtual_clock",
              "constant", "static",
              # Clause 7.6: a port that represents a CDC or RDC control signal.
              # Absent until now, so a conformant file declaring one was rejected.
              "cdc_control", "rdc_control",
              # Table 3 and Clause 5 d) 2): a virtual reset, used the same way as
              # a virtual clock. Absent, so a conformant declaration was rejected.
              "virtual_reset"}
DIRECTIONS = {"input", "output", "inout", "in", "out"}

CLOCK_LIKE = ("clock", "virtual_clock")
RESET_LIKE = ("reset", "async_reset", "virtual_reset")
CONTROL_TYPES = ("cdc_control", "rdc_control")

# Table 3, `ignore`: "defined set {blocked, hanging}".
IGNORE_VALUES = {"blocked", "hanging"}
# Table 3, `logic`: "defined set {combo, inverter, glitch_free_combo,
# internal_sync}"; 4.3.10 spells the same four values out in prose.
LOGIC_VALUES = {"combo", "inverter", "glitch_free_combo", "internal_sync"}
# Table 3, `sampling_edge`: "defined set {pos, neg}".
SAMPLING_EDGES = {"pos", "neg"}
# Table 3, `polarity`: "defined set {high, low, low_high}".
POLARITY_VALUES = {"high", "low", "low_high"}
# Table 2, `type`: "defined set {int, string, Boolean*, number (hex, decimal,
# oct, binary)}  * Boolean values 0/1 and true/false (case independent)".
PARAM_TYPES = {"int", "string", "boolean", "number",
               "hex", "decimal", "oct", "binary"}

# every command the standard defines, and the attributes each accepts
COMMANDS = {
    "set_module": {"-name"},
    # Table 2 gives the parameter domain four attributes: name, value, type and
    # ignore. `-ignore` was missing, so Clause 6.3 b) could not be enforced.
    "set_param": {"-name", "-type", "-value", "-ignore"},
    "set_port": {"-name", "-direction", "-type", "-associated_from_clocks",
                 "-associated_to_clocks", "-associated_from_reset",
                 "-associated_to_reset", "-ignore", "-cdc_static", "-constant",
                 "-associated_outputs", "-associated_inputs", "-logic",
                 "-rdc_control", "-cdc_control", "-cdc_data_from_clock",
                 "-rdc_data_from_reset", "-rdc_data_to_reset", "-rdc_data_to_clock",
                 "-blocking_polarity", "-sampling_edge", "-cdc_control_setup",
                 "-cdc_control_hold", "-cdc_control", "-polarity",
                 # §5.2 / §5.3: named in the standard's own examples and never
                 # in the code, so a conformant file using them was rejected
                 "-frequency", "-virtual_port", "-rdc_clock_gate_location",
                 # §5.6/§5.7: the singular form, used in the standard's own
                 # examples alongside the plural. I dismissed it as a hyphenation
                 # artefact in v0.54.3; it is a real attribute.
                 "-associated_from_clock", "-associated_to_clock",
                 # Table 3: `hamming1` — "Boolean {0 or 1, true or false},
                 # Default: 0 or false (case independent), Optional". Missing, so
                 # a conformant file using it was rejected.
                 "-hamming1",
                 # Table 3: `clock_period` — "string {clock period}, Conditional
                 # ... required for generating assertions, including fast to slow
                 # assertions. See also 8.4". Missing, same defect.
                 "-clock_period"},
    "set_clock_group": {"-name", "-clocks", "-polarity", "-logic"},
    "set_reset_assertion_sequence": {"-name", "-assert_sequence"},
}

# An attribute token: `-name`, `-cdc_control`, `-hamming1`. Deliberately *not*
# `-2`: Table 3's own comment for `-cdc_control_setup` says "If the value is
# -2 ...", so a leading dash followed by a digit is a value, not an attribute.
_ATTRIBUTE = re.compile(r"^-[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class Param:
    name: str
    type: str = ""
    value: str = ""
    # Table 2, `ignore`: "Tells that the parameter can be ignored."
    ignore: bool = False


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

    def has(self, attr: str) -> bool:
        """True when the attribute was written, even with an empty value."""
        return attr in self.raw

    def attr(self, attr: str) -> str:
        return (self.raw.get(attr) or "").strip()

    def refs(self, attr: str) -> list:
        """The space-separated list an attribute carries (Table 3's `list` type)."""
        return self.attr(attr).split()

    @property
    def ignore_value(self) -> str:
        """Table 3: `ignore` is a defined set, `blocked` or `hanging`."""
        return self.attr("ignore").strip().lower()

    @property
    def sampling_edge(self) -> str:
        """Clause 8.2: the active edge of the first flop, `pos` or `neg`."""
        return (self.raw.get("sampling_edge") or "").strip().lower()

    @property
    def control_setup(self) -> str:
        """Clause 8.3: how long the data must be stable before the control enables."""
        return (self.raw.get("cdc_control_setup") or "").strip()

    @property
    def control_hold(self) -> str:
        """Clause 8.3: how long it must stay stable after the control disables."""
        return (self.raw.get("cdc_control_hold") or "").strip()

    @property
    def logic(self) -> str:
        return (self.raw.get("logic") or "").strip().lower()

    @property
    def polarity(self) -> str:
        """Table 3: `low`, `high` or `low_high`. Mandatory for async_reset,
        cdc_control and rdc_control."""
        return (self.raw.get("polarity") or "").strip().lower()

    @property
    def hamming1(self) -> str:
        """Table 3: "Boolean {0 or 1, true or false}, Default: 0 or false"."""
        return (self.raw.get("hamming1") or "").strip().lower()

    @property
    def clock_period(self) -> str:
        """Table 3: "string {clock period}"."""
        return (self.raw.get("clock_period") or "").strip()

    @property
    def is_constant(self) -> bool:
        """Clause 4.3.8: a port carrying `-constant` needs only name and direction."""
        return self.has("constant")

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
    # (line, command, attribute) — Clause 6.1's namespace "cannot include
    # non-standard extensions"; a NOTE, so these are reported, not raised.
    unknown_attributes: list = field(default_factory=list)
    # Table 6 makes a clock group's `name` Optional, so an unnamed group is
    # conformant and must still have its clocks checked (Clause 6.5).
    unnamed_clock_groups: list = field(default_factory=list)
    # Clause 6.3 b): (line, command, parameter, declaring line).
    ignored_param_refs: list = field(default_factory=list)

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


def _names(text: str, name: str) -> bool:
    """True when `name` occurs in `text` as a whole identifier.

    Clause 6.3 b) talks about a parameter being "referred to"; a reference is
    the identifier itself, so `DATA[MSB:0]` refers to `MSB` while `MSB_i` does
    not.
    """
    if not name:
        return False
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])",
                     text) is not None


def _truthy(value: str) -> bool:
    """Table 2/Table 3 Boolean: {0 or 1, true or false}, case independent.

    A bare `-ignore` with no value is read as true, as the Annex C fixtures do.
    """
    return value.strip().lower() not in {"0", "false"}


def parse(text: str) -> Collateral:
    """Parse the standard's Tcl format. Unknown commands are recorded, not raised.

    An unknown `-attribute` is recorded under its own name. It used to be folded
    into the previous attribute's value, so `-type data -bogus_attr x` parsed as
    `type = "data -bogus_attr x"` and the file was rejected with a bogus
    "type not defined" instead of naming the attribute that is not in Table 3.
    """
    col = Collateral()
    param_lines: dict = {}
    for lineno, line in _logical_lines(text):
        m = re.match(r"accellera_cdc::(\w+)\s*(.*)$", line)
        if not m:
            continue
        cmd, rest = m.group(1), m.group(2)
        if cmd not in COMMANDS:
            col.unknown_commands.append((lineno, cmd))
            continue
        known = COMMANDS[cmd]
        tokens = _split_args(rest)

        # Clause 6.3 b): "If parameter is ignored and still referred to in
        # subsequent commands." Only *later* lines count, so this runs before
        # this line's own declarations are recorded.
        for pname, earlier in col.params.items():
            if earlier.ignore and _names(rest, pname):
                col.ignored_param_refs.append((lineno, cmd, pname,
                                               param_lines.get(pname, 0)))

        attrs, key = {}, None
        for tok in tokens:
            if _ATTRIBUTE.match(tok):
                if tok in known:
                    key = tok[1:]
                    attrs[key] = ""
                else:
                    key = None
                    col.unknown_attributes.append((lineno, cmd, tok))
                continue
            if key is not None:
                attrs[key] = (attrs[key] + " " + tok).strip()

        if cmd == "set_module":
            col.module = attrs.get("name", "")
        elif cmd == "set_param":
            p = Param(attrs.get("name", ""), attrs.get("type", ""),
                      attrs.get("value", ""),
                      ignore=("ignore" in attrs and _truthy(attrs["ignore"])))
            if p.name:
                col.params[p.name] = p
                param_lines[p.name] = lineno
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
            elif g.clocks:
                # Table 6: `name` is Optional and `clocks` is Mandatory. An
                # unnamed group was silently dropped, so its Clause 6.5 check
                # ("There shall be an error if one or more specified clock names
                # do not exist in the design") never ran.
                col.unnamed_clock_groups.append(g)
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


def _resolve(col: Collateral, name: str):
    """Find the port a reference names, tolerating a bit-slice (`DATA[7:4]`)."""
    if name in col.ports:
        return col.ports[name]
    base = Port(name=name).base_name
    for p in col.ports.values():
        if p.base_name == base:
            return p
    return None


def _check_enum(out: Conformance, port: str, p: Port, attr: str,
                allowed: set, rule: str) -> None:
    """Table 3 gives these attributes a defined set of values.

    An empty value is not reported: the standard defines the set, not an error
    condition for a missing value, and the Annex C fixtures write a bare
    `-ignore` and a bare `-cdc_static`.
    """
    if not p.has(attr):
        return
    value = p.attr(attr).strip().lower()
    if value and value not in allowed:
        out.findings.append(Finding(
            "error", rule,
            f"port {port}: -{attr} {p.attr(attr)!r} is not one of "
            f"{sorted(allowed)}"))


def check(col: Collateral, rtl_ports: set | None = None) -> Conformance:
    """Check the collateral against itself, and against the RTL if given.

    Clause 4: "All CDC/RDC-related declarations (such as modules, ports, and
    parameters) must be explicitly defined and referentially consistent." So a
    port naming an undeclared clock is an error rather than a warning. It does
    not say whether a crossing is safe, and neither does this.
    """
    out = Conformance(module=col.module, ports=len(col.ports),
                      clocks=len(col.clocks()))

    if not col.module:
        out.findings.append(Finding("error", "module name missing",
                                    "set_module -name is mandatory"))

    for name, p in col.ports.items():
        if not p.direction:
            out.findings.append(Finding("error", "direction missing",
                                        f"port {name}: -direction is mandatory"))
        elif p.direction not in DIRECTIONS:
            out.findings.append(Finding("error", "direction not defined",
                                        f"port {name}: {p.direction!r} is not one of "
                                        f"{sorted(DIRECTIONS)}"))
        if not p.type:
            # Clause 4.3.8: "While using the -constant attribute, only the name
            # and direction of the ports are mandatory attributes. Other
            # attributes like -type, -associated_to_clocks, etc. are not
            # required to be defined." Table 3 makes -type Mandatory for every
            # other port, so the exemption is exactly the -constant case.
            if not p.is_constant:
                out.findings.append(Finding("error", "type missing",
                                            f"port {name}: -type is mandatory"))
        elif p.type not in PORT_TYPES:
            out.findings.append(Finding("error", "type not defined",
                                        f"port {name}: {p.type!r} is not one of "
                                        f"{sorted(PORT_TYPES)}"))
        # Table 3, `polarity`: "This attribute is mandatory for async reset,
        # cdc_control, and rdc_control; otherwise, it is optional. For
        # cdc_control and rdc_control, 'low_high' is not allowed."
        if p.type == "async_reset" or p.type in CONTROL_TYPES:
            if not p.polarity:
                # Table 3 makes this mandatory for rdc_control — but the
                # standard's OWN Example 34 declares an rdc_control with
                # -blocking_polarity and no -polarity. That is a conflict inside
                # the standard, not something this checker can settle, so when
                # -blocking_polarity is present (which already states the value
                # that blocks the crossing) it is a warning that names the
                # conflict, not an error that rejects the standard's example.
                # Rejecting the standard's own example is the worse failure.
                if p.type in CONTROL_TYPES and p.has("blocking_polarity"):
                    out.findings.append(Finding(
                        "warning", "polarity missing",
                        f"port {name}: Table 3 makes -polarity mandatory for "
                        f"-type {p.type}, but the standard's own Example 34 "
                        f"omits it while declaring -blocking_polarity; treated "
                        f"as a warning so the example is not rejected"))
                else:
                    out.findings.append(Finding(
                        "error", "polarity missing",
                        f"port {name}: -polarity is mandatory for -type "
                        f"{p.type}"))
            elif p.polarity not in POLARITY_VALUES:
                out.findings.append(Finding(
                    "error", "polarity not defined",
                    f"port {name}: {p.polarity!r} is not one of "
                    f"['high', 'low', 'low_high']"))
            elif p.type in CONTROL_TYPES and p.polarity == "low_high":
                out.findings.append(Finding(
                    "error", "polarity not allowed",
                    f"port {name}: -polarity low_high is not allowed for "
                    f"-type {p.type}"))

        # ---- enumerated values (Table 3 / Table 2) ----------------------
        _check_enum(out, name, p, "ignore", IGNORE_VALUES,
                    "ignore value not defined")
        _check_enum(out, name, p, "logic", LOGIC_VALUES,
                    "logic value not defined")
        _check_enum(out, name, p, "sampling_edge", SAMPLING_EDGES,
                    "sampling_edge not defined")

        # ---- Clause 6.4 b): an attribute that does not apply to this type --
        # "There shall be an error if ... b) an attribute is specified for a
        # particular type of port that is not applicable to that type of port."
        # Only the restrictions Table 3 states outright are enforced here, so
        # that a conformant file is never rejected.
        # Table 3, `cdc_data_from_clock`: "Mandatory for output ports of type
        # cdc_control. Optional for input ports of type cdc_control. Prohibited
        # for other port types."
        if p.has("cdc_data_from_clock") and p.type != "cdc_control":
            out.findings.append(Finding(
                "error", "attribute not applicable",
                f"port {name}: -cdc_data_from_clock is prohibited for "
                f"-type {p.type or '(none)'}; Table 3 allows it only on "
                f"cdc_control"))
        # Table 3, `associated_inputs`: "applicable to outputs ... applicable to
        # inputs if considering a CDC control signal input."
        if (p.has("associated_inputs") and p.direction in ("input", "in")
                and p.type not in CONTROL_TYPES):
            out.findings.append(Finding(
                "error", "attribute not applicable",
                f"port {name}: -associated_inputs applies to output ports, and "
                f"to input ports only of type cdc_control/rdc_control"))
        # Table 3, `associated_outputs`: "applicable to inputs."
        if (p.has("associated_outputs") and p.direction in ("output", "out")
                and p.type not in CONTROL_TYPES):
            out.findings.append(Finding(
                "error", "attribute not applicable",
                f"port {name}: -associated_outputs applies to input ports, and "
                f"to output ports only of type cdc_control/rdc_control"))

        # ---- referential consistency (Clause 4) -------------------------
        for attr, refs in (("associated_from_clocks", p.associated_from_clocks),
                           ("associated_to_clocks", p.associated_to_clocks),
                           ("cdc_static", p.refs("cdc_static")),
                           ("rdc_data_to_clock", p.refs("rdc_data_to_clock"))):
            for ref in refs:
                target = _resolve(col, ref)
                if target is None:
                    out.findings.append(Finding(
                        "error", "undeclared clock",
                        f"port {name}: -{attr} names {ref!r}, which is not declared"))
                elif target.type not in CLOCK_LIKE:
                    out.findings.append(Finding(
                        "error", "not a clock",
                        f"port {name}: -{attr} names {ref!r}, declared as "
                        f"{target.type!r}"))
        for attr, refs in (("associated_from_reset", p.associated_from_reset),
                           ("associated_to_reset", p.associated_to_reset),
                           ("rdc_data_from_reset", p.refs("rdc_data_from_reset")),
                           ("rdc_data_to_reset", p.refs("rdc_data_to_reset"))):
            for ref in refs:
                if _resolve(col, ref) is None:
                    out.findings.append(Finding(
                        "error", "undeclared reset",
                        f"port {name}: -{attr} names {ref!r}, which is not declared"))
        # Table 3: `associated_inputs` and `associated_outputs` are lists of
        # ports; `cdc_control`/`rdc_control` are lists of associated ports of
        # the matching control type. None of these were ever resolved.
        for attr in ("associated_inputs", "associated_outputs"):
            for ref in p.refs(attr):
                if _resolve(col, ref) is None:
                    out.findings.append(Finding(
                        "error", "undeclared port",
                        f"port {name}: -{attr} names {ref!r}, which is not declared"))
        for attr, want in (("cdc_control", "cdc_control"),
                           ("rdc_control", "rdc_control")):
            for ref in p.refs(attr):
                target = _resolve(col, ref)
                if target is None:
                    out.findings.append(Finding(
                        "error", "undeclared port",
                        f"port {name}: -{attr} names {ref!r}, which is not declared"))
                elif target.type != want:
                    out.findings.append(Finding(
                        "error", "not a control port",
                        f"port {name}: -{attr} names {ref!r}, declared as "
                        f"{target.type!r} rather than {want!r}"))

    # ---- Table 3 pairing: a data port must name the control that controls it
    # "cdc_control: This attribute is mandatory for a data port if it is paired
    # with a port of type cdc_control"; "rdc_control: This attribute is required
    # for a data port that is paired with a control port of type rdc_control".
    # Annex A.3: "The port attributes support references between data ports and
    # the CDC control ports in both directions. For a data port (-type data),
    # the option -cdc_control specifies a unique CDC control port. If such a
    # relation exists, it is mandatory to describe it in this way." The reverse
    # list (`-associated_inputs`/`-associated_outputs`) is optional, so only the
    # data-port side is required here.
    for cname, cp in col.ports.items():
        if cp.type not in CONTROL_TYPES:
            continue
        attr = cp.type
        for target_name in cp.refs("associated_inputs") + cp.refs("associated_outputs"):
            target = _resolve(col, target_name)
            if target is None or target.type != "data":
                continue
            named = {Port(name=n).base_name for n in target.refs(attr)}
            if Port(name=cname).base_name not in named:
                out.findings.append(Finding(
                    "error", "control pairing missing",
                    f"port {target.name}: {cp.type} port {cname} names it in "
                    f"-associated_inputs/-associated_outputs, so it must carry "
                    f"-{attr} {cname}"))

    for name, g in col.clock_groups.items():
        for c in g.clocks:
            if _resolve(col, c) is None:
                out.findings.append(Finding("error", "undeclared clock",
                                            f"clock_group {name}: {c!r} not declared"))
    # Clause 6.5: "There shall be an error if one or more specified clock names
    # do not exist in the design." Table 6 makes `name` Optional, so an unnamed
    # group gets the same check.
    for i, g in enumerate(col.unnamed_clock_groups, 1):
        for c in g.clocks:
            if _resolve(col, c) is None:
                out.findings.append(Finding(
                    "error", "undeclared clock",
                    f"clock_group #{i} (unnamed): {c!r} not declared"))

    # ---- Clause 6.3 b) ------------------------------------------------
    # "There shall be an error if: ... b) If parameter is ignored and still
    # referred to in subsequent commands." Table 2: "Any parameter that is
    # ignored but still referred to in the model in following commands is a
    # failure."
    for lineno, cmd, pname, pline in col.ignored_param_refs:
        out.findings.append(Finding(
            "error", "ignored parameter referenced",
            f"line {lineno}: {pname!r} is referred to by accellera_cdc::{cmd} "
            f"but was declared -ignore at line {pline}"))

    # ---- Table 2, parameter domain -----------------------------------
    for name, p in col.params.items():
        if p.type and p.type.strip().lower() not in PARAM_TYPES:
            out.findings.append(Finding(
                "error", "parameter type not defined",
                f"parameter {name}: -type {p.type!r} is not one of "
                f"{sorted(PARAM_TYPES)} (Table 2)"))

    if rtl_ports is not None:
        declared = {p.base_name for p in col.ports.values()
                    if p.type not in ("virtual_clock", "virtual_reset")}
        for missing in sorted(declared - set(rtl_ports)):
            out.findings.append(Finding(
                "warning", "declared, not in RTL",
                f"{missing}: declared in the collateral but absent from the RTL"))
        for extra in sorted(set(rtl_ports) - declared):
            out.findings.append(Finding(
                "warning", "in RTL, not declared",
                f"{extra}: an RTL port with no CDC declaration"))

    for lineno, cmd, attr in col.unknown_attributes:
        out.findings.append(Finding(
            "warning", "unknown attribute",
            f"line {lineno}: {attr} on accellera_cdc::{cmd} is not an attribute "
            f"the standard defines"))
    for lineno, cmd in col.unknown_commands:
        out.findings.append(Finding("warning", "unknown command",
                                    f"line {lineno}: accellera_cdc::{cmd} is not in "
                                    f"the standard"))
    return out
