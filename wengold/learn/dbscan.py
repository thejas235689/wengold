"""DBSCAN: clusters of arbitrary shape, and the outliers.

k-means splits the data into k groups whether or not the data has k groups in it,
and every point lands in a cluster. DBSCAN does the opposite: it grows clusters
from dense regions, finds whatever shapes are there, and **leaves a point
unassigned when it is not near enough to anything** — which is the property that
makes it worth having here.

That property has a direct use in WENGOLD. A block whose dependency signature
resembles nothing else in the design is worth a look: it is either genuinely
special or a modelling mistake, and either way it is the one you have not thought
about. `outliers()` names them. k-means cannot do this — it would place every one
of them in some cluster and report nothing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..graph.model import NodeKind
from .features import BLOCK_KEYS, block_features, normalise, vector

__all__ = ["dbscan", "auto_eps", "cluster_blocks_dbscan", "DbscanResult"]

NOISE = -1


@dataclass
class DbscanResult:
    labels: list[int]
    eps: float
    min_pts: int
    clusters: int = 0
    noise: list[int] = field(default_factory=list)


def _dist(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def auto_eps(X: list[list[float]], min_pts: int = 3,
             percentile: float = 0.9) -> float:
    """The k-distance rule, at the 90th percentile rather than the median.

    The paper's rule is the median, and on real designs it is far too tight: on
    neorv32 it called 34 of 86 blocks (40%) outliers and on cv32e40p 65 of 154
    (42%) — a signal that names two fifths of the design is not a signal. The
    measured trade-off, blocks with a dependency signature unlike any other:

    =========  =========  ===========
    percentile neorv32    cv32e40p
    =========  =========  ===========
    50th       34 (40%)   65 (42%)
    75th       17 (20%)   22 (14%)
    **90th**   **8 (9%)** **7 (5%)**
    100th       0 (0%)     0 (0%)  — one cluster, everything merges
    =========  =========  ===========

    So 90th is the default and `--eps` overrides it, because the honest answer is
    that this parameter decides the result.
    """
    if len(X) < min_pts + 1:
        return 1.0
    kth = []
    for i, x in enumerate(X):
        d = sorted(_dist(x, y) for j, y in enumerate(X) if j != i)
        kth.append(d[min_pts - 1])
    kth.sort()
    idx = min(int(len(kth) * percentile), len(kth) - 1)
    return kth[idx] or 1.0


def dbscan(X: list[list[float]], eps: float | None = None,
           min_pts: int = 3) -> DbscanResult:
    """Density-based clustering. Returns labels, with NOISE (-1) for outliers."""
    n = len(X)
    if n == 0:
        return DbscanResult([], eps or 1.0, min_pts)
    eps = auto_eps(X, min_pts) if eps is None else eps

    neighbours = [[j for j in range(n) if j != i and _dist(X[i], X[j]) <= eps]
                  for i in range(n)]
    labels = [None] * n
    cluster = 0
    for i in range(n):
        if labels[i] is not None:
            continue
        if len(neighbours[i]) + 1 < min_pts:
            labels[i] = NOISE                     # not dense enough to start from
            continue
        labels[i] = cluster
        seeds = list(neighbours[i])
        while seeds:
            j = seeds.pop()
            if labels[j] == NOISE:
                labels[j] = cluster               # a border point joins the cluster
            if labels[j] is not None:
                continue
            labels[j] = cluster
            if len(neighbours[j]) + 1 >= min_pts:
                seeds.extend(neighbours[j])
        cluster += 1
    noise = [i for i, lab in enumerate(labels) if lab == NOISE]
    return DbscanResult([int(l) for l in labels], eps, min_pts, cluster, noise)


def cluster_blocks_dbscan(graph, eps: float | None = None, min_pts: int = 3):
    """Cluster blocks by dependency signature; return (result, blocks, outliers).

    The outliers are the point: blocks whose signature matches nothing else.
    """
    blocks = sorted(n for n, d in graph.nodes.items() if d.kind is NodeKind.RTL)
    if not blocks:
        return DbscanResult([], eps or 1.0, min_pts), [], []
    raw = [vector(block_features(graph, b), BLOCK_KEYS) for b in blocks]
    X, _m, _s = normalise(raw)
    res = dbscan(X, eps, min_pts)
    outliers = [blocks[i] for i in res.noise]
    return res, blocks, outliers
