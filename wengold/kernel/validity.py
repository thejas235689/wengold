"""The validity kernel.

Given a set of changed nodes and the prior results, decide for every prior result
whether it is still VALID, has been INVALIDATED, or is UNKNOWN.

The kernel is *conservative by construction*: it returns VALID only when it can
prove the result does not depend on the change. Anything it cannot prove — an
empty dependency set, a dependency on a node the elaboration could not resolve,
a change reachable only across an uncertain edge, or a graph built without a
full elaboration — becomes UNKNOWN and is re-established rather than assumed.

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
    """A prior verification conclusion and what it rests on.

    `depends_on` is the set of *design* nodes the result consumed. It must be
    populated: an empty set is treated as UNKNOWN, not as VALID, because we
    cannot claim a result is unaffected by a change we never mapped.

    `depends_on_results` links results to results (e.g. a coverage result that
    summarises a set of simulation results), so reruns propagate downstream.
    """
    id: str
    kind: str                      # "sim" | "formal" | "coverage" | "cdc" | ...
    depends_on: set[str] = field(default_factory=set)
    depends_on_results: set[str] = field(default_factory=set)
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
    # 0. No recorded dependencies means we cannot reason about the change at all.
    #    This is the dangerous case the review calls out: missing dependencies
    #    must never preserve evidence.
    if not result.depends_on:
        return Classification(result, Verdict.UNKNOWN,
                              "no recorded dependencies; evidence is not bound to the design")

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
    #    is never trusted.
    if uncertain_only & changed:
        return Classification(result, Verdict.UNKNOWN,
                              "dependency uncertain; must re-establish")

    # 4. The result rests on a node the elaboration could not resolve. We cannot
    #    claim it is unaffected, so it is re-established.
    closure = result.depends_on | certain | all_reach
    unresolved = graph.unresolved_nodes() & closure
    if unresolved:
        return Classification(result, Verdict.UNKNOWN,
                              f"depends on unresolved node(s): {sorted(unresolved)}")

    # 5. A graph built without a full elaboration cannot support a VALID verdict.
    if graph.approximate:
        return Classification(result, Verdict.UNKNOWN,
                              "graph is approximate (no full elaboration); cannot prove validity")

    # 6. Otherwise the evidence still holds.
    return Classification(result, Verdict.VALID, "no dependency on the change")


def classify_all(graph: DesignGraph, results: list[Result],
                 changed: set[str]) -> list[Classification]:
    return [classify(graph, r, changed) for r in results]


def completeness_report(graph: DesignGraph) -> dict:
    """Surface the graph's completeness for the CLI and the agents."""
    return graph.completeness()
