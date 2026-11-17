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
_VCD_COMMAND = re.compile(r"\$(\w+)\b(.*?)\$end\b", re.S)
_TIMESCALE = re.compile(r"(1|10|100)\s*(s|ms|us|ns|ps|fs)")
_DIGITAL = {"event", "integer", "parameter", "reg", "supply0", "supply1",
            "time", "tri", "triand", "trior", "trireg", "tri0", "tri1",
            "wand", "wire", "wor", "logic", "bit"}
_MAX_DIGITAL_WIDTH = 4096


def parse_vcd(text: str, limit: int = 4000, *, signal_limit: int | None = None) -> dict:
    """Sample digital updates at real VCD timestamps, retaining four-state bits.

    The legacy integer values remain None for X/Z so existing consumers still
    work. The parallel logic_values array preserves individual X and Z bits.
    The parser stops sampling at the bound instead of copying the full history.
    """
    header, marker, body = text.partition("$enddefinitions")
    declarations = []
    scope: list[str] = []
    timescale = None
    unsupported = 0
    for command, args in _VCD_COMMAND.findall(header):
        parts = args.split()
        if command == "timescale":
            scale = _TIMESCALE.fullmatch(args.strip())
            if scale:
                timescale = "".join(scale.groups())
        elif command == "scope" and len(parts) >= 2:
            scope.append(parts[1])
        elif command == "upscope" and scope:
            scope.pop()
        elif command == "var" and len(parts) >= 4:
            kind, width, ident, leaf = parts[:4]
            if (kind not in _DIGITAL or not width.isascii() or not width.isdecimal()
                    or len(width) > 6 or not 0 < int(width) <= _MAX_DIGITAL_WIDTH):
                unsupported += 1
                continue
            # Distinguish separately declared bits with a shared reference name.
            if len(parts) > 4 and parts[4].startswith("[") and ":" not in parts[4]:
                leaf += parts[4]
            declarations.append((ident, ".".join([*scope, leaf]), int(width)))

    clock = next((name for _, name, _ in declarations
                  if re.search(r"clk|clock", name.rsplit(".", 1)[-1], flags=re.I)), None)
    declarations.sort(key=lambda item: (item[1] != clock, item[1]))
    total_signals = len(declarations)
    if signal_limit is not None:
        declarations = declarations[:signal_limit]
    if not marker:
        declarations = []

    widths = {ident: width for ident, _, width in declarations}
    current: dict[str, tuple[int | None, str]] = {}
    tracks = {ident: ([], []) for ident in widths}
    times: list[int] = []
    pending = None
    truncated = False
    last_sample_cost = 0
    retained_logic = 0

    def snapshot():
        # Prevent compact VCD vector strings from inflating into unbounded memory.
        nonlocal retained_logic
        if len(times) >= limit or retained_logic + last_sample_cost > 16_000_000:
            return False
        times.append(pending)
        retained_logic += last_sample_cost
        for ident, (values, logic_values) in tracks.items():
            value, logic = current.get(ident, (None, "x"))
            values.append(value)
            logic_values.append(logic)
        return True

    def set_value(ident, bits):
        nonlocal pending, last_sample_cost
        if ident not in widths or not re.fullmatch(r"[01xz]+", bits, flags=re.I):
            return
        width = widths[ident]
        bits = bits.lower()
        pad = bits[0] if bits[0] in "xz" else "0"
        bits = bits[-width:].rjust(width, pad)
        value = None if "x" in bits or "z" in bits else int(bits, 2)
        last_sample_cost += len(bits) - len(current.get(ident, (None, ""))[1])
        current[ident] = value, bits
        if pending is None:
            pending = 0

    tokens = iter(match.group() for match in re.finditer(r"\S+", body))
    dump_blocks = {"$dumpvars", "$dumpall", "$dumpon", "$dumpoff"}
    for token in tokens:
        if token.startswith("#") and token[1:].isascii() and token[1:].isdecimal():
            timestamp = int(token[1:])
            if pending is not None and timestamp < pending:
                raise ValueError("VCD timestamps must not move backwards")
            if pending is not None and timestamp != pending and not snapshot():
                truncated = True
                break
            pending = timestamp
        elif token.startswith("$"):
            if token != "$end" and token not in dump_blocks:
                for part in tokens:
                    if part == "$end":
                        break
        elif token[0] in "bBrRsS":
            # Real/string samples are not digital but still consume their ID.
            ident = next(tokens, "")
            if token[0] in "bB":
                set_value(ident, token[1:])
        elif token[0] in "01xzXZ":
            set_value(token[1:], token[0])
    if pending is not None and not truncated:
        truncated = not snapshot()

    signals = [{"name": name, "width": width,
                "values": tracks[ident][0], "logic_values": tracks[ident][1]}
               for ident, name, width in declarations]
    return {"source": "vcd", "clock": clock, "fail_at": None,
            "cycles": len(times), "signals": signals, "times": times,
            "timescale": timescale, "samples_truncated": truncated,
            "signals_omitted": total_signals - len(signals),
            "unsupported_signals": unsupported}


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
