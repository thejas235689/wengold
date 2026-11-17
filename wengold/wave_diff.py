"""Differential PASS/FAIL waveform comparison with reset and clock alignment.

VCD timestamps are converted to nanoseconds before alignment. Reset alignment
uses the first observed active-to-inactive reset transition. Clock alignment
maps samples to normalized clock-cycle coordinates (cycle + phase), allowing
different clock periods to be compared without discarding intra-cycle events.
"""
from __future__ import annotations

from bisect import bisect_right
from decimal import Decimal
from typing import Any


def _time_scale(wave: dict) -> Decimal:
    value = wave.get("time_unit_ns")
    try:
        scale = Decimal(str(1 if value is None else value))
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


def _timeline(wave: dict, scale: Decimal) -> list[Decimal]:
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


def _reset_release(wave: dict, signals: dict, times: list[Decimal],
                   signal_name: str, active_level: int) -> Decimal:
    if active_level not in (0, 1):
        raise ValueError("reset_active_level must be 0 or 1")
    signal = signals.get(signal_name)
    if signal is None:
        raise ValueError(f"reset signal not found: {signal_name}")
    values = signal.get("values", [])
    previous_active = False
    for index, value in enumerate(values[:len(times)]):
        if value == active_level:
            previous_active = True
        elif value == 1 - active_level and previous_active:
            return times[index]
    raise ValueError(
        f"reset release not found for {signal_name}; capture must show active then inactive reset")


def _clock_axis(times: list[Decimal], signals: dict, clock_name: str,
                side: str) -> tuple[list[Decimal], dict]:
    signal = signals.get(clock_name)
    if signal is None:
        raise ValueError(f"{side} clock signal not found: {clock_name}")
    values = signal.get("values", [])
    edges = []
    previous = None
    for index, value in enumerate(values[:len(times)]):
        if previous == 0 and value == 1:
            edges.append(times[index])
        if value is not None:
            previous = value
    if len(edges) < 2:
        raise ValueError(
            f"{side} clock {clock_name} needs at least two observed rising edges")
    periods = [b - a for a, b in zip(edges, edges[1:])]
    if any(period <= 0 for period in periods):
        raise ValueError(f"{side} clock {clock_name} has non-increasing rising edges")
    last_period = periods[-1]
    axis = []
    for timestamp in times:
        pos = bisect_right(edges, timestamp) - 1
        if pos < 0:
            phase = (timestamp - edges[0]) / periods[0]
            coordinate = phase
        elif pos >= len(edges) - 1:
            coordinate = Decimal(pos) + (timestamp - edges[pos]) / last_period
        else:
            coordinate = Decimal(pos) + (
                (timestamp - edges[pos]) / periods[pos])
        axis.append(coordinate)
    return axis, {"clock": clock_name, "rising_edges": len(edges),
                  "first_edge_ns": str(edges[0]),
                  "last_edge_ns": str(edges[-1])}


