"""The result contract, and the four independent questions.

A stored "PASS" is dangerously ambiguous. This module makes a verification result
carry an explicit contract — what it claims, over what scope, by what method,
under what assumptions, with what evidence, and within what limits — so the
conclusion cannot be read more broadly than the check supports.

It also separates four questions that are usually collapsed into one bit:

    execution   what happened when the tool ran        (passed / failed / ...)
    currency    is the evidence still current          (current / stale / unknown)
    establishes what the check actually shows          (observation / bounded / proof)
    acceptance  has engineering accepted it            (accepted / rejected / waived)

They are independent. A current simulation pass is limited evidence. A waiver is
an engineering decision and must never become a technical pass.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------- four questions
class Execution(str, Enum):
    """What happened during execution?"""
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CRASHED = "crashed"
    TOOL_MISSING = "tool_missing"


class Currency(str, Enum):
    """Is the evidence current? (computed by the kernel, not stored)"""
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"
    WITHDRAWN = "withdrawn"


class Establishes(str, Enum):
    """What does the result establish? Ordered weakest to strongest."""
    NONE = "none"
    OBSERVATION = "observation"          # simulation exercised some inputs
    BOUNDED_CHECK = "bounded_check"      # bounded formal / assertions up to a depth
    PROOF = "proof"                      # a completed unbounded proof


class Acceptance(str, Enum):
    """Has engineering accepted it? (a human decision, never a technical pass)"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WAIVED = "waived"


_ESTABLISHES_RANK = {Establishes.NONE: 0, Establishes.OBSERVATION: 1,
                     Establishes.BOUNDED_CHECK: 2, Establishes.PROOF: 3}


def establishes_at_least(have: Establishes, need: Establishes) -> bool:
    return _ESTABLISHES_RANK[have] >= _ESTABLISHES_RANK[need]


class MethodKind(str, Enum):
    SIMULATION = "simulation"
    BOUNDED = "bounded"
    PROOF = "proof"
    LINT = "lint"
    SYNTHESIS = "synthesis"


# ---------------------------------------------------------------- the contract
def _pairs(d: dict | None) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in (d or {}).items()))


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True)
class Scope:
    """What the claim is about: files, configuration, reset behaviour."""
    files: tuple[str, ...] = ()
    config: tuple[tuple[str, str], ...] = ()      # (parameter/define/feature, value)
    reset: str | None = None

    @classmethod
    def make(cls, files=(), config=None, reset=None) -> "Scope":
        return cls(tuple(files), _pairs(config), reset)

    def as_dict(self) -> dict:
        return {"files": list(self.files), "config": dict(self.config), "reset": self.reset}


@dataclass(frozen=True)
class Method:
    """How the claim was established: the method, engine and settings."""
    kind: MethodKind = MethodKind.SIMULATION
    engine: str | None = None
    settings: tuple[tuple[str, str], ...] = ()

    @classmethod
    def make(cls, kind: MethodKind | str, engine=None, settings=None) -> "Method":
        return cls(MethodKind(kind), engine, _pairs(settings))

    def as_dict(self) -> dict:
        return {"kind": self.kind.value, "engine": self.engine, "settings": dict(self.settings)}


@dataclass(frozen=True)
class Assumptions:
    """What the claim assumes: input protocol constraints, reset assumptions."""
    items: tuple[str, ...] = ()
    discharged: tuple[str, ...] = ()

    @classmethod
    def make(cls, items=(), discharged=()) -> "Assumptions":
        return cls(tuple(items), tuple(discharged))

    def undischarged(self) -> tuple[str, ...]:
        done = set(self.discharged)
        return tuple(i for i in self.items if i not in done)

    def as_dict(self) -> dict:
        return {"items": list(self.items), "discharged": list(self.discharged),
                "undischarged": list(self.undischarged())}


@dataclass(frozen=True)
class EvidenceRef:
    """The witness: fingerprints, commands, proof status, artifacts."""
    fingerprints: tuple[tuple[str, str], ...] = ()
    commands: tuple[str, ...] = ()
    proof_status: str | None = None
    artifacts: tuple[str, ...] = ()

    @classmethod
    def make(cls, fingerprints=None, commands=(), proof_status=None,
             artifacts=()) -> "EvidenceRef":
        return cls(_pairs(fingerprints), tuple(commands), proof_status, tuple(artifacts))

    def as_dict(self) -> dict:
        return {"fingerprints": dict(self.fingerprints), "commands": list(self.commands),
                "proof_status": self.proof_status, "artifacts": list(self.artifacts)}


@dataclass(frozen=True)
class Limits:
    """What the claim does not cover: supported config and modeling gaps."""
    supported_config: tuple[tuple[str, tuple[str, ...]], ...] = ()
    gaps: tuple[str, ...] = ()

    @classmethod
    def make(cls, supported_config=None, gaps=()) -> "Limits":
        cfg = tuple(sorted((str(k), tuple(str(v) for v in vals))
                           for k, vals in (supported_config or {}).items()))
        return cls(cfg, tuple(gaps))

    def covers(self, config: dict) -> bool:
        """Is `config` inside the declared supported configuration?"""
        declared = {k: set(v) for k, v in self.supported_config}
        for k, v in config.items():
            if k in declared and str(v) not in declared[k]:
                return False
        return True

    def as_dict(self) -> dict:
        return {"supported_config": {k: list(v) for k, v in self.supported_config},
                "gaps": list(self.gaps)}


@dataclass(frozen=True)
class Contract:
    """Everything a stored result must carry to be read correctly."""
    claim: str
    scope: Scope = field(default_factory=Scope)
    method: Method = field(default_factory=Method)
    assumptions: Assumptions = field(default_factory=Assumptions)
    evidence: EvidenceRef = field(default_factory=EvidenceRef)
    limits: Limits = field(default_factory=Limits)

    def as_dict(self) -> dict:
        return {"claim": self.claim, "scope": self.scope.as_dict(),
                "method": self.method.as_dict(), "assumptions": self.assumptions.as_dict(),
                "evidence": self.evidence.as_dict(), "limits": self.limits.as_dict()}

    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(_canonical(self.as_dict()).encode()).hexdigest()[:16]

    def config(self) -> dict:
        return dict(self.scope.config)

    def in_scope(self) -> bool:
        """Does the declared configuration fall inside the declared limits?"""
        return self.limits.covers(self.config())

    def summary(self) -> str:
        m = self.method
        return (f"{self.claim} [{m.kind.value}"
                f"{'/' + m.engine if m.engine else ''}"
                f"; config {self.config() or 'default'}"
                f"; assumptions {len(self.assumptions.items)}"
                f"; gaps {len(self.limits.gaps)}]")
