"""Calibration, escalation, and the human decision loop.

The load-bearing test here is `test_the_belief_is_calibrated`. Everything else in
this package states probabilities and acts on them; if those numbers stop
predicting outcomes, every measurement in the agent layer becomes decoration.
"""
import random

import pytest

from wengold.agent.belief import Belief
from wengold.agent.human import (HumanDecision, calibration, escalation_curve,
                                 record_decision, reliability_curve,
                                 should_escalate)
from wengold.agent.memory import Memory


def _belief(n=200, seed=0):
    """A belief whose priors are known, and outcomes drawn from those priors."""
    rng = random.Random(seed)
    priors = {}
    outcomes = {}
    for i in range(n):
        p = rng.choice([0.1, 0.35, 0.5, 0.7, 0.9])
        priors[f"r{i}"] = p
        outcomes[f"r{i}"] = rng.random() <= p
    return Belief(priors, "synthetic"), outcomes


# ---- calibration -----------------------------------------------------------
def test_a_well_calibrated_belief_scores_low():
    b, outcomes = _belief(400, seed=1)
    cal = calibration(b, outcomes)
    assert cal["ece"] < 0.10, cal
    assert cal["n"] == 400


def test_an_overconfident_belief_is_caught():
    """A belief that says 0.95 everywhere while half the checks fail."""
    priors = {f"r{i}": 0.95 for i in range(200)}
    outcomes = {f"r{i}": (i % 2 == 0) for i in range(200)}
    cal = calibration(Belief(priors, "overconfident"), outcomes)
    assert cal["ece"] > 0.3, cal
    assert "NOT calibrated" in cal["verdict"]


def test_the_reliability_curve_bins_sum_to_the_sample():
    b, outcomes = _belief(150)
    rows = reliability_curve(b, outcomes)
    assert sum(r["n"] for r in rows) == 150


def test_calibration_with_no_data_does_not_divide_by_zero():
    cal = calibration(Belief({}, "empty"), {})
    assert cal["ece"] == 0.0 and cal["verdict"] == "no data"


# ---- escalation ------------------------------------------------------------
def test_an_uncertain_check_escalates_and_a_certain_one_does_not():
    b = Belief({"a": 0.5, "b": 0.99}, "t")
    assert should_escalate(b, "a") is True
    assert should_escalate(b, "b") is False


def test_an_expensive_check_escalates_even_when_fairly_likely_to_pass():
    b = Belief({"a": 0.85}, "t")
    assert should_escalate(b, "a", cost=4.0) is True
    assert should_escalate(b, "a", cost=1.0) is False


def test_widening_the_threshold_costs_attention_and_catches_failures():
    b, outcomes = _belief(300, seed=2)
    rows = escalation_curve(b, outcomes, thresholds=(0.0, 0.2, 0.4))
    assert rows[0]["escalation_rate"] <= rows[1]["escalation_rate"] <= rows[2]["escalation_rate"]
    assert rows[0]["failures_caught"] <= rows[1]["failures_caught"] <= rows[2]["failures_caught"]


# ---- the human decision loop ----------------------------------------------
def test_a_waiver_is_remembered_as_a_pass():
    m = Memory()
    record_decision(m, HumanDecision("r1", "waive", "known-good block"))
    assert m.pass_rate("r1") == 1.0
    assert m.recall("decision:r1")["action"] == "waive"


def test_an_override_is_remembered_as_a_failure():
    m = Memory()
    record_decision(m, HumanDecision("r2", "override", "the check is wrong"))
    assert m.pass_rate("r2") == 0.0


def test_a_decision_must_be_one_of_the_four_actions():
    with pytest.raises(ValueError):
        HumanDecision("r3", "ignore")


def test_a_human_decision_moves_the_next_belief():
    """The loop that makes this augmentation rather than logging.

    Note the `is None` check. Writing `pass_rate(r) or 0.5` here turns a legitimate
    0.0 — a result that always fails — into 0.5, because 0.0 is falsy. That is a
    live hazard in any code that defaults a probability this way, and it silently
    erases exactly the strongest evidence the memory can hold.
    """
    m = Memory()
    record_decision(m, HumanDecision("r1", "override", "fails in the field"))
    rate = m.pass_rate("r1")
    assert rate is not None
    assert (rate if rate is not None else 0.5) == 0.0
    assert (rate or 0.5) == 0.5, "this is the trap the test exists to document"
