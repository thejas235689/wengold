"""Waveform features, and that every learner can consume them.

The load-bearing test is `test_the_features_separate_behavioural_groups`: it is the
claim the module exists to support — that a VCD carries signal the graph does not.
Graph features measured zero lift against simulation ground truth; these are
measured off what the design actually did.
"""
import random

import pytest

from wengold.learn import dbscan as DB
from wengold.learn.waveform_features import (FEATURE_KEYS, activity_summary,
                                             signal_features, waveform_dataset,
                                             waveform_features, waveform_vector)


def _wave():
    rng = random.Random(0)
    sigs = []
    for i in range(6):
        sigs.append({"name": f"clk{i}", "width": 1, "values": ["0", "1"] * 40})
    for i in range(8):
        sigs.append({"name": f"data{i}", "width": 8,
                     "values": [format(rng.randrange(256), "08b") for _ in range(80)]})
    for i in range(5):
        sigs.append({"name": f"tie{i}", "width": 1, "values": ["0"] * 80})
    return {"cycles": 80, "signals": sigs}


# ---- the extractor ---------------------------------------------------------
def test_a_stuck_signal_has_no_toggles_and_a_long_run():
    f = signal_features({"width": 1, "values": ["0"] * 8}, 8)
    assert f["toggles"] == 0 and f["max_run"] == 8 and f["duty"] == 0.0
    assert f["entropy"] == 0.0, "a stuck signal carries no information"


def test_a_stuck_high_signal_is_distinguished_from_a_stuck_low_one():
    hi = signal_features({"width": 1, "values": ["1"] * 8}, 8)
    lo = signal_features({"width": 1, "values": ["0"] * 8}, 8)
    assert hi["duty"] == 1.0 and lo["duty"] == 0.0
    assert hi["toggles"] == lo["toggles"] == 0


def test_a_toggling_signal_has_duty_one_half_and_max_entropy():
    f = signal_features({"width": 1, "values": ["0", "1"] * 4}, 8)
    assert f["toggles"] == 7 and f["duty"] == 0.5
    assert abs(f["entropy"] - 1.0) < 1e-9


def test_x_and_z_are_counted_separately_from_zero():
    f = signal_features({"width": 1, "values": ["x", "0", "1", "z"]}, 4)
    assert f["x_fraction"] == 0.5, "x and z both count as unknown"


def test_a_bus_carries_more_entropy_than_a_bit():
    bus = signal_features({"width": 8, "values": ["00", "01", "10", "11"]}, 4)
    bit = signal_features({"width": 1, "values": ["0", "1", "0", "1"]}, 4)
    assert bus["entropy"] > bit["entropy"]


def test_an_empty_signal_does_not_divide_by_zero():
    f = signal_features({"width": 1, "values": []}, 0)
    assert all(isinstance(v, float) for v in f.values())


# ---- the bridge ------------------------------------------------------------
def test_the_dataset_has_one_row_per_signal_and_one_column_per_feature():
    names, X = waveform_dataset(_wave())
    assert len(names) == len(X) == 19
    assert all(len(row) == len(FEATURE_KEYS) for row in X)


def test_the_vector_order_matches_the_key_order():
    f = signal_features({"width": 1, "values": ["0", "1"] * 4}, 8)
    v = waveform_vector(f)
    assert len(v) == len(FEATURE_KEYS)
    assert v[FEATURE_KEYS.index("duty")] == 0.5


# ---- the claim -------------------------------------------------------------
def test_the_features_separate_behavioural_groups():
    """Clocks, data buses and tied-off nets must cluster apart.

    This is what graph features could not do: measured against simulation ground
    truth they showed zero lift. A waveform separates these three groups on
    behaviour alone, with no labels supplied.
    """
    names, X = waveform_dataset(_wave())
    r = DB.dbscan(X, eps=0.35, min_pts=2)
    groups = {}
    for n, lab in zip(names, r.labels):
        groups.setdefault(lab, []).append(n)
    clocks = next(g for g in groups.values() if any(n.startswith("clk") for n in g))
    ties = next(g for g in groups.values() if any(n.startswith("tie") for n in g))
    assert clocks is not ties, "clocks and tied-off nets must not share a cluster"
    assert len(clocks) >= 5, f"most clocks should group: {clocks}"
    assert len(ties) >= 4, f"most tied nets should group: {ties}"


def test_activity_summary_warns_when_nothing_moved():
    dead = {"cycles": 4, "signals": [{"name": f"t{i}", "width": 1,
                                      "values": ["0"] * 4} for i in range(4)]}
    s = activity_summary(dead)
    assert s["dead"] == 4
    assert "never changed" in s["verdict"]


def test_activity_summary_reports_x_state():
    w = {"cycles": 4, "signals": [{"name": "a", "width": 1, "values": ["x", "0", "1", "0"]}]}
    assert activity_summary(w)["with_x"] == 1


def test_activity_summary_on_an_empty_dump():
    assert activity_summary({"cycles": 0, "signals": []})["verdict"] == "empty dump"
