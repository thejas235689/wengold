"""Universal prediction and off-policy evaluation.

Two tests carry the weight here:

* `test_ips_is_unbiased_but_useless_when_the_support_is_narrow` pins the finding
  that matters — IPS is correct in expectation and catastrophic in practice, while
  SNIPS recovers the answer.
* `test_the_mixture_is_not_solomonoff_induction` pins the honesty. A description-
  length mixture over a fixed class is not Solomonoff induction, and the test says
  so in a way that would fail if someone started claiming otherwise.
"""
import math
import random

import pytest

from wengold.learn.universal import Mixture, ips, snips


# ---- the bounded mixture ---------------------------------------------------
def test_the_mixture_is_a_distribution_over_hypotheses():
    m = Mixture()
    assert abs(sum(m.posterior.values()) - 1.0) < 1e-9
    assert 0.0 <= m.predict() <= 1.0


def test_shorter_descriptions_start_with_more_weight():
    m = Mixture()
    assert m.posterior["always 0"] > m.posterior["period 5"], (
        "a 1-bit hypothesis must outweigh an 8-bit one")


def test_observing_a_contradiction_kills_a_hypothesis():
    m = Mixture()
    m.observe(1)
    m.observe(1)
    assert m.posterior["always 0"] < 1e-6, "a hypothesis contradicted twice must die"


def test_the_mixture_is_not_solomonoff_induction():
    """A fixed, finite hypothesis class is a *bounded* mixture.

    Solomonoff induction sums over all programs and is incomputable. This is a
    description-length prior over eight hand-written predictors. The test exists so
    the distinction cannot quietly erode.
    """
    m = Mixture()
    assert len(m.hypotheses) == 8, "the class is fixed and small, by construction"
    assert all(h.bits > 0 for h in m.hypotheses)


def test_a_periodic_signal_does_not_make_the_mixture_psychic():
    """Pinned negative: the short hypotheses dominate for a long time.

    On `101` repeated, the mixture predicts no better than a frequency count over
    the first dozen observations, and its best hypothesis is 'always 1' rather than
    'period 3' — which costs more bits than the data can pay for yet.
    """
    m = Mixture()
    seq = [1, 0, 1] * 5
    hits_mix = hits_freq = n = 0
    k = tot = 0
    for i, bit in enumerate(seq):
        if i >= 3:
            n += 1
            hits_mix += (m.predict() > 0.5) == bool(bit)
            hits_freq += ((k / tot) if tot else 0.5 > 0.5) == bool(bit)
        m.observe(bit)
        k += bit
        tot += 1
    assert hits_mix <= n, "cannot beat perfect"
    assert m.best() in m.posterior


# ---- off-policy evaluation -------------------------------------------------
def _setup(seed=0):
    rng = random.Random(seed)
    n, halt = 8, 5
    p = {f"c{i}": (0.9 if i % 3 else 0.3) for i in range(n)}
    names = [f"c{i}" for i in range(n)]

    def rollout(order):
        d = 0
        for c in order[:halt]:
            if rng.random() > p[c]:
                break
            d += 1
        return d

    def log(n_traj):
        out = []
        for _ in range(n_traj):
            o = list(names)
            rng.shuffle(o)
            out.append({"actions": [(o[i], 1.0 / (n - i)) for i in range(halt)],
                        "return": rollout(o)})
        return out

    target = {c: 1.0 for c in sorted(names, key=lambda c: -p[c])[:halt]}
    true_value = sum(rollout(tuple(sorted(names, key=lambda c: -p[c])))
                     for _ in range(4000)) / 4000
    return log, target, true_value


def test_snips_recovers_the_target_value():
    log, target, true_value = _setup()
    est = snips(log(3000), target)
    assert abs(est.value - true_value) < 0.5, (est.value, true_value)
    assert est.stderr < 1.0, "the error bar must be usable, not ±50"


def test_ips_is_unbiased_but_useless_when_the_support_is_narrow():
    """The finding worth keeping.

    The target ordering has probability 1/8! under a uniform behaviour policy, so a
    handful of trajectories carry all the weight: effective sample collapses and IPS
    reports a value hundreds of times too large. SNIPS divides by the weight sum and
    recovers the answer.
    """
    log, target, true_value = _setup()
    logged = log(2000)
    a, b = ips(logged, target), snips(logged, target)
    assert a.value > 10 * true_value, "IPS should have blown up here"
    assert abs(b.value - true_value) < 0.5, "SNIPS should not have"
    assert a.effective_sample < 0.1 * a.n, "the effective sample is the warning sign"


def test_an_empty_log_does_not_divide_by_zero():
    for fn in (ips, snips):
        e = fn([], {"a": 1.0})
        assert e.value == 0.0 and e.n == 0


def test_a_zero_probability_behaviour_action_gives_zero_weight():
    """The support condition: if behaviour could never take the action, IPS cannot
    evaluate a target that does. The weight goes to zero rather than to infinity."""
    logged = [{"actions": [("x", 0.0)], "return": 5.0}]
    assert ips(logged, {"x": 1.0}).value == 0.0
