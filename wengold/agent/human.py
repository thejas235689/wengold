"""The human interface: calibration, escalation, and what a person decides.

Everything in this package states probabilities. `belief.py` says P(this check
passes) = 0.92, and every planner downstream trusts that number. **Nothing has
checked whether it is true.** A system that says 0.92 and is right 60% of the time
is worse than one that says nothing, because the number gets acted on.

So this module does three things, and the first is the one that matters:

* **Calibration** — bin the stated probabilities against what actually happened,
  and report the reliability curve and the expected calibration error. This is
  the measurement behind "trust", and it is the one a vendor would rather you did
  not run.
* **Escalation** — the Moravec split made operational. The machine is good at
  counting: how many results depend on this, what it costs, what history says. The
  human is needed where the machine is *genuinely uncertain*, which is a small,
  identifiable set. `escalation_policy` picks it, and the cost is measured: what
  fraction of checks go to a person, and what fraction of failures that catches.
* **A decision record** — what the human did (accept, waive, override, escalate)
  and why, written back into `Memory` so the next run's priors reflect it. That is
  the feedback loop; without the write-back it is just a log.

The point of the escalation measurement is that augmentation has a *price*, and it
is payable in human attention. A policy that escalates everything catches every
failure and is useless; one that escalates nothing is the status quo. The useful
number is the curve between them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .belief import Belief

__all__ = ["calibration", "reliability_curve", "should_escalate",
           "escalation_curve", "HumanDecision", "record_decision"]


def reliability_curve(belief: Belief, outcomes: dict, bins: int = 5) -> list[dict]:
    """Predicted vs observed pass rate per confidence bin.

    `outcomes` maps result id -> True if the check passed.
    """
    rows = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        members = []
        for r in outcomes:
            if r not in belief.priors:
                continue
            p = belief.p(r)
            in_bin = (lo <= p < hi) or (b == bins - 1 and p >= hi)
            if in_bin:
                members.append((p, outcomes[r]))
        if not members:
            continue
        predicted = sum(p for p, _ in members) / len(members)
        observed = sum(1 for _, o in members if o) / len(members)
        rows.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(members),
                     "predicted": predicted, "observed": observed,
                     "gap": abs(predicted - observed)})
    return rows


def calibration(belief: Belief, outcomes: dict, bins: int = 5) -> dict:
    """Expected calibration error, weighted by bin size.

    ECE = sum over bins of (n_bin / n) * |observed - predicted|. 0 is perfect.
    """
    rows = reliability_curve(belief, outcomes, bins)
    total = sum(r["n"] for r in rows)
    if not total:
        return {"ece": 0.0, "n": 0, "rows": [], "verdict": "no data"}
    ece = sum(r["n"] / total * r["gap"] for r in rows)
    if ece < 0.05:
        verdict = "well calibrated"
    elif ece < 0.15:
        verdict = "usable, but the numbers should not be quoted to three places"
    else:
        verdict = "NOT calibrated — the stated probabilities do not predict outcomes"
    return {"ece": ece, "n": total, "rows": rows, "verdict": verdict}


def should_escalate(belief: Belief, rid: str, cost: float = 1.0,
                    uncertainty: float = 0.25, expensive: float = 3.0) -> bool:
    """Send it to a person when the machine is unsure, or when being wrong is dear.

    Two triggers, because they are different failures: a coin-flip the machine
    cannot resolve, and a cheap-looking call that costs a lot to get wrong.
    """
    p = belief.p(rid)
    unsure = abs(p - 0.5) <= uncertainty
    dear = cost >= expensive and p < 0.95
    return unsure or dear


def escalation_curve(belief: Belief, outcomes: dict, costs: dict | None = None,
                     thresholds=(0.0, 0.1, 0.2, 0.3, 0.4)) -> list[dict]:
    """The price of augmentation: how much human attention, how many failures caught.

    At threshold 0 nothing escalates and no failures are caught (the status quo).
    As it widens, more checks go to a person and more of the failures are caught —
    but the machine also asks about things that would have been fine. The useful
    reading is where the caught-failure rate stops improving.
    """
    costs = costs or {}
    rows = []
    failures = {r for r, o in outcomes.items() if not o}
    for t in thresholds:
        asked = [r for r in outcomes
                 if r in belief.priors and should_escalate(belief, r,
                                                          costs.get(r, 1.0),
                                                          uncertainty=t)]
        caught = len(set(asked) & failures)
        rows.append({
            "threshold": t,
            "escalation_rate": len(asked) / max(len(outcomes), 1),
            "failures_caught": caught / max(len(failures), 1),
            "precision": caught / max(len(asked), 1),
        })
    return rows


@dataclass
class HumanDecision:
    result: str
    action: str                 # accept | waive | override | escalate
    rationale: str = ""
    by: str = "human"

    def __post_init__(self):
        allowed = {"accept", "waive", "override", "escalate"}
        if self.action not in allowed:
            raise ValueError(f"action must be one of {sorted(allowed)}")


def record_decision(memory, decision: HumanDecision, passed: bool | None = None) -> None:
    """Write a human decision into memory so the next run's priors reflect it.

    A waived result is remembered as having passed — a person looked at it and
    said so — and an overridden one as having failed. That is the whole feedback
    loop; without this write-back the decision is a log entry and nothing more.
    """
    memory.remember(f"decision:{decision.result}",
                    {"action": decision.action, "rationale": decision.rationale,
                     "by": decision.by})
    if decision.action == "waive" or (decision.action == "accept" and passed):
        memory.record([decision.result], [decision.result],
                      {decision.result: "pass"}, 0, 0)
    elif decision.action == "override":
        memory.record([decision.result], [decision.result],
                      {decision.result: "fail"}, 0, 0)
