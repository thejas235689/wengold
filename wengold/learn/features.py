"""Feature vectors for the learners.

Everything the three methods need is derived from the same place — the graph, the
results, and the change set — so a model trained on one project has the same
columns as a model applied to another.

Two kinds of feature are deliberately kept apart:

* **block features** describe a module on its own: how much it depends on, how
  much depends on it, whether it resolved, how deep it sits.
* **result features** describe a result *relative to a change*: how far the
  nearest change is, how many changes reach it, how large its closure is.

The second kind is what a failure model needs, because whether a result fails
depends on what changed, not only on what the result is.
"""
from __future__ import annotations

from ..graph.model import EdgeKind

__all__ = ["BLOCK_KEYS", "RESULT_KEYS", "block_features", "result_features",
           "vector"]

BLOCK_KEYS = ["fan_in", "fan_out", "ancestors", "descendants", "depth",
              "unresolved", "edges_in", "edges_out", "is_leaf", "is_root"]

RESULT_KEYS = ["closure", "changes_in_closure", "nearest_change",
               "frac_changed", "unresolved_in_closure", "target_fan_in",
               "target_fan_out", "target_depth", "is_integration", "n_deps"]


def block_features(graph, node: str) -> dict[str, float]:
    """A block's position in the graph."""
    anc = graph.ancestors(node)
    des = graph.descendants(node)
    out_e = graph.out_edges(node)
    in_e = graph.in_edges(node)
    return {
        "fan_in": float(len(in_e)),
        "fan_out": float(len(out_e)),
        "ancestors": float(len(anc)),
        "descendants": float(len(des)),
        "depth": float(_depth(graph, node)),
        "unresolved": 1.0 if node in graph.unresolved_nodes() else 0.0,
        # compare against the enum, not its text: `str(EdgeKind.INSTANTIATES)` is
        # "EdgeKind.INSTANTIATES", so an endswith("instantiat") test never matches
        # and these counts were silently always zero
        "edges_in": float(sum(1 for e in in_e if e.kind is EdgeKind.INSTANTIATES)),
        "edges_out": float(sum(1 for e in out_e if e.kind is EdgeKind.INSTANTIATES)),
        "is_leaf": 1.0 if not anc else 0.0,
        "is_root": 1.0 if not des else 0.0,
    }


def _depth(graph, node: str, limit: int = 64) -> int:
    """How many levels of hierarchy sit below this block.

    Walks *in_edges* towards `src`: an INSTANTIATES edge runs child -> owner, so
    the blocks a node instantiates are on its in-edges. Walking out_edges instead
    gave zero for every block in the design.
    """
    seen: set[str] = set()
    frontier = [node]
    depth = 0
    while frontier and depth < limit:
        nxt = []
        for n in frontier:
            if n in seen:
                continue
            seen.add(n)
            nxt += [e.src for e in graph.in_edges(n)
                    if e.kind is EdgeKind.INSTANTIATES]
        if not nxt:
            break
        frontier = nxt
        depth += 1
    return depth


def result_features(graph, result, changed: set[str]) -> dict[str, float]:
    """A result's exposure to a change set."""
    deps = set(getattr(result, "depends_on", []) or [])
    closure = set(deps)
    for d in deps:
        closure |= graph.ancestors(d)
    hits = changed & closure
    target = sorted(deps)[0] if deps else ""
    base = block_features(graph, target) if target in graph.nodes else {}
    # no change reaching the result is the *furthest* case, not the nearest: a
    # default of 0 read as "a change is right here" and made the feature lie.
    dist = float(_DIST_LIMIT)
    if hits and target:
        dist = float(min(_distance(graph, c, target) for c in hits))
    return {
        "closure": float(len(closure)),
        "changes_in_closure": float(len(hits)),
        "nearest_change": dist,
        "frac_changed": len(hits) / len(closure) if closure else 0.0,
        "unresolved_in_closure": float(len(closure & graph.unresolved_nodes())),
        "target_fan_in": base.get("fan_in", 0.0),
        "target_fan_out": base.get("fan_out", 0.0),
        "target_depth": base.get("depth", 0.0),
        "is_integration": 1.0 if len(deps) != 1 else 0.0,
        "n_deps": float(len(deps)),
    }


_DIST_LIMIT = 32


def _distance(graph, src: str, dst: str, limit: int = _DIST_LIMIT) -> int:
    """Shortest path from a changed node up to the result's target."""
    if src == dst:
        return 0
    seen = {src}
    frontier = [(src, 0)]
    while frontier:
        node, d = frontier.pop(0)
        if d >= limit:
            continue
        for e in graph.out_edges(node):
            if e.kind is not EdgeKind.INSTANTIATES:
                continue
            if e.dst == dst:
                return d + 1
            if e.dst not in seen:
                seen.add(e.dst)
                frontier.append((e.dst, d + 1))
    return limit


def vector(feats: dict[str, float], keys: list[str]) -> list[float]:
    """A fixed-order vector, so a model's columns are stable across projects."""
    return [float(feats.get(k, 0.0)) for k in keys]


def dataset(graph, results, changed: set[str], keys: list[str] | None = None):
    """(X, ids) for a set of results against one change set."""
    keys = keys or RESULT_KEYS
    X, ids = [], []
    for r in results:
        X.append(vector(result_features(graph, r, changed), keys))
        ids.append(getattr(r, "id", str(r)))
    return X, ids


def normalise(X: list[list[float]]) -> tuple[list[list[float]], list[float],
                                             list[float]]:
    """Zero-mean, unit-variance columns; returns (X, mean, std) for reuse."""
    if not X:
        return [], [], []
    n, d = len(X), len(X[0])
    mean = [sum(row[j] for row in X) / n for j in range(d)]
    std = []
    for j in range(d):
        var = sum((row[j] - mean[j]) ** 2 for row in X) / n
        std.append(var ** 0.5 or 1.0)
    return [[(row[j] - mean[j]) / std[j] for j in range(d)] for row in X], mean, std
