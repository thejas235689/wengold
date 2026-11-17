"""Waveforms: from a formal counterexample, or from a simulator's VCD.

A waveform is only worth showing if the values in it are real. Two sources here,
and no invented data:

* **A formal counterexample.** The engines already produce one — a concrete trace
  of input and state values per cycle, computed while searching for a violation
  of a property. That trace *is* a waveform, and it is the cycle in which the
  property failed.
* **A VCD file.** A simulator's dump, parsed here. Point the IDE at one with
  --vcd and it is drawn the same way.

Both normalise to the same shape. VCD time units are retained so telemetry
export can map simulation ticks without guessing the simulator timescale.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

__all__ = ["from_trace", "parse_vcd", "from_vcd", "from_formal"]

_TIME_UNITS_NS = {
    "s": Decimal("1000000000"),
    "ms": Decimal("1000000"),
    "us": Decimal("1000"),
    "ns": Decimal("1"),
    "ps": Decimal("0.001"),
    "fs": Decimal("0.000001"),
}
_TIMESCALE = re.compile(
    r"\$timescale\s+(\d+)\s*(s|ms|us|ns|ps|fs)\s+\$end",
    re.IGNORECASE,
)


def _timescale_info(text: str) -> dict:
    match = _TIMESCALE.search(text)
    if not match:
        return {"timescale": None, "time_unit_ns": None}
    magnitude, unit = match.groups()
    unit = unit.lower()
    return {
        "timescale": f"{magnitude}{unit}",
        "time_unit_ns": str(Decimal(magnitude) * _TIME_UNITS_NS[unit]),
    }


def _widths_of(rtl_text: str) -> dict[str, int]:
    from .formal.rtl_model import UnsupportedConstruct, parse_module, to_model
    try:
        return dict(to_model(parse_module(rtl_text)).widths)
    except UnsupportedConstruct:
        return {}


def from_trace(trace: list, widths: dict[str, int] | None = None,
               clock: str | None = None, source: str = "formal counterexample",
               fail_at: int | None = None) -> dict:
    """Normalise an engine trace into the waveform shape.

    Formal trace positions are logical cycles, not physical time. Their unit is
    explicitly labelled cycle so a downstream exporter cannot mistake them
    for measured nanoseconds.
    """
    widths = widths or {}
    cycles: list[dict] = []
    for step in trace:
        if isinstance(step, dict) and "state" in step:
            cycles.append(dict(step["state"]))
        elif isinstance(step, dict):
            cycles.append(dict(step))
        else:
            cycles.append({})
    if not cycles:
        return {"source": source, "clock": clock, "fail_at": None, "cycles": 0,
                "signals": [], "timescale": "1cycle", "time_unit_ns": "1",
                "time_unit_label": "cycle"}

    names: list[str] = []
    for c in cycles:
        for k in c:
            if k not in names:
                names.append(k)
    names.sort(key=lambda n: (n != clock, n))
    signals = [{"name": n,
                "width": int(widths.get(n, 1)),
                "values": [c.get(n) for c in cycles]}
               for n in names]
    return {"source": source, "clock": clock,
            "fail_at": fail_at if fail_at is not None else len(cycles) - 1,
            "cycles": len(cycles), "signals": signals,
            "timescale": "1cycle", "time_unit_ns": "1",
            "time_unit_label": "cycle"}


# ---- VCD -------------------------------------------------------------------
_VAR = re.compile(r"\$var\s+(\w+)\s+(\d+)\s+(\S+)\s+([^$]*?)\s*\$end")
_SCALAR = re.compile(r"^([01xzXZ])(\S+)$")
_SCOPE = re.compile(r"\$scope\s+\w+\s+(\S+)\s*\$end")
_UPSCOPE = re.compile(r"\$upscope\s*\$end")


def parse_vcd(text: str, limit: int = 4000) -> dict:
    """Parse a VCD dump into the waveform shape."""
    timing = _timescale_info(text)
    ids: dict[str, tuple[str, int]] = {}
    scope: list[str] = []
    for line in text.splitlines():
        m = _VAR.search(line)
        if m:
            _kind, width, ident, name = m.groups()
            leaf = name.strip().split()[0]
            full = ".".join(scope + [leaf]) if scope else leaf
            ids[ident] = (full, int(width))
            continue
        s = _SCOPE.search(line)
        if s:
            scope.append(s.group(1))
            continue
        if _UPSCOPE.search(line):
            if scope:
                scope.pop()
    body = text.split("$enddefinitions", 1)
    if len(body) < 2:
        return {"source": "vcd", "clock": None, "fail_at": None,
                "cycles": 0, "signals": [], **timing}

    current: dict[str, int | None] = {}
    history: list[tuple[int, dict[str, int | None]]] = []
    pending: int | None = None
    for line in body[1].splitlines():
        line = line.strip()
        if not line or line.startswith("$"):
            continue
        if line.startswith("#"):
            try:
                if pending is not None:
                    history.append((pending, dict(current)))
                pending = int(line[1:])
            except ValueError:
                pass
            continue
        if line[0] in "bB":
            parts = line[1:].split()
            if len(parts) == 2:
                bits, ident = parts
                try:
                    current[ident] = (None if any(c in "xXzZ" for c in bits)
                                      else int(bits, 2))
                except ValueError:
                    pass
            continue
        m = _SCALAR.match(line)
        if m:
            bit, ident = m.groups()
            current[ident] = 1 if bit == "1" else 0 if bit == "0" else None
    if pending is not None:
        history.append((pending, dict(current)))
    if not history:
        return {"source": "vcd", "clock": None, "fail_at": None,
                "cycles": 0, "signals": [], **timing}
    history = history[:limit]

    names = [ids[i][0] for i in ids]
    clock = next((n for n in names if re.search(r"(?i)clk|clock", n)), None)
    if clock is None:
        clock = next((n for n in names
                      if re.search(r"(?i)clk|clock", n.split(".")[-1])), None)
    signals = []
    for ident, (name, width) in ids.items():
        values = [snapshot.get(ident) for _t, snapshot in history]
        signals.append({"name": name, "width": width, "values": values})
    signals.sort(key=lambda s: (s["name"] != clock, s["name"]))
    return {"source": "vcd", "clock": clock, "fail_at": None,
            "cycles": len(history), "signals": signals,
            "times": [t for t, _ in history], **timing}


def from_vcd(path: str | Path) -> dict:
    return parse_vcd(Path(path).read_text(errors="replace"))


# ---- from a formal run -----------------------------------------------------
def from_formal(rtl_text: str, property_expr: str, reset: str | None = None,
                clock: str | None = None, engine: str = "explicit",
                depth: int = 12) -> dict | None:
    """Run one property; if it fails, return the counterexample as a waveform.

    Returns None when the property does not fail — there is no counterexample to
    draw, and a waveform of nothing would be a lie.
    """
    from .formal import Property, prove
    from .formal.rtl_model import UnsupportedConstruct

    widths = _widths_of(rtl_text)
    try:
        out = prove(rtl_text, [Property.safety("wave", property_expr, reset=reset,
                                               clock=clock)],
                    engine=engine, depth=depth, budget=1)
    except UnsupportedConstruct:
        return None
    for r in out["results"]:
        if r.status == "fail" and r.trace:
            wave = from_trace(r.trace, widths, clock,
                              source=f"counterexample: {property_expr} "
                                     f"({r.engine} engine)")
            return wave
    return None
