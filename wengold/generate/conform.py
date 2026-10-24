"""Check generated SystemVerilog against the spec it came from.

This is the part that makes generation trustworthy. The generator and the checker
read the *same spec* but different artifacts: the generator writes RTL, the
checker re-reads the RTL **as source** and compares it with the spec. A bug in
the bit arithmetic, an address that drifted, a reset value computed wrongly, or
an output left undriven shows up here as a failed check rather than as code that
merely looks plausible.

Each check records the method it used, so the strength of the evidence is visible
rather than implied:

* ``parse tree``  — read from a real SystemVerilog parse of the emitted file
  (module name, port names and directions, the fact a parameter is declared).
* ``source scan`` — a scan of the emitted text (numeric widths, bit slices,
  address and reset literals, which signals are driven).

Neither method consults the spec to decide what the file contains; the spec is
only the expectation it is compared against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pyslang import syntax as S

from .spec import ModuleSpec

__all__ = ["Check", "Report", "check"]


@dataclass
class Check:
    item: str
    ok: bool
    detail: str
    method: str = "source scan"

    def __str__(self) -> str:
        mark = "ok  " if self.ok else "FAIL"
        return f"  {mark} {self.item:<32} {self.detail}"


@dataclass
class Report:
    module: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def summary(self) -> str:
        n, bad = len(self.checks), len(self.failures)
        head = f"{self.module}: {n - bad}/{n} checks passed"
        if bad:
            head += f" — {bad} FAILED"
        return "\n".join([head] + [str(c) for c in self.checks])


def _walk(node):
    yield node
    try:
        for child in node:
            if hasattr(child, "kind"):
                yield from _walk(child)
    except TypeError:
        pass


def _parse(source: str):
    return S.SyntaxTree.fromText(source, name="<rtl>")


def _lit_value(text: str) -> int | None:
    m = re.search(r"\d+'([hdb]?)([0-9a-fA-F_]+)", text)
    if not m:
        return None
    base = {"h": 16, "d": 10, "b": 2, "": 10}[m.group(1)]
    try:
        return int(m.group(2).replace("_", ""), base)
    except ValueError:
        return None


def _module_names(tree) -> list[str]:
    return [getattr(getattr(n.header, "name", None), "valueText", None)
            for n in _walk(tree.root)
            if str(n.kind).endswith("ModuleDeclaration")]


def _port_directions(tree) -> dict[str, str]:
    """name -> direction, from the parse tree's port declarations."""
    out: dict[str, str] = {}
    for n in _walk(tree.root):
        kind = str(n.kind)
        if not (kind.endswith("ImplicitAnsiPort") or kind.endswith("AnsiPortDeclaration")):
            continue
        name = getattr(getattr(n, "declarator", None), "name", None)
        direction = getattr(getattr(getattr(n, "header", None), "direction", None),
                            "valueText", None)
        if name is not None and direction is not None:
            out[name.valueText] = direction
    return out


def _port_widths(source: str) -> dict[str, int]:
    out: dict[str, int] = {}
    pat = re.compile(r"^\s*(?:input|output|inout)\s+logic\s*"
                     r"(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?(\w+)", re.M)
    for m in pat.finditer(source):
        out[m.group(3)] = (int(m.group(1)) - int(m.group(2)) + 1) if m.group(1) else 1
    return out


def _param_values(source: str) -> dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in re.finditer(
        r"\bparameter\s+int\s+unsigned\s+(\w+)\s*=\s*(\d+)", source)}


def _field_slices(source: str) -> dict[str, str]:
    """field signal -> the register slice it is taken from.

    Accepts both spellings a field view may take: `assign sig = reg[hi:lo];`
    and the initialised-net form `wire sig = reg[hi:lo];`.
    """
    out: dict[str, str] = {}
    pats = [re.compile(r"\bassign\s+(\w+)\s*=\s*(\w+)\[([^\]]+)\]\s*;"),
            re.compile(r"\bwire\s+(?:\[\s*\d+\s*:\s*\d+\s*\]\s*)?(\w+)\s*=\s*"
                       r"(\w+)\[([^\]]+)\]\s*;")]
    for pat in pats:
        for m in pat.finditer(source):
            out.setdefault(m.group(1), f"{m.group(2)}[{m.group(3).replace(' ', '')}]")
    return out


