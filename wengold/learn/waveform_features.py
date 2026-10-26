"""Waveform features, so the learners can read a VCD as well as a graph.

Every learner in this package so far reads the **graph**: fan-in, fan-out, depth,
parameter counts. Measured against simulation ground truth those features showed
**zero lift** — they detect artefacts of the regex elaborator, not anything about
behaviour. A waveform is a different signal entirely: it is what the design
*actually did*, cycle by cycle.

What this module extracts, per signal:

| feature | meaning | why it matters |
| --- | --- | --- |
| `toggles` | value changes over the dump | raw activity |
| `toggle_rate` | toggles per cycle | activity normalised for dump length |
| `duty` | fraction of cycles at 1 | a signal stuck at 1 is not being exercised |
| `x_fraction` | fraction of cycles with x/z | uninitialised or contended state |
| `max_run` | longest unchanged run | a signal that never moves is dead logic |
| `switching_cycles` | fraction of cycles that changed | distinguishes sparse from busy |
| `entropy` | Shannon entropy of the value distribution | how much information it carries |
| `width` | declared width | a 1-bit flag and a 64-bit bus are not comparable |

`waveform_features()` returns one dict per signal; `waveform_vector()` turns them
into the row format `learn/features.vector` already produces, so DBSCAN, the trees,
the regression and the clustering all consume waveforms without changes.

**The honest limit.** These features are real and they are measured off real dumps,
but a *product-level* claim — "waveform features predict which blocks fail" — needs
a simulator to produce the dumps and the failures. `cocotb` and `iverilog` are not
installed in this environment, so the validation here is against constructed
waveforms with known properties, not against a regression run. That is stated in
the release notes rather than dressed up.
"""
from __future__ import annotations

import math
from collections import Counter

__all__ = ["signal_features", "waveform_features", "waveform_vector",
           "FEATURE_KEYS", "activity_summary", "waveform_dataset"]

FEATURE_KEYS = ["toggles", "toggle_rate", "duty", "x_fraction", "max_run",
                "switching_cycles", "entropy", "width"]


def _as_bits(value) -> str:
    return str(value).strip().lower()


def _is_x(value: str) -> bool:
    return any(c in value for c in "xz")


def signal_features(sig: dict, cycles: int) -> dict[str, float]:
    """Features for one signal. `cycles` is the dump length."""
    values = [_as_bits(v) for v in sig.get("values", [])]
    width = float(sig.get("width", 1) or 1)
    n = len(values)
    if not n:
        return {k: 0.0 for k in FEATURE_KEYS[:-1]} | {"width": width}

    toggles = sum(1 for a, b in zip(values, values[1:]) if a != b)
    ones = sum(1 for v in values if v not in ("0", "x", "z") and int_or(v) == 1)
    xs = sum(1 for v in values if _is_x(v))
    switching = sum(1 for a, b in zip(values, values[1:]) if a != b)

    # longest run of an unchanged value
    best = run = 1
    for a, b in zip(values, values[1:]):
        run = run + 1 if a == b else 1
        best = max(best, run)

    counts = Counter(values)
    total = sum(counts.values())
    entropy = -sum((c / total) * math.log2(c / total) for c in counts.values() if c)
    entropy = entropy + 0.0        # a stuck signal otherwise reports -0.0

    denom = max(cycles or n, 1)
    return {
        "toggles": float(toggles),
        "toggle_rate": toggles / denom,
        "duty": ones / n,
        "x_fraction": xs / n,
        "max_run": float(best),
        "switching_cycles": switching / max(n - 1, 1),
        "entropy": entropy,
        "width": width,
    }


def int_or(v: str) -> int:
    """A VCD value can be `1`, `01`, `1b1` — take the last bit for a 1-bit net."""
    try:
        return int(v, 2) if set(v) <= {"0", "1"} else 0
    except ValueError:
        return 0


def waveform_features(wave: dict) -> dict[str, dict[str, float]]:
    """One feature dict per signal name."""
    cycles = int(wave.get("cycles", 0) or 0)
    return {s["name"]: signal_features(s, cycles) for s in wave.get("signals", [])}


def waveform_vector(feats: dict[str, float], keys: list[str] | None = None) -> list[float]:
    """The row format `learn.features.vector` produces, for the waveform keys."""
    keys = keys or FEATURE_KEYS
    return [float(feats.get(k, 0.0)) for k in keys]


def waveform_dataset(wave: dict, keys: list[str] | None = None):
    """`(names, X)` in the same shape `learn.features.dataset` returns.

    This is the whole point of the module: the learners take a matrix and a list of
    row labels, and they do not care whether the numbers came from a graph or a
    VCD. Point DBSCAN, the trees or the regression at this instead and they work
    unchanged.
    """
    keys = keys or FEATURE_KEYS
    feats = waveform_features(wave)
    names = sorted(feats)
    return names, [waveform_vector(feats[n], keys) for n in names]


def activity_summary(wave: dict) -> dict:
    """A short, human-readable account of how alive the dump is.

    Useful on its own: a design whose every signal has `toggles == 0` was not
    exercised, and that is worth knowing before any learner is pointed at it.
    """
    feats = waveform_features(wave)
    if not feats:
        return {"signals": 0, "dead": 0, "fraction_dead": 0.0, "verdict": "empty dump"}
    dead = [n for n, f in feats.items() if f["toggles"] == 0]
    xed = [n for n, f in feats.items() if f["x_fraction"] > 0.0]
    frac = len(dead) / len(feats)
    if frac > 0.5:
        verdict = (f"{len(dead)} of {len(feats)} signals never changed — this dump "
                   f"exercised little of the design")
    elif xed:
        verdict = (f"{len(xed)} signal(s) carry x/z — uninitialised or contended "
                   f"state; waveform features will reflect that, and so should a plan")
    else:
        verdict = f"{len(feats)} signals, {len(feats) - len(dead)} switching, no x/z"
    return {"signals": len(feats), "dead": len(dead), "fraction_dead": frac,
            "with_x": len(xed), "verdict": verdict}
