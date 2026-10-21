"""Minimum new evidence.

From the classification we only need to re-establish what was invalidated or
left unknown — and everything *downstream* of it. Results form their own
dependency graph (a coverage result summarises simulation results; a sign-off
result consumes both), so a rerun propagates: if A must be re-run and B derives
from A, B is stale too and must be re-established.

Everything still valid is kept, along with the evidence behind it.
"""
from __future__ import annotations

from ..graph.model import DesignGraph
from .validity import Classification, Result, Verdict


def _result_dependency_map(classifications: list[Classification],
                           result_deps: dict[str, set[str]] | None) -> dict[str, set[str]]:
    """result id -> the result ids it depends on (its upstream)."""
    deps: dict[str, set[str]] = {}
    for c in classifications:
        upstream = set(getattr(c.result, "depends_on_results", set()) or set())
        if upstream:
            deps[c.result.id] = upstream
    for rid, ups in (result_deps or {}).items():
        deps.setdefault(rid, set()).update(ups)
    return deps


def minimum_new_evidence(graph: DesignGraph,
                         classifications: list[Classification],
                         result_deps: dict[str, set[str]] | None = None) -> list[str]:
    """The smallest set of results that must be re-established.

    = the invalidated and unknown results, closed over everything downstream of
    them in the result graph.
    """
    deps = _result_dependency_map(classifications, result_deps)

    # reverse edges: upstream result -> results that derive from it
    dependents: dict[str, set[str]] = {}
    for rid, ups in deps.items():
        for up in ups:
            dependents.setdefault(up, set()).add(rid)

    need = {c.result.id for c in classifications if c.verdict is not Verdict.VALID}

    # transitive closure over the result graph
    frontier = set(need)
    while frontier:
        nxt: set[str] = set()
        for rid in frontier:
            for down in dependents.get(rid, set()):
                if down not in need:
                    nxt.add(down)
        need |= nxt
        frontier = nxt

    return sorted(need)


def propagate_results(results: list[Result], changed_results: set[str],
                      result_deps: dict[str, set[str]] | None = None) -> set[str]:
    """Convenience: expand a set of changed result ids to include downstream ones."""
    deps = {}
    for r in results:
        if r.depends_on_results:
            deps[r.id] = set(r.depends_on_results)
    for rid, ups in (result_deps or {}).items():
        deps.setdefault(rid, set()).update(ups)
    dependents: dict[str, set[str]] = {}
    for rid, ups in deps.items():
        for up in ups:
            dependents.setdefault(up, set()).add(rid)
    need = set(changed_results)
    frontier = set(changed_results)
    while frontier:
        nxt = set()
        for rid in frontier:
            for down in dependents.get(rid, set()):
                if down not in need:
                    nxt.add(down)
        need |= nxt
        frontier = nxt
    return need