def _written_slices(source: str, signal: str) -> list[str]:
    return [s.replace(" ", "") for s in re.findall(
        rf"\b{re.escape(signal)}\[([^\]]+)\]\s*<=", source)]


def _driven_signals(source: str) -> set[str]:
    driven = set(re.findall(r"\bassign\s+(\w+)", source))
    driven |= set(re.findall(r"^\s*(\w+)\s*<=", source, re.M))
    return driven


def check(source: str, spec: ModuleSpec) -> Report:
    """Compare emitted RTL text against the spec. Returns a per-item report."""
    rep = Report(module=spec.name)
    tree = _parse(source)
    if tree.diagnostics:
        rep.checks.append(Check("parse", False,
                                f"{len(tree.diagnostics)} parse diagnostic(s)",
                                "parse tree"))

    names = _module_names(tree)
    rep.checks.append(Check("module name", spec.name in names,
                            f"expected {spec.name!r}, found {names or 'none'}",
                            "parse tree"))

    params = _param_values(source)
    declared_params = {m.group(1) for m in re.finditer(
        r"\bparameter\s+int\s+unsigned\s+(\w+)", source)}
    for p in spec.parameters:
        if p.name not in declared_params:
            rep.checks.append(Check(f"parameter {p.name}", False,
                                    "not declared", "parse tree"))
        else:
            got = params.get(p.name)
            rep.checks.append(Check(f"parameter {p.name}", got == p.value,
                                    f"expected {p.value}, found {got}",
                                    "parse tree"))

    directions = _port_directions(tree)
    widths = _port_widths(source)
    for p in spec.all_ports:
        direction = directions.get(p.name)
        if direction is None:
            rep.checks.append(Check(f"port {p.name}", False, "not declared",
                                    "parse tree"))
            continue
        width = widths.get(p.name)
        ok = direction == p.direction and width == p.width
        rep.checks.append(Check(
            f"port {p.name}", ok,
            f"expected {p.direction} [{p.width}], found {direction} [{width}]",
            "parse tree"))

    slices = _field_slices(source)
    for r in spec.registers:
        m = re.search(rf"\b{re.escape(r.name)}_ADDR\s*=\s*([^;]+);", source)
        addr = _lit_value(m.group(1)) if m else None
        rep.checks.append(Check(f"{r.name} address", addr == r.addr,
                                f"expected 0x{r.addr:x}, found "
                                f"{'none' if addr is None else hex(addr)}"))

        m = re.search(rf"\b{re.escape(r.signal)}\s*<=\s*([^;]+);", source)
        reset = _lit_value(m.group(1)) if m else None
        rep.checks.append(Check(f"{r.name} reset", reset == r.reset_value,
                                f"expected 0x{r.reset_value:x}, found "
                                f"{'none' if reset is None else hex(reset)}"))

        for f in r.fields:
            sig = spec.field_signal(r, f)
            want = f"{r.signal}[{f.bits}]"
            got = slices.get(sig)
            rep.checks.append(Check(f"{r.name}.{f.name} slice", got == want,
                                    f"expected {want}, found {got or 'not declared'}"))
            if f.access in ("ro", "r"):
                written = _written_slices(source, r.signal)
                bad = f.bits in written
                rep.checks.append(Check(f"{r.name}.{f.name} read-only", not bad,
                                        "no write path" if not bad
                                        else f"written at [{f.bits}]"))

    driven = _driven_signals(source)
    for p in spec.all_ports:
        if p.direction == "output":
            rep.checks.append(Check(f"output {p.name} driven", p.name in driven,
                                    "driven" if p.name in driven else "never driven"))

    return rep
