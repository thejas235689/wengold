"""An independent reference implementation of the invalidation semantics.

Written deliberately differently from the kernel — it enumerates upstream *paths*
explicitly rather than doing a closure with an edge filter — so the two can be
cross-checked. When they disagree on a generated graph, one of them is wrong and
the disagreement is the finding.
"""
from __future__ import annotations

from ..graph.model import DesignGraph, EdgeKind
from .validity import Result


def _paths(graph: DesignGraph, start: str, visited: frozenset):
    """Yield every simple upstream path from `start` as [(node, edge_kind), ...]."""
    for e in graph.in_edges(start):
        if e.src in visited:
            continue
        head = [(e.src, e.kind)]
        yield head
        for rest in _paths(graph, e.src, visited | {e.src}):
            yield head + rest


def _upstream(graph: DesignGraph, deps: set[str]) -> tuple[set[str], set[str]]:
    """(certain, uncertain) upstream node sets.

    certain   reachable along a path that never crosses an UNKNOWN edge
    uncertain reachable only along a path that does cross an UNKNOWN edge
    """
    certain: set[str] = set()
    uncertain: set[str] = set()
    for dep in deps:
        for path in _paths(graph, dep, frozenset({dep})):
            nodes = [n for n, _k in path]
            kinds = [k for _n, k in path]
            if EdgeKind.UNKNOWN in kinds:
                uncertain.update(nodes)
            else:
                certain.update(nodes)
    uncertain -= certain
    return certain, uncertain


def reference_verdict(graph: DesignGraph, result: Result, changed: set[str]) -> str:
    """The verdict the semantics require, computed by explicit path enumeration."""
    if not result.depends_on:
        return "unknown"
    if result.depends_on & changed:
        return "invalidated"

    certain, uncertain = _upstream(graph, result.depends_on)

    if certain & changed:
        return "invalidated"
    if uncertain & changed:
        return "unknown"

    closure = result.depends_on | certain | uncertain
    if any(n not in graph.nodes for n in closure):
        return "unknown"
    if any(not graph.nodes[n].resolved for n in closure if n in graph.nodes):
        return "unknown"
    if graph.approximate:
        return "unknown"
    return "valid"


def cross_check(graph: DesignGraph, results: list[Result],
                changed: set[str]) -> list[dict]:
    """Compare the real kernel against the reference on the same inputs."""
    from .validity import classify
    out = []
    for r in results:
        real = classify(graph, r, changed).verdict.value
        ref = reference_verdict(graph, r, changed)
        if real != ref:
            out.append({"result": r.id, "kernel": real, "reference": ref})
    return out
