"""Waveforms: from a formal counterexample, or from a simulator's VCD.

A waveform is only worth showing if the values in it are real. Two sources here,
and no invented data:

* **A formal counterexample.** The engines already produce one — a concrete trace
  of input and state values per cycle, computed while searching for a violation
  of a property. That trace *is* a waveform, and it is the one that matters:
  it is the cycle in which the property failed.
* **A VCD file.** A simulator's dump, parsed here. Point the IDE at one with
  `--vcd` and it is drawn the same way.

Both normalise to the same shape, so the renderer has one input:

    {"source": str, "clock": str | None, "fail_at": int | None,
     "cycles": int,
     "signals": [{"name": str, "width": int, "values": [...]}, ...]}

`values[i]` is the value of that signal at cycle `i`; `None` means unknown.
"""
from __future__ import annotations

import re
from pathlib import Path

__all__ = ["from_trace", "parse_vcd", "from_vcd", "from_formal"]


def _widths_of(rtl_text: str) -> dict[str, int]:
    from .formal.rtl_model import UnsupportedConstruct, parse_module, to_model
    try:
        return dict(to_model(parse_module(rtl_text)).widths)
    except UnsupportedConstruct:
        return {}


def from_trace(trace: list, widths: dict[str, int] | None = None,
               clock: str | None = None, source: str = "formal counterexample",
               fail_at: int | None = None) -> dict:
    """Normalise an engine trace into a waveform.

    The engines emit the initial state, then one `{"inputs":…, "state":…}` per
    cycle. The state already carries the inputs merged in, so the state alone
    gives every signal at every cycle.
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
                "signals": []}

    names: list[str] = []
    for c in cycles:
        for k in c:
            if k not in names:
                names.append(k)
    # clock first, then inputs and state alphabetically — a stable, readable order
    names.sort(key=lambda n: (n != clock, n))
    signals = [{"name": n,
                "width": int(widths.get(n, 1)),
                "values": [c.get(n) for c in cycles]}
               for n in names]
    return {"source": source, "clock": clock,
            "fail_at": fail_at if fail_at is not None else len(cycles) - 1,
            "cycles": len(cycles), "signals": signals}


# ---- VCD -------------------------------------------------------------------
_VAR = re.compile(r"\$var\s+(\w+)\s+(\d+)\s+(\S+)\s+([^$]*?)\s*\$end")
_SCALAR = re.compile(r"^([01xzXZ])(\S+)$")
_SCOPE = re.compile(r"\$scope\s+\w+\s+(\S+)\s*\$end")
_UPSCOPE = re.compile(r"\$upscope\s*\$end")


def parse_vcd(text: str, limit: int = 4000) -> dict:
    """Parse a VCD dump into the waveform shape."""
    # Track the scope stack. A dump of `tb` and its children declares the same
    # net twice (`tb.q` and `tb.u.q`); keying on the leaf name alone reported two
    # signals both called `q`, which is indistinguishable in the waveform.
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
        return {"source": "vcd", "clock": None, "fail_at": None, "cycles": 0,
                "signals": []}

    # A VCD lists the value changes *after* their `#time` marker, so a snapshot
    # taken when the marker is read is the previous cycle's. Record the values
    # when the NEXT marker arrives instead.
    current: dict[str, int] = {}
    history: list[tuple[int, dict[str, int]]] = []
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
                    current[ident] = int(bits.replace("x", "0").replace("z", "0"), 2)
                except ValueError:
                    pass
            continue
        m = _SCALAR.match(line)
        if m:
            bit, ident = m.groups()
            current[ident] = 1 if bit == "1" else 0
    if pending is not None:
        history.append((pending, dict(current)))
    if not history:
        return {"source": "vcd", "clock": None, "fail_at": None, "cycles": 0,
                "signals": []}
    history = history[:limit]

    def value_at(ident: str, t: int) -> int | None:
        last = None
        for tt, snap in history:
            if tt > t:
                break
            if ident in snap:
                last = snap[ident]
        return last

    names = [ids[i][0] for i in ids]
    clock = next((n for n in names if re.search(r"(?i)clk|clock", n)), None)
    if clock is None:
        clock = next((n for n in names if re.search(r"(?i)clk|clock", n.split(".")[-1])),
                     None)
    signals = []
    for ident, (name, width) in ids.items():
        values = [value_at(ident, t) for t, _ in history]
        signals.append({"name": name, "width": width, "values": values})
    signals.sort(key=lambda s: (s["name"] != clock, s["name"]))
    return {"source": "vcd", "clock": clock, "fail_at": None,
            "cycles": len(history), "signals": signals,
            "times": [t for t, _ in history]}


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
