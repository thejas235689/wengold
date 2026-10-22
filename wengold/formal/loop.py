"""The counterexample-guided proof loop.

Check the properties; on a counterexample, diagnose it, propose a repair, apply
it to the source and check again — bounded by a budget. Every attempt and every
outcome is recorded, and each property leaves a `Contract` so the claim cannot be
read more broadly than the proof supports.

A bounded result is recorded as a bounded check, never as a proof; a design that
cannot be parsed is recorded as UNKNOWN, never as a pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..agents.debugger import Debugger
from ..agents.repair import Repairer
from ..kernel.contract import (Acceptance, Assumptions, Contract, Establishes,
                               EvidenceRef, Execution, Limits, Method, MethodKind,
                               Scope)
from ..kernel.validity import Result
from .engine import FormalResult, FormalStatus, check
from .ir import Property, PropertyKind, sva_module
from .rtl_model import UnsupportedConstruct, parse_module, to_model

_METHOD = {FormalStatus.PROOF: MethodKind.PROOF, FormalStatus.BOUNDED: MethodKind.BOUNDED}
_EXECUTION = {FormalStatus.PROOF: Execution.PASSED, FormalStatus.BOUNDED: Execution.PASSED,
              FormalStatus.FAIL: Execution.FAILED, FormalStatus.UNKNOWN: Execution.NOT_RUN}


@dataclass
class ProofOutcome:
    property: str
    status: str
    engine: str
    depth: int | None
    detail: str
    establishes: str
    attempts: int = 1
    trace: list | None = None

    def as_dict(self) -> dict:
        return {"property": self.property, "status": self.status, "engine": self.engine,
                "depth": self.depth, "detail": self.detail,
                "establishes": self.establishes, "attempts": self.attempts,
                "trace": self.trace}


def contract_for(module: str, prop: Property, res: FormalResult,
                 rtl_text: str, depth: int | None) -> Contract:
    """The contract a formal result carries."""
    kind = _METHOD.get(res.status, MethodKind.BOUNDED)
    # a gap is an undeclared limit of the *claim*; a counterexample is a
    # refutation, not a gap, so it is recorded in the evidence status instead.
    gaps = []
    if res.status is FormalStatus.BOUNDED:
        gaps = [f"bounded: {res.detail}"]
    elif res.status is FormalStatus.UNKNOWN:
        gaps = [f"undecided: {res.detail}"]
    return Contract(
        claim=f"{module}: {prop.expr}",
        scope=Scope.make(files=[f"{module}.sv"]),
        method=Method.make(kind, engine=res.engine,
                           settings={"depth": depth, "engine": res.engine}),
        assumptions=Assumptions.make(),
        evidence=EvidenceRef.make(fingerprints={"property": prop.digest(),
                                                "rtl": f"len:{len(rtl_text)}"},
                                  commands=[f"wengold formal --engine {res.engine}"],
                                  proof_status=res.status.value),
        limits=Limits.make(supported_config={}, gaps=gaps),
    )


def result_for(module: str, prop: Property, res: FormalResult, rtl_text: str,
               depth: int | None) -> Result:
    return Result(
        id=prop.name, kind="formal", depends_on={module},
        contract=contract_for(module, prop, res, rtl_text, depth),
        execution=_EXECUTION[res.status],
        establishes=res.establishes,
        acceptance=Acceptance.PENDING,
    )


def default_repair(repairer: Repairer | None = None):
    """A repair hook built from the Repairer: proposes an edit and applies it."""
    repairer = repairer or Repairer()

    def repair(rtl_text: str, failure: FormalResult):
        diag = Debugger().investigate({
            "outcome": "fail", "tool": "formal",
            "log": f"counterexample for {failure.property}: {failure.detail}"})
        prop = repairer.propose({**diag, "property": failure.property,
                                 "trace": failure.trace})
        if prop.get("find") and prop.get("replace") is not None:
            new = repairer.apply(rtl_text, prop)
            if new != rtl_text:
                return new
        return None

    return repair


def prove(rtl_text: str, properties: list[Property], engine: str = "auto",
          depth: int = 12, budget: int = 3, repair=None, ledger=None,
          max_states: int = 20000) -> dict:
    """Check the properties, repairing on counterexamples up to `budget` times."""
    module = None
    text = rtl_text
    iterations: list[dict] = []
    results: list[FormalResult] = []
    repair_fn = repair if repair is not None else default_repair()

    for attempt in range(max(1, budget)):
        try:
            rtl = parse_module(text)
        except UnsupportedConstruct as e:
            results = [FormalResult(p.name, FormalStatus.UNKNOWN, engine,
                                    detail=f"front-end: {e}") for p in properties]
            iterations.append({"attempt": attempt, "error": str(e)})
            break
        module = rtl.name
        model = to_model(rtl)
        results = check(model, properties, engine=engine, depth=depth,
                        max_states=max_states)
        iterations.append({"attempt": attempt,
                           "results": [r.as_dict() for r in results]})
        if ledger is not None:
            ledger.append("formal_run", {"attempt": attempt, "module": module,
                                         "results": [r.as_dict() for r in results]})
        failures = [r for r in results if r.status is FormalStatus.FAIL]
        if not failures or repair_fn is None or attempt == budget - 1:
            break
        new_text = repair_fn(text, failures[0])
        if not new_text or new_text == text:
            break
        text = new_text
        if ledger is not None:
            ledger.append("formal_repair", {"attempt": attempt,
                                            "property": failures[0].property})

    module = module or "unknown"
    outcomes = [ProofOutcome(prop_name := r.property, r.status.value, r.engine, r.depth,
                             r.detail, r.establishes.value, len(iterations), r.trace)
                for r in results]
    contracts = [contract_for(module, p, r, text, depth)
                 for p, r in zip(properties, results)]
    result_objects = [result_for(module, p, r, text, depth)
                      for p, r in zip(properties, results)]
    sva = sva_module(module, properties)
    summary = {
        "module": module,
        "results": outcomes,
        "contracts": contracts,
        "result_objects": result_objects,
        "sva": sva,
        "rtl": text,
        "repaired": text != rtl_text,
        "iterations": iterations,
        "proved": all(r.status is FormalStatus.PROOF for r in results) and bool(results),
        "counterexamples": [r.property for r in results if r.status is FormalStatus.FAIL],
    }
    if ledger is not None:
        ledger.append("formal_end", {"module": module, "proved": summary["proved"],
                                     "counterexamples": summary["counterexamples"]})
    return summary
