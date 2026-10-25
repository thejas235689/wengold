"""Invariants for WENGOLD's own invalidation logic.

The kernel decides what evidence may be reused. These invariants state what that
decision must never do, and they are checked against generated graphs, mutation
and an independent reference implementation — so the reasoning is tested, not
just the code paths.

    1. Adding uncertainty must not upgrade an affected result to reusable.
    2. A known changed input must invalidate evidence that consumed it.
    3. Removing graph information must not increase confidence.
    4. Identical recorded inputs must produce deterministic classifications.
    5. Reassessment must propagate when supporting evidence is withdrawn.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..graph.model import DesignGraph, EdgeKind, Node
from . import reference
from .gengraph import clone_graph, random_changed, random_graph, random_results
from .reuse import decide
from .validity import Result, Verdict, classify


@dataclass
class Violation:
    invariant: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.invariant}] {self.detail}"


def rank(verdict) -> int:
    """Reusability rank: 1 if the result may be reused, else 0."""
    v = verdict.value if isinstance(verdict, Verdict) else str(verdict)
    return 1 if v == Verdict.VALID.value else 0


# ---------------------------------------------------------------- 1
def check_adding_uncertainty(graph: DesignGraph, results: list[Result],
                             changed: set[str]) -> list[Violation]:
    out: list[Violation] = []
    for r in results:
        base = rank(classify(graph, r, changed).verdict)
        if base == 0:
            continue
        for c in changed:
            for dep in r.depends_on:
                if c == dep:
                    continue
                g2 = clone_graph(graph)
                g2.add_edge(c, dep, EdgeKind.UNKNOWN)
                after = rank(classify(g2, r, changed).verdict)
                if after > base:
                    out.append(Violation(
                        "adding_uncertainty_never_upgrades",
                        f"result {r.id}: unknown edge {c}->{dep} upgraded "
                        f"{base}->{after}"))
    return out


# ---------------------------------------------------------------- 2
def check_known_change_invalidates(graph: DesignGraph,
                                   results: list[Result]) -> list[Violation]:
    out: list[Violation] = []
    for r in results:
        for dep in r.depends_on:
            v = classify(graph, r, {dep}).verdict
            if v is not Verdict.INVALIDATED:
                out.append(Violation(
                    "known_change_invalidates_consumers",
                    f"result {r.id}: changing its dependency {dep} gave {v.value}"))
    return out


# ---------------------------------------------------------------- 3
def check_removing_information(graph: DesignGraph, results: list[Result],
                               changed: set[str]) -> list[Violation]:
    out: list[Violation] = []
    for r in results:
        base = rank(classify(graph, r, changed).verdict)

        def record(mutation: str, g2: DesignGraph):
            after = rank(classify(g2, r, changed).verdict)
            if after > base:
                out.append(Violation(
                    "removing_information_never_increases_confidence",
                    f"result {r.id}: {mutation} raised rank {base}->{after}"))

        for nid in list(graph.nodes):
            g2 = clone_graph(graph)
            g2.mark_unresolved(nid, "removed-info")
            record(f"mark_unresolved({nid})", g2)

            g3 = clone_graph(graph)
            g3.nodes.pop(nid, None)
            record(f"remove_node({nid})", g3)

        g4 = clone_graph(graph)
        g4.approximate = True
        record("approximate=True", g4)
    return out


def edge_removal_hazard(graph: DesignGraph, results: list[Result],
                        changed: set[str]) -> list[Violation]:
    """Removing an edge can raise confidence; a pipeline that edits the graph must
    detect this and mark the graph incomplete. Reported here so it is visible."""
    out: list[Violation] = []
    for r in results:
        base = rank(classify(graph, r, changed).verdict)
        for i, e in enumerate(graph.edges):
            g2 = clone_graph(graph)
            g2.edges.pop(i)
            # the graph indexes its edges, so a direct mutation of the list must
            # be followed by a rebuild — otherwise the clone still sees the edge
            g2.rebuild_index()
            after = rank(classify(g2, r, changed).verdict)
            if after > base:
                out.append(Violation(
                    "edge_removal_must_be_flagged",
                    f"result {r.id}: removing edge {e.src}->{e.dst} ({e.kind.value}) "
                    f"raised rank {base}->{after}"))
    return out


# ---------------------------------------------------------------- 4
def check_deterministic(graph: DesignGraph, results: list[Result],
                        changed: set[str]) -> list[Violation]:
    out: list[Violation] = []
    for r in results:
        a = classify(graph, r, changed).verdict
        b = classify(graph, r, changed).verdict
        if a is not b:
            out.append(Violation("deterministic", f"result {r.id}: {a} != {b}"))
    return out


# ---------------------------------------------------------------- 5
def check_withdrawal_propagates(graph: DesignGraph, results: list[Result],
                                changed: set[str]) -> list[Violation]:
    out: list[Violation] = []
    by_id = {r.id: r for r in results}
    for r in results:
        for sup in r.depends_on_results:
            if sup not in by_id:
                continue
            d = decide(graph, r, changed, results=results, withdrawn={sup})
            if d.reusable:
                out.append(Violation(
                    "withdrawal_propagates",
                    f"result {r.id} reusable despite withdrawn support {sup}"))
    return out


# ---------------------------------------------------------------- driver
def run_all(graph: DesignGraph, results: list[Result], changed: set[str]) -> list[Violation]:
    out: list[Violation] = []
    out += check_adding_uncertainty(graph, results, changed)
    out += check_known_change_invalidates(graph, results)
    out += check_removing_information(graph, results, changed)
    out += check_deterministic(graph, results, changed)
    out += check_withdrawal_propagates(graph, results, changed)
    for d in reference.cross_check(graph, results, changed):
        out.append(Violation("kernel_matches_reference", str(d)))
    return out


def fuzz(seeds=range(40), n_nodes: int = 8, n_edges: int = 12) -> list[Violation]:
    out: list[Violation] = []
    for s in seeds:
        g = random_graph(s, n_nodes=n_nodes, n_edges=n_edges)
        rs = random_results(g, s)
        ch = random_changed(g, s)
        out += run_all(g, rs, ch)
    return out
