"""Compare observed four-state traces on a shared, explicitly aligned time axis."""
from __future__ import annotations

from bisect import bisect_right
import re

from .wave_inspect import logic_at

UNIT_FS = dict(zip(("fs", "ps", "ns", "us", "ms", "s"), (1000 ** n for n in range(6))))


def fs_per_tick(scale):
    match = re.fullmatch(r"(1|10|100)(s|ms|us|ns|ps|fs)", scale or "")
    return int(match[1]) * UNIT_FS[match[2]] if match else None


def aligned_grid(left, right, anchor_a=None, anchor_b=None):
    if not left["times"] or not right["times"]:
        raise ValueError("Both traces need observed timestamps")
    a, b = left["times"], right["times"]
    factors = [fs_per_tick(trace.get("timescale")) for trace in (left, right)]
    if factors == [None, None]:
        factors, unit = [1, 1], "ticks (unscaled)"
    elif None in factors:
        raise ValueError("Cannot align physical time when only one trace has a timescale")
    else:
        unit = "fs"
    aa, ab = a[0] if anchor_a is None else anchor_a, b[0] if anchor_b is None else anchor_b
    if aa not in a or ab not in b:
        raise ValueError("Alignment anchors must be observed timestamps in each trace")
    at = [(t - aa) * factors[0] for t in a]
    bt = [(t - ab) * factors[1] for t in b]
    start, end = max(at[0], bt[0]), min(at[-1], bt[-1])
    if start > end:
        raise ValueError("Aligned traces have no overlap")
    times = sorted(t for t in set(at + bt) if start <= t <= end)
    return {"times": times, "unit": unit,
            "a": [bisect_right(at, t) - 1 for t in times],
            "b": [bisect_right(bt, t) - 1 for t in times]}


def compare(left, right, anchor_a=None, anchor_b=None, query=""):
    grid = aligned_grid(left, right, anchor_a, anchor_b)
    a = {sig["name"]: sig for sig in left["signals"]}
    b = {sig["name"]: sig for sig in right["signals"]}
    rows = []
    for name in sorted(set(a) | set(b)):
        if query.casefold() not in name.casefold():
            continue
        row = {"name": name, "first": None}
        if name not in a or name not in b:
            row["status"] = "Baseline only" if name in a else "Candidate only"
        elif a[name]["width"] != b[name]["width"]:
            row["status"] = "Width differs"
        else:
            first = next((n for n, (i, j) in enumerate(zip(grid["a"], grid["b"]))
                          if logic_at(a[name], i) != logic_at(b[name], j)), None)
            row.update(first=first, status="Differs" if first is not None else "No difference in overlap")
        rows.append(row)
    return {**grid, "rows": rows}


def plot_window(trace, comparison, side, name, center):
    matches = {s["name"]: s for s in trace["signals"]}
    start = min(max(0, len(comparison["times"]) - 14), max(0, center - 6))
    end = start + 14
    times = comparison["times"][start:end]
    signals = []
    if name in matches:
        sig = matches[name]
        indexes = comparison[side][start:end]
        signals.append({**sig, "logic_values": [logic_at(sig, i) for i in indexes],
                        "values": [sig["values"][i] for i in indexes]})
    return ({"times": times, "cycles": len(times), "signals": signals,
             "ruler": f"ALIGNED / {comparison['unit']}"}, center - start)
