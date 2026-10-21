"""The result contract, and the four independent questions."""
from wengold.kernel.contract import (Acceptance, Assumptions, Contract, Currency,
                                     Establishes, EvidenceRef, Execution, Limits,
                                     Method, MethodKind, Scope, establishes_at_least)


def _fifo_contract(**kw) -> Contract:
    base = dict(
        claim="FIFO never overflows under the stated interface assumptions.",
        scope=Scope.make(files=["fifo.sv"], config={"DEPTH": 16, "WIDTH": 64},
                         reset="synchronous"),
        method=Method.make(MethodKind.PROOF, engine="sby", settings={"mode": "prove"}),
        assumptions=Assumptions.make(["in_valid held until in_ready"],
                                     discharged=["in_valid held until in_ready"]),
        evidence=EvidenceRef.make(fingerprints={"fifo.sv": "sha256:abc"},
                                  commands=["sby -f fifo.sby"], proof_status="PASS",
                                  artifacts=["fifo/logfile.txt"]),
        limits=Limits.make(supported_config={"DEPTH": [8, 16], "WIDTH": [32, 64]},
                           gaps=["reset glitch shorter than one cycle not modeled"]),
    )
    base.update(kw)
    return Contract(**base)


def test_contract_carries_every_field():
    c = _fifo_contract()
    d = c.as_dict()
    assert set(d) == {"claim", "scope", "method", "assumptions", "evidence", "limits"}
    assert d["scope"]["config"] == {"DEPTH": "16", "WIDTH": "64"}
    assert d["method"]["engine"] == "sby"
    assert d["assumptions"]["undischarged"] == []
    assert d["evidence"]["proof_status"] == "PASS"
    assert "not modeled" in d["limits"]["gaps"][0]


def test_contract_digest_is_stable_and_sensitive():
    a, b = _fifo_contract(), _fifo_contract()
    assert a.digest() == b.digest()
    other = _fifo_contract(claim="FIFO never underflows.")
    assert other.digest() != a.digest()


def test_limits_covers_configuration():
    lim = Limits.make(supported_config={"DEPTH": [8, 16]})
    assert lim.covers({"DEPTH": 8}) is True
    assert lim.covers({"DEPTH": 32}) is False
    assert lim.covers({"OTHER": 1}) is True       # unconstrained key


def test_in_scope():
    assert _fifo_contract().in_scope() is True
    out = _fifo_contract(scope=Scope.make(files=["fifo.sv"], config={"DEPTH": 1024}))
    assert out.in_scope() is False


def test_undischarged_assumptions():
    c = Contract(claim="x", assumptions=Assumptions.make(["a", "b"], discharged=["a"]))
    assert c.assumptions.undischarged() == ("b",)


def test_four_questions_are_independent_enums():
    # the same result can be a current pass that establishes only an observation,
    # or a stale run that engineering has accepted.
    assert Execution.PASSED.value == "passed"
    assert Currency.CURRENT.value == "current"
    assert Establishes.OBSERVATION.value == "observation"
    assert Acceptance.WAIVED.value == "waived"
    assert len({Execution, Currency, Establishes, Acceptance}) == 4


def test_establishes_ordering():
    assert establishes_at_least(Establishes.PROOF, Establishes.BOUNDED_CHECK)
    assert not establishes_at_least(Establishes.OBSERVATION, Establishes.PROOF)
