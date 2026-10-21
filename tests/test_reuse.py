"""Reuse obligations, the decision record, and withdrawal."""
from wengold.graph.model import DesignGraph, Node, NodeKind
from wengold.kernel.contract import (Acceptance, Assumptions, Contract, Establishes,
                                     Execution, Limits, Method, MethodKind, Scope)
from wengold.kernel.reuse import (decide, record_withdrawal, verify_decision,
                                  withdrawals_from_ledger)
from wengold.kernel.validity import Result
from wengold.ledger.store import Ledger


def _graph():
    g = DesignGraph()
    for n in ("fifo", "other"):
        g.add_node(Node(n, NodeKind.RTL))
    return g


def _contract():
    return Contract(
        claim="no overflow", scope=Scope.make(files=["fifo.sv"], config={"DEPTH": 16}),
        method=Method.make(MethodKind.PROOF, engine="sby"),
        assumptions=Assumptions.make(["in_valid until in_ready"],
                                     discharged=["in_valid until in_ready"]),
        limits=Limits.make(supported_config={"DEPTH": [8, 16]}))


def _result(**kw):
    base = dict(id="fifo_proof", kind="formal", depends_on={"fifo"},
                contract=_contract(), execution=Execution.PASSED,
                establishes=Establishes.PROOF, acceptance=Acceptance.ACCEPTED)
    base.update(kw)
    return Result(**base)


def test_reusable_when_all_obligations_met():
    d = decide(_graph(), _result(), {"other"}, required=Establishes.PROOF,
               require_contract=True)
    assert d.reusable is True
    assert d.accepted_for_use is True
    assert d.unmet() == []


def test_stale_evidence_is_not_reusable():
    d = decide(_graph(), _result(), {"fifo"})       # its own dep changed
    assert d.reusable is False
    assert "evidence_current" in d.unmet()


def test_insufficient_establishment_is_not_reusable():
    d = decide(_graph(), _result(establishes=Establishes.OBSERVATION),
               {"other"}, required=Establishes.PROOF)
    assert d.reusable is False
    assert "established_at_required_level" in d.unmet()


def test_waiver_is_not_a_technical_pass():
    # a waiver with stale evidence must not become reusable
    d = decide(_graph(), _result(acceptance=Acceptance.WAIVED), {"fifo"})
    assert d.reusable is False            # technically not reusable
    assert d.waived is True
    assert d.accepted_for_use is True     # engineering may proceed, on record
    assert "not a technical pass" in d.reason


def test_rejected_is_never_accepted():
    d = decide(_graph(), _result(acceptance=Acceptance.REJECTED), {"other"})
    assert d.reusable is False and d.accepted_for_use is False


def test_undischarged_assumption_blocks_reuse():
    c = _contract()
    c2 = Contract(claim=c.claim, scope=c.scope, method=c.method,
                  assumptions=Assumptions.make(["a", "b"], discharged=["a"]))
    d = decide(_graph(), _result(contract=c2), {"other"})
    assert d.reusable is False
    assert "assumptions_discharged" in d.unmet()


def test_config_out_of_scope_blocks_reuse():
    c = Contract(claim="x", scope=Scope.make(config={"DEPTH": 1024}),
                 method=Method.make(MethodKind.PROOF),
                 limits=Limits.make(supported_config={"DEPTH": [8, 16]}))
    d = decide(_graph(), _result(contract=c), {"other"})
    assert "config_in_scope" in d.unmet()


def test_decision_record_is_independently_checkable():
    d = decide(_graph(), _result(), {"other"}, required=Establishes.PROOF,
               require_contract=True)
    rec = d.record(_result(), Establishes.PROOF).as_dict()
    ok, issues = verify_decision(rec)
    assert ok and issues == []

    # tamper: claim reusable with stale evidence
    bad = dict(rec); bad["currency"] = "stale"
    ok, issues = verify_decision(bad)
    assert not ok and any("non-current" in i or "implies" in i for i in issues)

    # tamper: flip reusable
    bad2 = dict(rec); bad2["reusable"] = not rec["reusable"]
    assert verify_decision(bad2)[0] is False


def test_withdrawal_retracts_and_propagates(tmp_path):
    led = Ledger(tmp_path / "l.tof")
    record_withdrawal(led, "fifo_proof", "sby soundness bug in release 0.61")
    withdrawn = withdrawals_from_ledger(led)
    assert set(withdrawn) == {"fifo_proof"}
    assert withdrawn["fifo_proof"]["kind"] == "checker_bug"

    # a result that leaned on the withdrawn one is no longer reusable
    base = Result("signoff", "coverage", depends_on={"fifo"},
                  depends_on_results={"fifo_proof"})
    d = decide(_graph(), base, {"other"}, results=[base, _result()],
               withdrawn=set(withdrawn))
    assert d.reusable is False
    assert "supporting_evidence_current" in d.unmet()


def test_withdrawal_of_self_marks_currency():
    d = decide(_graph(), _result(), {"other"}, withdrawn={"fifo_proof"})
    assert d.currency.value == "withdrawn"
    assert "not_withdrawn" in d.unmet()
