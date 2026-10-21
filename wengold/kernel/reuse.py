"""Proof obligations for reuse, and an independently checkable decision record.

A stored result is not reusable by default. Retaining it is an auditable decision:
each obligation is stated, evaluated, and recorded, so "we kept this" has a reason
rather than an assumption.

The decision is exported as a small, self-contained `DecisionRecord` that another
checker can re-derive without WENGOLD's kernel — so a kernel error is easier to
detect and investigate.

Withdrawal is separate: when a checker bug, bad assumption or tool issue is found,
the affected conclusions are retracted and reuse of anything that leaned on them
is re-assessed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .contract import (Acceptance, Currency, Establishes, establishes_at_least,
                       _ESTABLISHES_RANK)
from .validity import Result, Verdict, classify, verdict_to_currency


@dataclass
class Obligation:
    name: str
    satisfied: bool
    detail: str = ""
    mandatory: bool = True

    def as_dict(self) -> dict:
        return {"name": self.name, "satisfied": self.satisfied,
                "detail": self.detail, "mandatory": self.mandatory}


@dataclass
class Decision:
    result_id: str
    verdict: Verdict
    currency: Currency
    reusable: bool                    # the technical decision
    accepted_for_use: bool            # reusable OR waived (engineering may proceed)
    waived: bool
    obligations: list[Obligation] = field(default_factory=list)
    reason: str = ""

    def unmet(self) -> list[str]:
        return [o.name for o in self.obligations if o.mandatory and not o.satisfied]

    def as_dict(self) -> dict:
        return {"result_id": self.result_id, "verdict": self.verdict.value,
                "currency": self.currency.value, "reusable": self.reusable,
                "accepted_for_use": self.accepted_for_use, "waived": self.waived,
                "obligations": [o.as_dict() for o in self.obligations],
                "reason": self.reason}

    def record(self, result: Result, required: Establishes,
               inputs_digest: str = "") -> "DecisionRecord":
        return DecisionRecord(
            result_id=self.result_id, verdict=self.verdict.value,
            currency=self.currency.value, establishes=result.establishes.value,
            acceptance=result.acceptance.value, required_establishes=required.value,
            inputs_digest=inputs_digest or _inputs_digest(result),
            obligations=[o.as_dict() for o in self.obligations],
            reusable=self.reusable, waived=self.waived)


def _inputs_digest(result: Result) -> str:
    payload = {
        "id": result.id, "kind": result.kind,
        "depends_on": sorted(result.depends_on),
        "depends_on_results": sorted(result.depends_on_results),
        "contract": result.contract.digest() if result.contract else None,
    }
    return "sha256:" + hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- withdrawal
def record_withdrawal(ledger, result_id: str, reason: str,
                      kind: str = "checker_bug") -> dict:
    return ledger.append("withdrawal", {"result": result_id, "reason": reason, "kind": kind})


def withdrawals_from_ledger(ledger) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for rec in ledger:
        if rec.get("kind") == "withdrawal":
            p = rec["payload"]
            out[p["result"]] = {"reason": p.get("reason", ""), "kind": p.get("kind", "")}
    return out


def _supporting_withdrawn(result: Result, results_by_id: dict[str, Result],
                          withdrawn: set[str]) -> list[str]:
    """Supporting results (transitively) that have been withdrawn."""
    seen: set[str] = set()
    hits: list[str] = []
    stack = list(result.depends_on_results)
    while stack:
        rid = stack.pop()
        if rid in seen:
            continue
        seen.add(rid)
        if rid in withdrawn:
            hits.append(rid)
        sup = results_by_id.get(rid)
        if sup is not None:
            stack.extend(sup.depends_on_results)
    return sorted(hits)


# ---------------------------------------------------------------- the decision
def decide(graph, result: Result, changed: set[str], *,
           results: list[Result] | None = None,
           withdrawn: set[str] | None = None,
           required: Establishes = Establishes.OBSERVATION,
           require_contract: bool = False) -> Decision:
    results_by_id = {r.id: r for r in (results or [result])}
    withdrawn = set(withdrawn or ())

    cls = classify(graph, result, changed)
    currency = verdict_to_currency(cls.verdict)
    if result.id in withdrawn:
        currency = Currency.WITHDRAWN

    obligations: list[Obligation] = []

    obligations.append(Obligation(
        "evidence_current", currency is Currency.CURRENT,
        f"currency is {currency.value}: {cls.reason}"))

    obligations.append(Obligation(
        "not_withdrawn", result.id not in withdrawn,
        "this result has been withdrawn" if result.id in withdrawn else "not withdrawn"))

    sup = _supporting_withdrawn(result, results_by_id, withdrawn)
    obligations.append(Obligation(
        "supporting_evidence_current", not sup,
        f"withdrawn supporting evidence: {sup}" if sup else "supporting evidence intact"))

    obligations.append(Obligation(
        "established_at_required_level",
        establishes_at_least(result.establishes, required),
        f"establishes {result.establishes.value}, required {required.value}",
        mandatory=required is not Establishes.NONE))

    obligations.append(Obligation(
        "acceptance_not_rejected", result.acceptance is not Acceptance.REJECTED,
        f"acceptance is {result.acceptance.value}"))

    has_contract = result.contract is not None
    obligations.append(Obligation(
        "contract_present", has_contract,
        "no contract attached" if not has_contract else "contract attached",
        mandatory=require_contract))

    if has_contract:
        obligations.append(Obligation(
            "config_in_scope", result.contract.in_scope(),
            f"config {result.contract.config()} vs limits"))
        undischarged = result.contract.assumptions.undischarged()
        obligations.append(Obligation(
            "assumptions_discharged", not undischarged,
            f"undischarged assumptions: {list(undischarged)}" if undischarged
            else "all assumptions discharged"))
        gaps = result.contract.limits.gaps
        obligations.append(Obligation(
            "no_modeling_gaps", not gaps,
            f"modeling gaps: {list(gaps)}" if gaps else "no declared gaps",
            mandatory=False))       # a declared gap is disclosed, not a reuse blocker

    unmet = [o.name for o in obligations if o.mandatory and not o.satisfied]
    reusable = not unmet
    waived = result.acceptance is Acceptance.WAIVED

    if reusable:
        reason = "all mandatory obligations satisfied"
    else:
        reason = f"unmet obligations: {unmet}"
        if waived:
            reason += " (waived — an engineering decision, not a technical pass)"

    return Decision(result_id=result.id, verdict=cls.verdict, currency=currency,
                    reusable=reusable, accepted_for_use=reusable or waived,
                    waived=waived, obligations=obligations, reason=reason)


# ---------------------------------------------------------------- independent check
@dataclass
class DecisionRecord:
    """A small, self-contained record another checker can validate on its own."""
    result_id: str
    verdict: str
    currency: str
    establishes: str
    acceptance: str
    required_establishes: str
    inputs_digest: str
    obligations: list[dict]
    reusable: bool
    waived: bool

    def as_dict(self) -> dict:
        return {"result_id": self.result_id, "verdict": self.verdict,
                "currency": self.currency, "establishes": self.establishes,
                "acceptance": self.acceptance,
                "required_establishes": self.required_establishes,
                "inputs_digest": self.inputs_digest, "obligations": self.obligations,
                "reusable": self.reusable, "waived": self.waived}

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True)


def verify_decision(record: dict) -> tuple[bool, list[str]]:
    """Re-derive the reuse decision from the record alone.

    Deliberately independent of `decide()`: it reads only the recorded fields and
    re-checks the rule, so a bug in the kernel's own decision path shows up as a
    disagreement rather than passing silently.
    """
    issues: list[str] = []

    currency_current = record.get("currency") == Currency.CURRENT.value
    rank = _ESTABLISHES_RANK.get(Establishes(record["establishes"]), 0)
    need = _ESTABLISHES_RANK.get(Establishes(record["required_establishes"]), 0)
    established = rank >= need
    not_rejected = record.get("acceptance") != Acceptance.REJECTED.value
    mandatory_ok = all(o.get("satisfied", False)
                       for o in record.get("obligations", []) if o.get("mandatory", True))

    expected = bool(currency_current and established and not_rejected and mandatory_ok)
    if expected != record.get("reusable"):
        issues.append(f"reusable={record.get('reusable')} but the record implies {expected}")
    if record.get("waived") and record.get("acceptance") != Acceptance.WAIVED.value:
        issues.append("waived flag set but acceptance is not 'waived'")
    if record.get("reusable") and not currency_current:
        issues.append("claimed reusable with non-current evidence")
    if record.get("reusable") and not established:
        issues.append("claimed reusable below the required establishment level")
    return (not issues), issues
