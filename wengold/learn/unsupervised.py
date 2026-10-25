"""Unsupervised: cluster blocks by their dependency signature.

The kernel treats every block as an individual — it invalidates result by result.
That is correct and it is also unhelpful when a change reaches forty blocks that
all fail for the same reason. Clustering groups blocks by how they sit in the
graph, so one explanation can cover a cluster, and two blocks with the same
signature surface as reuse candidates (why re-verify what is already proven for an
identical dependency profile?).

No labels are needed, which is the point: this works on the first run, before any
history exists. k-means and the silhouette are implemented here rather than
imported, because a dependency would cost more than the model earns.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from ..graph.model import NodeKind
from .features import BLOCK_KEYS, block_features, normalise, vector

__all__ = ["kmeans", "silhouette", "choose_k", "cluster_blocks", "near_duplicates"]


@dataclass
class Clustering:
    k: int
    labels: list[int]
    centroids: list[list[float]]
    inertia: float
    silhouette: float = 0.0


def _sq_dist(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b))


def _dist(a: list[float], b: list[float]) -> float:
    return math.sqrt(_sq_dist(a, b))


def kmeans(X: list[list[float]], k: int, seed: int = 0, iters: int = 100,
           restarts: int = 4) -> Clustering:
    """k-means with restarts; the run with the lowest inertia wins."""
    if not X or k < 1:
        return Clustering(max(k, 0), [], [], 0.0)
    k = min(k, len(X))
    best: Clustering | None = None
    for r in range(restarts):
        rng = random.Random(seed + r * 977)
        cents = [list(X[rng.randrange(len(X))]) for _ in range(k)]
        labels = [0] * len(X)
        for _ in range(iters):
            new_labels = [min(range(k), key=lambda c: _sq_dist(x, cents[c]))
                          for x in X]
            sums = [[0.0] * len(X[0]) for _ in range(k)]
            counts = [0] * k
            for x, lab in zip(X, new_labels):
                counts[lab] += 1
                for j, v in enumerate(x):
                    sums[lab][j] += v
            moved = False
            for c in range(k):
                if counts[c]:
                    new = [s / counts[c] for s in sums[c]]
                    if new != cents[c]:
                        moved = True
                    cents[c] = new
            labels = new_labels
            if not moved:
                break
        inertia = sum(_sq_dist(x, cents[c]) for x, c in zip(X, labels))
        if best is None or inertia < best.inertia - 1e-12:
            best = Clustering(k, labels, cents, inertia)
    assert best is not None
    best.silhouette = silhouette(X, best.labels)
    return best


def silhouette(X: list[list[float]], labels: list[int]) -> float:
    """Mean silhouette. Singleton clusters score 0 and are counted."""
    if not X or len(set(labels)) < 2:
        return 0.0
    groups: dict[int, list[int]] = {}
    for i, lab in enumerate(labels):
        groups.setdefault(lab, []).append(i)
    scores = []
    for i, x in enumerate(X):
        own = [j for j in groups[labels[i]] if j != i]
        if not own:
            scores.append(0.0)
            continue
        a = sum(_dist(x, X[j]) for j in own) / len(own)
        b = min((sum(_dist(x, X[j]) for j in idx) / len(idx))
                for lab, idx in groups.items() if lab != labels[i])
        scores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return sum(scores) / len(scores)


def choose_k(X: list[list[float]], kmax: int = 8, seed: int = 0) -> Clustering:
    """The k with the best silhouette, k in 2..kmax."""
    if len(X) < 3:
        return kmeans(X, 1, seed)
    best, best_score = None, -2.0
    for k in range(2, min(kmax, len(X)) + 1):
        c = kmeans(X, k, seed)
        if c.silhouette > best_score:
            best, best_score = c, c.silhouette
    return best or kmeans(X, 2, seed)


# ---- the project-level use ------------------------------------------------
@dataclass
class BlockCluster:
    label: int
    members: list[str] = field(default_factory=list)
    distinctive: list[str] = field(default_factory=list)
    note: str = ""


def cluster_blocks(graph, k: int | None = None, kmax: int = 8,
                   seed: int = 0) -> tuple[list[BlockCluster], Clustering]:
    """Cluster the RTL blocks by dependency signature."""
    blocks = sorted(n for n, d in graph.nodes.items() if d.kind is NodeKind.RTL)
    if not blocks:
        return [], Clustering(0, [], [], 0.0)
    raw = [vector(block_features(graph, b), BLOCK_KEYS) for b in blocks]
    X, mean, std = normalise(raw)
    c = choose_k(X, kmax, seed) if k is None else kmeans(X, k, seed)

    groups: dict[int, list[str]] = {}
    for b, lab in zip(blocks, c.labels):
        groups.setdefault(lab, []).append(b)

    out = []
    for lab, members in sorted(groups.items()):
        idx = [blocks.index(m) for m in members]
        centroid = c.centroids[lab] if lab < len(c.centroids) else mean
        # which feature is furthest from the global centre: the cluster's character
        dev = sorted(range(len(BLOCK_KEYS)),
                     key=lambda j: -abs(centroid[j]))[:2]
        distinctive = [BLOCK_KEYS[j] for j in dev]
        note = _describe(graph, members)
        out.append(BlockCluster(lab, members, distinctive, note))
    return out, c


def _describe(graph, members: list[str]) -> str:
    """A sentence a human can check, in terms of the graph rather than the vector."""
    leaves = [m for m in members if not graph.ancestors(m)]
    roots = [m for m in members if not graph.descendants(m)]
    unres = [m for m in members if m in graph.unresolved_nodes()]
    bits = []
    if len(members) == 1:
        bits.append("on its own")
    if leaves and len(leaves) == len(members):
        bits.append("all leaves — nothing beneath them")
    elif roots and len(roots) == len(members):
        bits.append("all roots — nothing above them")
    if unres:
        bits.append(f"{len(unres)} unresolved")
    return "; ".join(bits) or "mixed position in the hierarchy"


def neighbour_sets(graph, node: str) -> set[str]:
    """Every block this one is connected to, either way.

    The feature vector is a summary; for "is this the same position in the
    graph" the neighbours themselves are the right thing to compare. Two blocks
    that instantiate the same set of modules and are instantiated by the same set
    are genuinely interchangeable for reuse.
    """
    return (graph.ancestors(node) | graph.descendants(node)
            | {e.dst for e in graph.out_edges(node)}
            | {e.src for e in graph.in_edges(node)}) - {node}


def near_duplicates(graph, threshold: float = 0.8,
                    min_neighbours: int = 2) -> list[tuple[str, str, float]]:
    """Block pairs occupying the same position in the graph.

    Jaccard over the neighbour sets, not cosine over the feature vector: with
    summary features every isolated block has the same all-zero vector, so cosine
    reports unrelated modules as identical. Requiring real neighbours removes
    that degenerate case rather than papering over it.

    `min_neighbours` matters more than it looks. On OpenTitan at a minimum of 1,
    two blocks that each have a single edge pair up whenever they share that
    edge — 2,112 pairs, 91% of them resting on one connection. At 3, 195 pairs
    remain and they are the real ones (`TIEHIx1 ~ TIELOx1`,
    `i3c_dword_collector ~ i3c_dword_splitter`).
    """
    blocks = sorted(n for n, d in graph.nodes.items() if d.kind is NodeKind.RTL)
    sets = {b: neighbour_sets(graph, b) for b in blocks}
    eligible = [b for b in blocks if len(sets[b]) >= min_neighbours]
    out = []
    for i in range(len(eligible)):
        for j in range(i + 1, len(eligible)):
            a, b = sets[eligible[i]], sets[eligible[j]]
            union = a | b
            if not union:
                continue
            s = len(a & b) / len(union)
            if s >= threshold:
                out.append((eligible[i], eligible[j], s))
    return sorted(out, key=lambda t: -t[2])
