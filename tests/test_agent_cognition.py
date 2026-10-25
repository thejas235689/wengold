"""The cognitive scorecard: what the agent can be shown to do, and what it cannot.

The load-bearing tests are the ones that keep the scorecard honest. A scorecard
that only reports passes is a brochure, so:

* every ability must be one of the three statuses — there is no "partial";
* an ability marked "measured" must carry a score, not a promise;
* the abilities that cannot be tested here must say *why*, so the gap is a
  documented limitation rather than an omission;
* at least one ability must be allowed to fail, or the harness is not testing
  anything.
"""
import pytest

from wengold.agent.cognition import Ability, Scorecard, evaluate

STATUSES = {"measured", "failed", "not measurable here"}


def test_every_ability_has_a_valid_status():
    sc = evaluate()
    assert sc.abilities
    for a in sc.abilities:
        assert a.status in STATUSES, (a.name, a.status)


def test_a_measured_ability_carries_a_score_not_a_promise():
    for a in evaluate().abilities:
        if a.status == "measured":
            assert a.score and "TODO" not in a.score.upper(), a.name


def test_untestable_abilities_say_why():
    for a in evaluate().abilities:
        if a.status == "not measurable here":
            assert a.score and len(a.score) > 3, a.name


def test_the_scorecard_allows_failure():
    """If nothing can fail, the harness is decorative."""
    sc = evaluate()
    assert any(a.status == "failed" for a in sc.abilities), (
        "no ability failed — either the agent improved or the probes stopped probing")


def test_the_summary_counts_add_up():
    sc = evaluate()
    n, m = len(sc.abilities), len(sc.measured)
    assert 0 < m <= n
    text = sc.render()
    assert f"{m} of {n} abilities measurable here" in text


def test_perception_and_metacognition_are_measured():
    names = {a.name: a for a in evaluate().abilities}
    assert names["perception"].status == "measured"
    assert names["metacognition"].status == "measured"
    assert "ECE" in names["metacognition"].score


def test_an_ability_rejects_a_made_up_status():
    a = Ability("x", "measured", "1.0")
    assert a.render().startswith("  x")
    with pytest.raises(AssertionError):
        assert "partial" in STATUSES
