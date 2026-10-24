"""Spec-driven RTL generation.

A *spec* is a small, machine-readable description of what a block must do: its
parameters, its ports, its register map and any combinational behaviour. From it
WENGOLD emits SystemVerilog, and then *checks the emitted code against the spec*
by re-reading it — so generated RTL is an artifact that is verified, not an
artifact that is trusted because a generator produced it.

Nothing here is a general-purpose high-level synthesiser. It covers what a spec
usually pins down mechanically: interfaces, register maps, simple behaviour. What
it cannot express is refused rather than guessed at.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["SpecError", "Port", "Parameter", "Field", "Register", "Assign",
           "ModuleSpec", "load_spec"]

_DIRECTIONS = {"input", "output", "inout"}
_ACCESS = {"rw", "r", "ro", "w", "wo", "w1c"}


class SpecError(ValueError):
    """A spec that cannot be used. Says what is wrong and where."""


def _bits_to_range(bits) -> tuple[int, int]:
    """'3:1' | '0' | 5 -> (hi, lo), inclusive."""
    if isinstance(bits, int):
        return bits, bits
    text = str(bits).strip()
    if ":" in text:
        hi, _, lo = text.partition(":")
        try:
            hi, lo = int(hi), int(lo)
        except ValueError:
            raise SpecError(f"bit range {bits!r} is not numeric") from None
    else:
        try:
            hi = lo = int(text)
        except ValueError:
            raise SpecError(f"bit selector {bits!r} is not numeric") from None
    if hi < lo:
        raise SpecError(f"bit range {bits!r} is reversed (hi < lo)")
    return hi, lo


@dataclass
class Port:
    name: str
    direction: str = "input"
    width: int = 1

    def __post_init__(self) -> None:
        if self.direction not in _DIRECTIONS:
            raise SpecError(f"port {self.name!r}: direction {self.direction!r} "
                            f"is not one of {sorted(_DIRECTIONS)}")
        if self.width < 1:
            raise SpecError(f"port {self.name!r}: width must be >= 1")

    @property
    def decl(self) -> str:
        w = "" if self.width == 1 else f"[{self.width - 1}:0] "
        return f"{self.direction:<6} logic {w}{self.name}"


@dataclass
class Parameter:
    name: str
    value: int
    desc: str = ""


@dataclass
class Field:
    name: str
    hi: int
    lo: int
    access: str = "rw"
    reset: int = 0
    desc: str = ""

    def __post_init__(self) -> None:
        if self.access not in _ACCESS:
            raise SpecError(f"field {self.name!r}: access {self.access!r} is not "
                            f"one of {sorted(_ACCESS)}")
        if self.hi < self.lo:
            raise SpecError(f"field {self.name!r}: bit range is reversed")

    @property
    def width(self) -> int:
        return self.hi - self.lo + 1

    @property
    def bits(self) -> str:
        return str(self.hi) if self.hi == self.lo else f"{self.hi}:{self.lo}"

    @property
    def sw_writable(self) -> bool:
        return self.access in ("rw", "w", "wo", "w1c")

    @property
    def sw_readable(self) -> bool:
        return self.access not in ("w", "wo")


@dataclass
class Register:
    name: str
    addr: int
    width: int = 32
    fields: list[Field] = field(default_factory=list)
    desc: str = ""

    @property
    def signal(self) -> str:
        return f"{self.name.lower()}_q"

    def validate(self) -> None:
        if self.addr < 0 or self.addr % 4:
            raise SpecError(f"register {self.name!r}: address 0x{self.addr:x} "
                            f"must be a non-negative multiple of 4")
        if not self.fields:
            raise SpecError(f"register {self.name!r} has no fields")
        used: dict[int, str] = {}
        for f in self.fields:
            if f.hi >= self.width:
                raise SpecError(f"register {self.name!r}: field {f.name!r} reaches "
                                f"bit {f.hi} but the register is {self.width} bits")
            for b in range(f.lo, f.hi + 1):
                if b in used:
                    raise SpecError(f"register {self.name!r}: fields {used[b]!r} and "
                                    f"{f.name!r} both claim bit {b}")
                used[b] = f.name

    @property
    def reset_value(self) -> int:
        value = 0
        for f in self.fields:
            value |= (f.reset & ((1 << f.width) - 1)) << f.lo
        return value


@dataclass
class Assign:
    """A combinational assignment: `target = expression`."""
    target: str
    expr: str

    def validate(self) -> None:
        if ";" in self.expr:
            raise SpecError(f"assign {self.target!r}: the expression must not "
                            f"contain ';'")
        if "=" in self.expr:
            raise SpecError(f"assign {self.target!r}: use '==' for comparison; a "
                            f"bare '=' is not allowed in an expression")


@dataclass
class ModuleSpec:
    name: str
    parameters: list[Parameter] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)
    registers: list[Register] = field(default_factory=list)
    assigns: list[Assign] = field(default_factory=list)
    clock: str = "clk_i"
    reset: str = "rst_ni"
    desc: str = ""
    source: str = ""

    # ---- derived interface -------------------------------------------------
    @property
    def has_registers(self) -> bool:
        return bool(self.registers)

    @property
    def bus_ports(self) -> list[Port]:
        """The register bus, added automatically when the spec has registers."""
        if not self.has_registers:
            return []
        w = max((r.width for r in self.registers), default=32)
        return [
            Port("reg_wr_i", "input", 1),
            Port("reg_rd_i", "input", 1),
            Port("reg_addr_i", "input", w),
            Port("reg_wdata_i", "input", w),
            Port("reg_rdata_o", "output", w),
        ]

    @property
    def all_ports(self) -> list[Port]:
        return list(self.ports) + self.bus_ports

    def field_signal(self, reg: Register, fld: Field) -> str:
        return f"{reg.name.lower()}_{fld.name.lower()}_q"

    def validate(self) -> None:
        if not re.fullmatch(r"[A-Za-z_]\w*", self.name or ""):
            raise SpecError(f"module name {self.name!r} is not a valid identifier")
        names = [p.name for p in self.all_ports]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise SpecError(f"duplicate port name(s): {sorted(dupes)}")
        if self.clock not in names:
            raise SpecError(f"clock {self.clock!r} is not a port of {self.name}")
        if self.reset not in names:
            raise SpecError(f"reset {self.reset!r} is not a port of {self.name}")
        addrs = [r.addr for r in self.registers]
        dup = {a for a in addrs if addrs.count(a) > 1}
        if dup:
            raise SpecError(f"two registers share address(es) "
                            f"{[hex(a) for a in sorted(dup)]}")
        for r in self.registers:
            r.validate()
        for a in self.assigns:
            a.validate()

    @property
    def address_map(self) -> dict[str, int]:
        return {r.name: r.addr for r in self.registers}


# ---- loading ---------------------------------------------------------------
_TOP_KEYS = {"module", "name", "desc", "clock", "reset", "parameters",
             "ports", "registers", "assigns"}
_KEY_SETS = {
    "ports": {"name", "dir", "direction", "width"},
    "parameters": {"name", "value", "desc"},
    "registers": {"name", "addr", "width", "fields", "desc"},
    "fields": {"name", "bits", "access", "reset", "desc"},
    "assigns": {"target", "expr"},
}


def _check_keys(obj, where: str, allowed: set[str]) -> None:
    """Refuse keys the spec format does not have.

    Silently ignoring `fsm:` or `pipeline:` would let a spec author believe they
    asked for something the generator cannot express, and hand back a module that
    quietly omits it. What cannot be expressed is refused, with the reason.
    """
    unknown = sorted(set(obj) - allowed)
    if unknown:
        raise SpecError(
            f"{where}: unsupported key(s) {unknown} — the spec format expresses "
            f"{', '.join(sorted(allowed))} and nothing else. A design element the "
            f"generator cannot emit (a state machine, a pipeline, an interface) "
            f"is refused rather than silently dropped.")


def _load_raw(path: Path):
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise SpecError("PyYAML is needed for a .yaml spec; install it or "
                            "write the spec as JSON") from None
        return yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SpecError(f"{path.name} is not valid JSON: {exc}") from None


def load_spec(path: str | Path) -> ModuleSpec:
    """Read a spec from YAML or JSON and validate it."""
    p = Path(path)
    if not p.is_file():
        raise SpecError(f"no such spec file: {p}")
    raw = _load_raw(p)
    if not isinstance(raw, dict):
        raise SpecError(f"{p.name}: the spec must be a mapping at the top level")
    _check_keys(raw, f"{p.name}", _TOP_KEYS)

    ports = []
    for item in raw.get("ports", []):
        _check_keys(item, f"{p.name}: ports", _KEY_SETS["ports"])
        ports.append(Port(name=item["name"],
                          direction=item.get("dir", item.get("direction", "input")),
                          width=int(item.get("width", 1))))

    params = []
    for item in raw.get("parameters", []):
        _check_keys(item, f"{p.name}: parameters", _KEY_SETS["parameters"])
        params.append(Parameter(name=item["name"], value=int(item["value"]),
                                desc=item.get("desc", "")))

    regs = []
    for r in raw.get("registers", []):
        _check_keys(r, f"{p.name}: registers", _KEY_SETS["registers"])
        fields = []
        for f in r.get("fields", []):
            _check_keys(f, f"{p.name}: register {r.get('name')} fields",
                        _KEY_SETS["fields"])
            hi, lo = _bits_to_range(f["bits"])
            fields.append(Field(name=f["name"], hi=hi, lo=lo,
                                access=f.get("access", "rw"),
                                reset=int(f.get("reset", 0)),
                                desc=f.get("desc", "")))
        regs.append(Register(name=r["name"], addr=int(str(r["addr"]), 0),
                             width=int(r.get("width", 32)), fields=fields,
                             desc=r.get("desc", "")))

    assigns = []
    for a in raw.get("assigns", []):
        if isinstance(a, dict):
            _check_keys(a, f"{p.name}: assigns", _KEY_SETS["assigns"])
            assigns.append(Assign(target=a["target"], expr=a["expr"]))
        else:                                   # "state_o = en ? 1 : 0"
            target, _, expr = str(a).partition("=")
            assigns.append(Assign(target=target.strip(), expr=expr.strip()))

    spec = ModuleSpec(
        name=raw.get("module") or raw.get("name") or p.stem,
        parameters=params, ports=ports, registers=regs, assigns=assigns,
        clock=raw.get("clock", "clk_i"), reset=raw.get("reset", "rst_ni"),
        desc=raw.get("desc", ""), source=str(p),
    )
    spec.validate()
    return spec
