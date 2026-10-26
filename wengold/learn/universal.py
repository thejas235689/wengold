"""Universal prediction and unbiased off-policy evaluation.

Four ideas were named: Solomonoff induction, sequential decision theory, unbiased
learning, universal optimality. Two of them are computable in bounded form and one
of those is genuinely useful here. The other two are not implementable, and this
module says so rather than shipping a shadow of them.

**Solomonoff induction** assigns a prior of 2^-l(p) to each program p and predicts
by weighting every program's output by that prior. It is **not computable**: the sum
ranges over all programs and the halting problem decides which contribute. What is
here — `Mixture` — is the bounded, honest version: a *fixed, small hypothesis class*
weighted by 2^-description-length and updated by Bayes. That is a Solomonoff-style
mixture, not Solomonoff induction, and the distinction is the whole point.

**Universal optimality** (AIXI) is incomputable for the same reason, and its
optimality is asymptotic over an infinite horizon. Nothing here claims it.

**Sequential decision theory** is already the shape of `agent/belief.py` and
`agent/planning.py`: a POMDP over evidence with a belief and a policy.

**Unbiased learning** is the one with real value: `ips` and `snips` estimate how a
policy *that never ran* would have scored, using only logged runs — which is exactly
the question "would safest-first have beaten greedy on the runs I already have?".
Unbiased in expectation, and high-variance in practice, which `snips` exists to fix.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["Mixture", "Hypothesis", "ips", "snips", "OPEEstimate"]


@dataclass
class Hypothesis:
    """One predictor, with the description length its prior is derived from."""

    name: str
    bits: int                 # description length in bits
    fn: object                # history (list[int]) -> 0 | 1 | None (abstain)

    @property
    def prior(self) -> float:
        return 2.0 ** -self.bits


def _builtin_hypotheses() -> list[Hypothesis]:
    """A deliberately small class — this is the honest bound on the 'universal' part."""
    return [
        Hypothesis("always 0", 1, lambda h: 0),
        Hypothesis("always 1", 1, lambda h: 1),
        Hypothesis("alternate", 3, lambda h: (len(h) % 2) if h else 0),
        Hypothesis("copy last", 4, lambda h: h[-1] if h else 0),
        Hypothesis("flip last", 5, lambda h: 1 - h[-1] if h else 0),
        Hypothesis("period 3", 6, lambda h: h[-3] if len(h) >= 3 else 0),
        Hypothesis("period 5", 8, lambda h: h[-5] if len(h) >= 5 else 0),
        Hypothesis("majority", 7, lambda h: 1 if sum(h) * 2 > len(h) else 0),
    ]


@dataclass
class Mixture:
    """Bayesian mixture over hypotheses, weighted by 2^-description-length.

    This is a **bounded** Solomonoff-style predictor, not Solomonoff induction: the
    hypothesis class is fixed and finite, so the "universal" claim is dropped and
    what remains is a description-length prior that can be measured against a plain
    frequency estimate.
    """

    hypotheses: list[Hypothesis] = field(default_factory=_builtin_hypotheses)
    posterior: dict = field(init=False)
    history: list = field(default_factory=list)

    def __post_init__(self):
        z = sum(h.prior for h in self.hypotheses)
        self.posterior = {h.name: h.prior / z for h in self.hypotheses}

    def predict(self) -> float:
        """P(next = 1), the posterior-weighted vote."""
        total = 0.0
        for h in self.hypotheses:
            p = h.fn(self.history)
            if p is None:
                continue
            total += self.posterior[h.name] * p
        return total

    def observe(self, bit: int) -> None:
        """Bayesian update; a hypothesis that contradicts the observation is killed."""
        evidence = 0.0
        for h in self.hypotheses:
            p = h.fn(self.history)
            if p is None:
                continue
            evidence += self.posterior[h.name] * (p if bit else 1 - p)
        if evidence <= 0:
            return                      # nothing predicted it; leave the belief alone
        for h in self.hypotheses:
            p = h.fn(self.history)
            if p is None:
                continue
            self.posterior[h.name] = self.posterior[h.name] * (p if bit else 1 - p) / evidence
        self.history.append(bit)

    def best(self) -> str:
        return max(self.posterior, key=self.posterior.get)


@dataclass
class OPEEstimate:
    value: float
    stderr: float
    n: int
    method: str
    effective_sample: float

    def render(self) -> str:
        return (f"  {self.method:<6} value {self.value:>7.3f} ± {self.stderr:.3f}  "
                f"(n={self.n}, effective {self.effective_sample:.0f})")


def _weights(logged: list[dict], target: dict) -> list[float]:
    """Per-trajectory importance weight pi_target / pi_behaviour over the actions taken."""
    out = []
    for traj in logged:
        w = 1.0
        for action, p_b in traj["actions"]:
            p_t = target.get(action, 0.0)
            if p_b <= 0:
                w = 0.0
                break
            w *= p_t / p_b
        out.append(w)
    return out


def ips(logged: list[dict], target: dict) -> OPEEstimate:
    """Ordinary importance sampling — unbiased in expectation, high variance.

    `logged` is a list of trajectories, each `{"actions": [(action, p_behaviour)],
    "return": float}`. `target` maps action -> P(action) under the policy being
    evaluated. The estimate is E_behaviour[(pi_t/pi_b) * return], which is unbiased
    for the target policy's value **provided the behaviour policy never takes a
    zero-probability action the target would take** — the support condition, and the
    first thing that breaks in practice.
    """
    if not logged:
        return OPEEstimate(0.0, 0.0, 0, "IPS", 0.0)
    w = _weights(logged, target)
    vals = [wi * t["return"] for wi, t in zip(w, logged)]
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / max(n - 1, 1)
    return OPEEstimate(mean, math.sqrt(var / n) if n else 0.0, n, "IPS",
                       (sum(w) ** 2) / max(sum(wi * wi for wi in w), 1e-12))


def snips(logged: list[dict], target: dict) -> OPEEstimate:
    """Self-normalised importance sampling — biased, but far lower variance.

    Divides by the sum of the weights instead of n. That makes it consistent rather
    than unbiased, which is the trade worth making: IPS with a handful of
    trajectories produces weights of 50 and a confidence interval of nothing.
    """
    if not logged:
        return OPEEstimate(0.0, 0.0, 0, "SNIPS", 0.0)
    w = _weights(logged, target)
    wsum = sum(w)
    if wsum <= 0:
        return OPEEstimate(0.0, 0.0, len(logged), "SNIPS", 0.0)
    vals = [wi * t["return"] for wi, t in zip(w, logged)]
    mean = sum(vals) / wsum
    # Delta-method standard error for a ratio estimator. The naive variance of the
    # weighted values divided by n gives ±50 on an estimate accurate to ±0.01,
    # because it ignores the normalisation — a wrong error bar is worse than none.
    var_num = sum((wi * (t["return"] - mean)) ** 2 for wi, t in zip(w, logged))
    se = math.sqrt(var_num) / wsum if wsum > 0 else 0.0
    return OPEEstimate(mean, se, len(logged), "SNIPS",
                       (wsum ** 2) / max(sum(wi * wi for wi in w), 1e-12))
