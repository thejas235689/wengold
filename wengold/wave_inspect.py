"""Deterministic waveform measurements and WaveDrom export, without Qt."""
from __future__ import annotations

from bisect import bisect_left
from math import gcd
import re


def logic_at(signal: dict, index: int) -> str:
    states = signal.get("logic_values")
    if states is not None:
        return states[index]
    value = signal["values"][index]
    return "x" if value is None else format(value, "b").zfill(signal["width"])


def render_value(signal: dict, index: int, radix: str) -> str:
    bits = logic_at(signal, index)
    if any(bit in bits for bit in "xz"):
        # Preserve partial unknown/high-Z data rather than replacing a mixed bus
        # with one X or falsely displaying a numeric value.
        return bits.upper()
    value = int(bits, 2)
    if radix == "Binary":
        return "0b" + bits
    if radix == "Unsigned":
        return str(value)
    if radix == "Signed":
        return str(value - (1 << signal["width"]) if bits[0] == "1" else value)
    return f"0x{value:0{(signal['width'] + 3) // 4}X}"


def time_label(tick: int, timescale: str | None) -> str:
    scale = re.fullmatch(r"(1|10|100)(s|ms|us|ns|ps|fs)", timescale or "")
    return f"{tick * int(scale[1])} {scale[2]}" if scale else f"{tick} ticks"


def time_at(data: dict, index: int) -> int:
    return data["times"][index]


def nearest_sample(times: list[int], tick: int) -> int:
    right = bisect_left(times, tick)
    if not 0 < right < len(times):
        return min(right, len(times) - 1)
    left = right - 1
    return left if tick - times[left] <= times[right] - tick else right


def next_change(signal: dict, index: int, direction: int) -> int | None:
    length = len(signal["values"])
    # A transition is anchored at the first new value, not the previous slot.
    offsets = (range(index + 1, length) if direction > 0 else range(index - 1, 0, -1))
    return next((i for i in offsets if logic_at(signal, i) != logic_at(signal, i - 1)), None)


def wave_drom(data: dict, signals: list[dict], a: int, b: int,
              radix: str = "Hex", *, max_slots: int = 240) -> dict:
    """Export an exact observed time grid, or refuse a window too large to render."""
    if not data or not isinstance(a, int) or not isinstance(b, int):
        raise ValueError("Choose two distinct observed cursor timestamps")
    if not signals:
        raise ValueError("Pin one or more signals before exporting")
    if len(signals) > 24:
        raise ValueError("Pin at most 24 signals for a readable diagram")
    if any(s["width"] > 256 for s in signals):
        raise ValueError("WaveDrom export supports signals up to 256 bits wide")
    times = data["times"]
    start, end = sorted((a, b))
    if not 0 <= start < end < len(times):
        raise ValueError("Choose two distinct observed cursor timestamps")
    step = 0
    for i in range(start, end):
        step = gcd(step, times[i + 1] - times[i])
    if step <= 0:
        raise ValueError("Observed timestamps must increase")
    slots = (times[end] - times[start]) // step + 1
    if slots > max_slots:
        raise ValueError(f"Exact time grid needs {slots} slots (limit {max_slots}); narrow the cursor window")
    sample_slots = {(times[i] - times[start]) // step: i for i in range(start, end + 1)}
    lanes = []
    # The boundary sample has no observed interval after it. Display its value
    # in the last slot, with a caption making this endpoint convention explicit.
    for sig in signals:
        wave = ["."] * slots
        labels = []
        previous = None
        for slot, index in sample_slots.items():
            bits = logic_at(sig, index)
            if index != start and bits == previous:
                continue
            previous = bits
            if sig["width"] == 1:
                wave[slot] = bits
            elif set(bits) == {"x"} or set(bits) == {"z"}:
                wave[slot] = bits[0]
            else:
                wave[slot] = "="
                labels.append(render_value(sig, index, radix))
        lane = {"name": sig["name"], "wave": "".join(wave)}
        if labels:
            lane["data"] = labels
        lanes.append(lane)
    scale = data.get("timescale")
    source_format = data.get("source_format", "vcd")
    return {"signal": lanes,
            "head": {"text": f"Observed {source_format.upper()} waveform", "tick": 0},
            "foot": {"text": f"Slot width: {time_label(step, scale)}. "
                              "Last slot shows the endpoint sample only."},
            "wengold": {"kind": f"observed_{source_format}", "source": data["source"],
                        "source_sha256": data.get("source_sha256"),
                        "timescale": scale, "start_tick": times[start],
                        "end_tick": times[end], "ticks_per_slot": step,
                        "samples_truncated": bool(data.get("samples_truncated"))}}
