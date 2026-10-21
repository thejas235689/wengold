"""The validity kernel.

Given a set of changed nodes and the prior results, decide for every prior result
whether it is still VALID, has been INVALIDATED, or is UNKNOWN. The kernel never
guesses: where a dependency is uncertain it returns UNKNOWN so the result is
re-established, never assumed.

    prior results + delta  ->  minimum new evidence  ->  verified state
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..graph.model import DesignGraph, EdgeKind


class Verdict(str, Enum):
    VALID = "valid"
    INVALIDATED = "invalidated"
    UNKNOWN = "unknown"


@dataclass
class Result:
    """A prior verification conclusion and the design nodes it depends on."""
    id: str
    kind: str                      # "sim" | "formal" | "coverage" | "cdc" | ...
    depends_on: set[str] = field(default_factory=set)
    status: str = "pass"


@dataclass
class Classification:
    result: Result
    verdict: Verdict
    reason: str


def _reach(graph: DesignGraph, start: str, allow_unknown: bool) -> set[str]:
    """Upstream closure of `start`. With allow_unknown=False, UNKNOWN edges are
    not traversed, so we get only the dependencies we are *certain* about."""
    seen: set[str] = set()
    stack = [start]
    while stack:
        cur = stack.pop()
        for e in graph.in_edges(cur):
            if e.kind is EdgeKind.UNKNOWN and not allow_unknown:
                continue
            if e.src not in seen:
                seen.add(e.src)
                stack.append(e.src)
    return seen


def _reach_all(graph: DesignGraph, deps: set[str], allow_unknown: bool) -> set[str]:
    out: set[str] = set()
    for d in deps:
        out |= _reach(graph, d, allow_unknown)
    return out


def classify(graph: DesignGraph, result: Result, changed: set[str]) -> Classification:
    # 1. A direct dependency on a changed node invalidates.
    affected = result.depends_on & changed
    if affected:
        return Classification(result, Verdict.INVALIDATED,
                              f"depends on changed node(s): {sorted(affected)}")

    # Split the upstream closure into what we are certain about and what is only
    # reachable by crossing an UNKNOWN edge.
    certain = _reach_all(graph, result.depends_on, allow_unknown=False)
    all_reach = _reach_all(graph, result.depends_on, allow_unknown=True)
    uncertain_only = all_reach - certain

    # 2. A change we are certain reaches the result invalidates it.
    if certain & changed:
        return Classification(result, Verdict.INVALIDATED,
                              f"change propagates into result via {sorted(certain & changed)}")

    # 3. A change that might reach it, but only across an uncertain dependency,
    #    is never trusted — the result must be re-established.
    if uncertain_only & changed:
        return Classification(result, Verdict.UNKNOWN,
                              "dependency uncertain; must re-establish")

    # 4. Otherwise the evidence still holds.
    return Classification(result, Verdict.VALID, "no dependency on the change")


def classify_all(graph: DesignGraph, results: list[Result],
                 changed: set[str]) -> list[Classification]:
    return [classify(graph, r, changed) for r in results]
