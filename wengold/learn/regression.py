"""Regression: predicting a continuous value.

The list this answers to names three regressors — linear regression, a random
forest, and XGBoost/LightGBM — for targets like price, temperature or trend. The
question is what continuous value WENGOLD has, and it has a real one: **how many
results a change puts in doubt**. That number is exact — the kernel computes it —
so it is a proper label, not a proxy, and the task is to estimate it from cheap
structural features without walking the graph.

The honest caveat, stated where it will be read: after the edge-index fix the
kernel walks a real graph in milliseconds, so a surrogate for it earns little
today. What is being demonstrated is that the three methods work on this data and
are scored against a baseline and each other — not that they are needed.

`LinearRegression` is ridge-regularised and solved by Gaussian elimination rather
than gradient descent, because with ten features an exact solve is both faster and
easier to trust.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..graph.model import NodeKind

__all__ = ["LinearRegression", "REG_FEATURES", "build_dataset", "evaluate",
           "mean_baseline", "Metrics"]

REG_FEATURES = ["fan_in", "fan_out", "ancestors", "descendants", "depth",
                "is_leaf", "is_root", "unresolved", "suite_size",
                "descendant_frac"]


@dataclass
class Metrics:
    n: int = 0
    mae: float = 0.0
    rmse: float = 0.0
    r2: float = 0.0

    def render(self) -> str:
        return (f"n={self.n:<4} MAE={self.mae:6.2f}  RMSE={self.rmse:6.2f}  "
                f"R2={self.r2:+.3f}")


class LinearRegression:
    """Ridge regression, solved exactly."""

    def __init__(self, l2: float = 1e-6):
        self.l2 = l2
        self.w: list[float] = []
        self.b = 0.0
        self.mean: list[float] = []
        self.std: list[float] = []

    def _scale_fit(self, X):
        n, d = len(X), len(X[0])
        self.mean = [sum(r[j] for r in X) / n for j in range(d)]
        self.std = []
        for j in range(d):
            var = sum((r[j] - self.mean[j]) ** 2 for r in X) / n
            self.std.append(math.sqrt(var) or 1.0)
        return self._scale(X)

    def _scale(self, X):
        return [[(r[j] - self.mean[j]) / self.std[j] for j in range(len(self.mean))]
                for r in X]

    def fit(self, X, y) -> "LinearRegression":
        Xs = self._scale_fit(X)
        n, d = len(Xs), len(Xs[0])
        self.b = sum(y) / n
        yc = [yi - self.b for yi in y]
        # normal equations with a small ridge term, solved by elimination
        A = [[sum(Xs[i][a] * Xs[i][b] for i in range(n)) + (self.l2 * n if a == b else 0.0)
              for b in range(d)] + [sum(Xs[i][a] * yc[i] for i in range(n))]
             for a in range(d)]
        self.w = self._solve(A, d)
        return self

    @staticmethod
    def _solve(A: list[list[float]], d: int) -> list[float]:
        for col in range(d):
            piv = max(range(col, d), key=lambda r: abs(A[r][col]))
            if abs(A[piv][col]) < 1e-12:
                continue
            A[col], A[piv] = A[piv], A[col]
            for r in range(d):
                if r == col:
                    continue
                factor = A[r][col] / A[col][col]
                for c in range(col, d + 1):
                    A[r][c] -= factor * A[col][c]
        return [A[i][d] / A[i][i] if abs(A[i][i]) > 1e-12 else 0.0 for i in range(d)]

    def predict(self, X) -> list[float]:
        out = []
        for row in self._scale(X):
            out.append(self.b + sum(w * v for w, v in zip(self.w, row)))
        return out


# ---- the task --------------------------------------------------------------
def build_dataset(graph, results, max_blocks: int = 120,
                  target: str = "doubtful"):
    """One row per block, as if that block were the change.

    Features are structural and cheap. Two targets, and the difference matters:

    * ``doubtful`` — results the change puts in doubt at all. This turns out to be
      almost exactly linear in the features (the closure size determines it), so
      linear regression recovers it and the trees do worse. Honest, and a fair
      answer to "which algorithm": for a linear target, the linear one.
    * ``unknown`` — results that become UNKNOWN, which depends on *which* of the
      descendants carry an unresolved dependency. That is not linear in anything,
      and it is the target worth having a non-linear model for.
    """
    from ..kernel.validity import classify_all

    if target not in ("doubtful", "unknown"):
        raise ValueError(f"unknown target {target!r}")
    blocks = sorted(n for n, d in graph.nodes.items() if d.kind is NodeKind.RTL)
    if len(blocks) > max_blocks:
        blocks = blocks[:max_blocks]
    X, y = [], []
    for b in blocks:
        verdicts = classify_all(graph, results, {b})
        if target == "unknown":
            doubtful = sum(1 for c in verdicts if c.verdict.value == "unknown")
        else:
            doubtful = sum(1 for c in verdicts
                           if c.verdict.value in ("invalidated", "unknown"))
        anc = graph.rtl_ancestors(b)
        des = graph.rtl_descendants(b)
        X.append([
            float(len(graph.in_edges(b))),
            float(len(graph.out_edges(b))),
            float(len(anc)),
            float(len(des)),
            float(_depth(graph, b)),
            1.0 if not anc else 0.0,
            1.0 if not des else 0.0,
            1.0 if b in graph.unresolved_nodes() else 0.0,
            float(len(results)),
            len(des) / max(len(results), 1),
        ])
        y.append(float(doubtful))
    return X, y, blocks


def _depth(graph, node: str, limit: int = 64) -> int:
    seen, frontier, depth = set(), [node], 0
    while frontier and depth < limit:
        nxt = []
        for n in frontier:
            if n in seen:
                continue
            seen.add(n)
            nxt += [e.src for e in graph.in_edges(n) if e.kind.value == "instantiates"]
        if not nxt:
            break
        frontier, depth = nxt, depth + 1
    return depth


def mean_baseline(y_train: list[float], y_test: list[float]) -> Metrics:
    m = sum(y_train) / len(y_train) if y_train else 0.0
    return score([m] * len(y_test), y_test)


def score(pred: list[float], actual: list[float]) -> Metrics:
    n = len(actual)
    if n == 0:
        return Metrics()
    mae = sum(abs(p - a) for p, a in zip(pred, actual)) / n
    rmse = math.sqrt(sum((p - a) ** 2 for p, a in zip(pred, actual)) / n)
    mean = sum(actual) / n
    ss_tot = sum((a - mean) ** 2 for a in actual)
    ss_res = sum((p - a) ** 2 for p, a in zip(pred, actual))
    return Metrics(n, mae, rmse, 1 - ss_res / ss_tot if ss_tot > 0 else 0.0)


def evaluate(model_factory, X, y, test_frac: float = 0.3, seed: int = 0):
    """Train/test split over blocks; returns (model, train, test, baseline)."""
    import random
    idx = list(range(len(X)))
    random.Random(seed).shuffle(idx)
    cut = max(1, int(len(idx) * (1 - test_frac)))
    tr, te = idx[:cut], idx[cut:]
    if not te:
        tr = te = idx
    model = model_factory().fit([X[i] for i in tr], [y[i] for i in tr])
    return (model,
            score(model.predict([X[i] for i in tr]), [y[i] for i in tr]),
            score(model.predict([X[i] for i in te]), [y[i] for i in te]),
            mean_baseline([y[i] for i in tr], [y[i] for i in te]))
