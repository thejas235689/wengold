"""Differential comparison of passing and failing simulation waveforms.

Values are compared by fully-qualified signal path and physical VCD time after
converting each capture's timescale to nanoseconds. Missing signals and X/Z
(unknown) samples are reported explicitly; no value is guessed.
"""
from __future__ import annotations

from bisect import bisect_right
from decimal import Decimal
from typing import Any


def _time_scale(wave: dict) -> Decimal:
    value = wave.get("time_unit_ns")
    if value is None:
        return Decimal(1)
    try:
        scale = Decimal(str(value))
    except Exception as exc:
        raise ValueError("invalid waveform time_unit_ns") from exc
    if scale <= 0:
        raise ValueError("waveform time_unit_ns must be positive")
    return scale


def _signal_map(wave: dict) -> dict[str, dict]:
    result = {}
    for signal in wave.get("signals", []):
        name = str(signal.get("name", "")).strip()
        if not name:
            continue
        if name in result:
            raise ValueError(f"duplicate signal path in waveform: {name}")
        result[name] = signal
    return result


def _timeline(wave: dict, scale: Decimal):
    raw = wave.get("times")
    if raw is None:
        raw = list(range(int(wave.get("cycles", 0))))
    if len(raw) != int(wave.get("cycles", len(raw))):
        raise ValueError("waveform timestamps and cycle count do not match")
    times = [Decimal(str(t)) * scale for t in raw]
    if any(b < a for a, b in zip(times, times[1:])):
        raise ValueError("waveform timestamps must be monotonic")
    return times


def _sample_at(signal: dict, indices: list[int], times: list[Decimal],
               target: Decimal):
    pos = bisect_right(times, target) - 1
    if pos < 0:
        return None
    values = signal.get("values", [])
    index = indices[pos]
    return values[index] if index < len(values) else None


def compare_waveforms(pass_wave: dict, fail_wave: dict, *,
                      max_differences: int = 5000) -> dict[str, Any]:
    """Compare PASS and FAIL VCDs on a common physical-time timeline.

    VCD value changes are sampled with hold-last-value semantics. The union
    of timestamps is used, so differences between change events are not lost.
    """
    if not isinstance(max_differences, int) or not 1 <= max_differences <= 50000:
        raise ValueError("max_differences must be between 1 and 50000")
    pscale, fscale = _time_scale(pass_wave), _time_scale(fail_wave)
    ptime, ftime = _timeline(pass_wave, pscale), _timeline(fail_wave, fscale)
    pmap, fmap = _signal_map(pass_wave), _signal_map(fail_wave)
    common = sorted(set(pmap) & set(fmap))
    pass_only = sorted(set(pmap) - set(fmap))
    fail_only = sorted(set(fmap) - set(pmap))
    if not common:
        raise ValueError("the PASS and FAIL VCDs have no matching fully-qualified signal paths")
    if not ptime or not ftime:
        raise ValueError("both waveforms must contain at least one timestamp")

    # Compare the common physical-time interval. A sample is held until the
    # next value change, as defined by VCD semantics.
    start, end = max(ptime[0], ftime[0]), min(ptime[-1], ftime[-1])
    if end < start:
        raise ValueError("PASS and FAIL captures have no overlapping time range")
    grid = sorted({t for t in ptime if start <= t <= end} |
                  {t for t in ftime if start <= t <= end})
    pidx = list(range(len(ptime)))
    fidx = list(range(len(ftime)))
    differences = []
    per_signal = []
    first = None
    unknown_differences = 0
    total = 0
    for name in common:
        psig, fsig = pmap[name], fmap[name]
        pwidth, fwidth = int(psig.get("width", 1)), int(fsig.get("width", 1))
        count = 0
        first_for_signal = None
        if pwidth != fwidth:
            total += 1
            count += 1
            first_for_signal = {"time_ns": str(start), "pass": f"width={pwidth}",
                                "fail": f"width={fwidth}", "kind": "width_mismatch"}
            width_item = {"signal": name, **first_for_signal}
            if first is None:
                first = width_item
            if len(differences) < max_differences:
                differences.append(width_item)
        for t in grid:
            pv = _sample_at(psig, pidx, ptime, t)
            fv = _sample_at(fsig, fidx, ftime, t)
            if pv == fv:
                continue
            # Do not double count the width mismatch at the first sample.
            if pwidth != fwidth and count == 1 and t == start:
                continue
            total += 1
            count += 1
            kind = "unknown_vs_known" if (pv is None) != (fv is None) else "value_mismatch"
            if kind == "unknown_vs_known":
                unknown_differences += 1
            item = {"signal": name, "time_ns": str(t),
                    "pass": pv, "fail": fv, "kind": kind}
            if first_for_signal is None:
                first_for_signal = {k: item[k] for k in
                                    ("time_ns", "pass", "fail", "kind")}
            if first is None:
                first = item
            if len(differences) < max_differences:
                differences.append(item)
        if count:
            per_signal.append({"signal": name, "differences": count,
                               "first_difference": first_for_signal})
    per_signal.sort(key=lambda x: (-x["differences"], x["signal"]))
    return {
        "status": "different" if total else "identical_on_common_signals",
        "pass_cycles": len(ptime), "fail_cycles": len(ftime),
        "common_signals": len(common), "pass_only_signals": pass_only,
        "fail_only_signals": fail_only, "compared_timestamps": len(grid),
        "total_differences": total, "reported_differences": len(differences),
        "truncated": total > len(differences),
        "unknown_differences": unknown_differences,
        "first_divergence": first, "per_signal": per_signal,
        "differences": differences,
        "time_alignment": "absolute VCD time converted to ns; hold-last-value; common capture interval",
        "limits": ["Only exact fully-qualified signal paths are matched.",
                   "X/Z are represented as unknown (None) by the current VCD parser.",
                   "Captures are not automatically aligned to reset release or first transaction.",
                   "A first divergence is a debug clue, not proof of root cause."]
    }
