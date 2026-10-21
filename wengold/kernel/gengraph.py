"""Deterministic generators of random graphs, results and change sets.

Used by the invariant checks and the cross-check against the reference kernel.
Everything is seeded, so a failing case can be reproduced from its seed.
"""
from __future__ import annotations

import random

from ..graph.model import DesignGraph, EdgeKind, Node, NodeKind
from .validity import Result

_NODE_KINDS = [NodeKind.RTL, NodeKind.TEST, NodeKind.ASSERTION, NodeKind.COVERAGE,
               NodeKind.REQUIREMENT, NodeKind.REGMAP, NodeKind.CLOCK, NodeKind.RESET]
_EDGE_KINDS = [EdgeKind.DRIVES, EdgeKind.INSTANTIATES, EdgeKind.VERIFIES,
               EdgeKind.COVERS, EdgeKind.TRACES_TO, EdgeKind.CLOCKED_BY,
               EdgeKind.RESET_BY, EdgeKind.INCLUDES, EdgeKind.IMPORTS,
               EdgeKind.PARAMETERIZES, EdgeKind.CONSTRAINED_BY]


def random_graph(seed: int, n_nodes: int = 8, n_edges: int = 12,
                 unresolved_prob: float = 0.1, approximate_prob: float = 0.05,
                 unknown_edge_prob: float = 0.15) -> DesignGraph:
    rng = random.Random(seed)
    g = DesignGraph()
    ids = [f"n{i}" for i in range(n_nodes)]
    for i in ids:
        g.add_node(Node(i, rng.choice(_NODE_KINDS)))
    for _ in range(n_edges):
        a, b = rng.choice(ids), rng.choice(ids)
        if a == b:
            continue
        kind = EdgeKind.UNKNOWN if rng.random() < unknown_edge_prob else rng.choice(_EDGE_KINDS)
        g.add_edge(a, b, kind)
    for i in ids:
        if rng.random() < unresolved_prob:
            g.mark_unresolved(i, "generated")
    if rng.random() < approximate_prob:
        g.approximate = True
    return g


def random_results(graph: DesignGraph, seed: int, n: int = 5) -> list[Result]:
    rng = random.Random(seed + 1)
    ids = list(graph.nodes)
    results: list[Result] = []
    for i in range(n):
        deps = set(rng.sample(ids, k=min(len(ids), rng.randint(0, 3))))
        results.append(Result(f"r{i}", rng.choice(["sim", "formal", "coverage"]),
                              depends_on=deps))
    # link some results to others, so propagation is exercised
    for r in results:
        if rng.random() < 0.4 and len(results) > 1:
            other = rng.choice([x for x in results if x.id != r.id])
            r.depends_on_results = {other.id}
    return results


def random_changed(graph: DesignGraph, seed: int, k: int = 2) -> set[str]:
    rng = random.Random(seed + 2)
    ids = list(graph.nodes)
    if not ids:
        return set()
    return set(rng.sample(ids, k=min(len(ids), k)))


def clone_graph(graph: DesignGraph) -> DesignGraph:
    g = DesignGraph()
    g.nodes = dict(graph.nodes)
    g.edges = list(graph.edges)
    g.approximate = graph.approximate
    g.notes = list(graph.notes)
    return g