def compare_waveforms(pass_wave: dict, fail_wave: dict, *,
                      max_differences: int = 5000,
                      alignment: str = "absolute",
                      pass_reset_signal: str | None = None,
                      fail_reset_signal: str | None = None,
                      reset_active_level: int = 0,
                      pass_clock_signal: str | None = None,
                      fail_clock_signal: str | None = None) -> dict[str, Any]:
    """Compare PASS and FAIL waveforms on absolute, reset-relative, or cycle axes.

    Clock alignment preserves intra-cycle phase while normalizing different
    clock periods. VCD values use hold-last-value semantics.
    """
    if not isinstance(max_differences, int) or not 1 <= max_differences <= 50000:
        raise ValueError("max_differences must be between 1 and 50000")
    if alignment not in ("absolute", "reset", "clock"):
        raise ValueError("alignment must be 'absolute', 'reset', or 'clock'")
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

    alignment_info: dict[str, Any] = {"mode": alignment}
    if alignment == "absolute":
        paxis, faxis = ptime, ftime
        axis_label = "ns"
    elif alignment == "reset":
        pr_name = pass_reset_signal or ""
        fr_name = fail_reset_signal or pr_name
        prelease = _reset_release(pass_wave, pmap, ptime, pr_name,
                                  reset_active_level)
        frelease = _reset_release(fail_wave, fmap, ftime, fr_name,
                                  reset_active_level)
        paxis = [t - prelease for t in ptime]
        faxis = [t - frelease for t in ftime]
        alignment_info.update({"pass_reset_signal": pr_name,
                               "fail_reset_signal": fr_name,
                               "pass_reset_release_ns": str(prelease),
                               "fail_reset_release_ns": str(frelease),
                               "reset_active_level": reset_active_level})
        axis_label = "ns_after_reset_release"
    else:
        pc_name = pass_clock_signal or pass_wave.get("clock") or ""
        fc_name = fail_clock_signal or fail_wave.get("clock") or pc_name
        paxis, pclock = _clock_axis(ptime, pmap, pc_name, "PASS")
        faxis, fclock = _clock_axis(ftime, fmap, fc_name, "FAIL")
        alignment_info.update({"pass_clock": pclock, "fail_clock": fclock})
        axis_label = "cycle"

    start, end = max(paxis[0], faxis[0]), min(paxis[-1], faxis[-1])
    if end < start:
        raise ValueError("PASS and FAIL captures have no overlapping aligned time range")
    grid = sorted({t for t in paxis if start <= t <= end} |
                  {t for t in faxis if start <= t <= end})
    pidx, fidx = list(range(len(ptime))), list(range(len(ftime)))
    differences, per_signal = [], []
    unknown_differences = total = 0
    first = None
    for name in common:
        psig, fsig = pmap[name], fmap[name]
        pwidth, fwidth = int(psig.get("width", 1)), int(fsig.get("width", 1))
        count, first_for_signal = 0, None
        if pwidth != fwidth:
            total += 1
            count += 1
            first_for_signal = {"aligned_time": str(start), "time_unit": axis_label,
                                "pass": f"width={pwidth}", "fail": f"width={fwidth}",
                                "kind": "width_mismatch"}
            item = {"signal": name, **first_for_signal}
            differences.append(item)
            if first is None or start < Decimal(first["aligned_time"]):
                first = item
        for t in grid:
            pt = t + (ptime[0] - paxis[0])
            ft = t + (ftime[0] - faxis[0])
            # For reset/absolute alignment, axis is an offset from original time.
            # Clock mode requires inverse mapping from normalized cycle to source
            # time, so use the nearest source timestamp in that cycle coordinate.
            pv = _sample_at(psig, pidx, paxis, t)
            fv = _sample_at(fsig, fidx, faxis, t)
            if pv == fv:
                continue
            if pwidth != fwidth and count == 1 and t == start:
                continue
            total += 1
            count += 1
            kind = "unknown_vs_known" if (pv is None) != (fv is None) else "value_mismatch"
            if kind == "unknown_vs_known":
                unknown_differences += 1
            item = {"signal": name, "aligned_time": str(t), "time_unit": axis_label,
                    "pass": pv, "fail": fv, "kind": kind}
            if first_for_signal is None:
                first_for_signal = {k: item[k] for k in
                                    ("aligned_time", "time_unit", "pass", "fail", "kind")}
            if first is None or t < Decimal(first["aligned_time"]):
                first = item
            if len(differences) < max_differences:
                differences.append(item)
        if count:
            per_signal.append({"signal": name, "differences": count,
                               "first_difference": first_for_signal})
    per_signal.sort(key=lambda x: (-x["differences"], x["signal"]))
    differences.sort(key=lambda item: Decimal(item["aligned_time"]))
    if len(differences) > max_differences:
        differences = differences[:max_differences]
    return {
        "status": "different" if total else "identical_on_common_signals",
        "alignment": alignment_info, "time_unit": axis_label,
        "pass_cycles": len(ptime), "fail_cycles": len(ftime),
        "common_signals": len(common), "pass_only_signals": pass_only,
        "fail_only_signals": fail_only, "compared_timestamps": len(grid),
        "total_differences": total, "reported_differences": len(differences),
        "truncated": total > len(differences),
        "unknown_differences": unknown_differences,
        "first_divergence": first, "per_signal": per_signal,
        "differences": differences,
        "limits": ["Only exact fully-qualified signal paths are matched.",
                   "X/Z are represented as unknown (None) by the current VCD parser.",
                   "Reset alignment requires an observed active-to-inactive transition.",
                   "Clock alignment normalizes period and phase; inspect the raw ns timestamps for physical timing.",
                   "A first divergence is a debug clue, not proof of root cause."]
    }
