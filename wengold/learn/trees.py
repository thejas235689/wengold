"""Tree-based regressors: CART, a random forest, and gradient boosting.

These are the three the list calls for — Random Forest, and the idea behind
XGBoost / LightGBM — written out rather than imported, because the datasets here
are a few hundred rows and a dependency would cost more than the model earns.

What each one is, honestly:

* `DecisionTreeRegressor` — CART: pick the split that reduces variance most, and
  recurse. The base of the other two.
* `RandomForestRegressor` — bagging plus feature subsampling. Averages many deep,
  decorrelated trees, which is what makes it good at non-linear data where
  features interact.
* `GradientBoostingRegressor` — boosting: fit each tree to what the last ensemble
  got wrong. This is the mechanism XGBoost and LightGBM are built on. It is
  **not** those libraries: no second-order gradients, no histogram binning, no
  regularised leaf weights. Calling it XGBoost would be a lie; calling it
  gradient boosting is accurate.

All three take and return plain floats, so they can be scored against linear
regression on the same data with the same split.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

__all__ = ["DecisionTreeRegressor", "RandomForestRegressor",
           "GradientBoostingRegressor"]


@dataclass
class _Node:
    value: float                       # prediction at a leaf
    feature: int = -1
    threshold: float = 0.0
    left: "_Node | None" = None
    right: "_Node | None" = None

    @property
    def leaf(self) -> bool:
        return self.feature < 0


def _variance(y: list[float]) -> float:
    if not y:
        return 0.0
    m = sum(y) / len(y)
    return sum((v - m) ** 2 for v in y) / len(y)


class DecisionTreeRegressor:
    """CART regression tree."""

    def __init__(self, max_depth: int = 4, min_samples_leaf: int = 2,
                 max_features: int | None = None, max_thresholds: int = 24,
                 seed: int = 0):
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.max_features = max_features
        self.max_thresholds = max_thresholds
        self.rng = random.Random(seed)
        self.root: _Node | None = None
        self.n_features = 0

    def fit(self, X: list[list[float]], y: list[float]) -> "DecisionTreeRegressor":
        self.n_features = len(X[0]) if X else 0
        self.root = self._build(X, y, depth=0)
        return self

    def _build(self, X, y, depth) -> _Node:
        node = _Node(value=sum(y) / len(y) if y else 0.0)
        if (depth >= self.max_depth or len(y) < 2 * self.min_samples_leaf
                or _variance(y) <= 1e-12):
            return node
        best = self._best_split(X, y)
        if best is None:
            return node
        feat, thr = best
        left_idx = [i for i, row in enumerate(X) if row[feat] <= thr]
        right_idx = [i for i, row in enumerate(X) if row[feat] > thr]
        if not left_idx or not right_idx:
            return node
        node.feature, node.threshold = feat, thr
        node.left = self._build([X[i] for i in left_idx], [y[i] for i in left_idx],
                                depth + 1)
        node.right = self._build([X[i] for i in right_idx], [y[i] for i in right_idx],
                                 depth + 1)
        return node

    def _candidate_features(self) -> list[int]:
        feats = list(range(self.n_features))
        if self.max_features and self.max_features < len(feats):
            feats = self.rng.sample(feats, self.max_features)
        return feats

    def _best_split(self, X, y) -> tuple[int, float] | None:
        base = _variance(y) * len(y)
        best_gain, best = 0.0, None
        for feat in self._candidate_features():
            pairs = sorted({row[feat] for row in X})
            if len(pairs) < 2:
                continue
            # cap the thresholds so a feature with hundreds of distinct values
            # does not dominate the fit time
            if len(pairs) > self.max_thresholds:
                step = len(pairs) / self.max_thresholds
                pairs = [pairs[int(i * step)] for i in range(self.max_thresholds)]
            for a, b in zip(pairs, pairs[1:]):
                thr = (a + b) / 2
                ly = [y[i] for i, row in enumerate(X) if row[feat] <= thr]
                ry = [y[i] for i, row in enumerate(X) if row[feat] > thr]
                if (len(ly) < self.min_samples_leaf
                        or len(ry) < self.min_samples_leaf):
                    continue
                gain = base - (_variance(ly) * len(ly) + _variance(ry) * len(ry))
                if gain > best_gain:
                    best_gain, best = gain, (feat, thr)
        return best

    def _one(self, row: list[float]) -> float:
        node = self.root
        while node is not None and not node.leaf:
            node = node.left if row[node.feature] <= node.threshold else node.right
        return node.value if node is not None else 0.0

    def predict(self, X: list[list[float]]) -> list[float]:
        return [self._one(row) for row in X]

    def feature_importance(self) -> list[float]:
        imp = [0.0] * self.n_features

        def walk(n: _Node):
            if n is None or n.leaf:
                return
            imp[n.feature] += 1.0
            walk(n.left)
            walk(n.right)

        walk(self.root)
        total = sum(imp) or 1.0
        return [v / total for v in imp]


class RandomForestRegressor:
    """Bagged trees with feature subsampling."""

    def __init__(self, n_trees: int = 30, max_depth: int = 6,
                 min_samples_leaf: int = 2, max_features: int | None = None,
                 seed: int = 0):
        self.n_trees = n_trees
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.max_features = max_features
        self.seed = seed
        self.trees: list[DecisionTreeRegressor] = []
        self.n_features = 0

    def fit(self, X, y) -> "RandomForestRegressor":
        self.n_features = len(X[0]) if X else 0
        rng = random.Random(self.seed)
        k = self.max_features or max(1, int(math.sqrt(self.n_features)))
        self.trees = []
        for t in range(self.n_trees):
            idx = [rng.randrange(len(X)) for _ in range(len(X))]
            tree = DecisionTreeRegressor(self.max_depth, self.min_samples_leaf,
                                         max_features=k, seed=self.seed + t * 13)
            tree.fit([X[i] for i in idx], [y[i] for i in idx])
            self.trees.append(tree)
        return self

    def predict(self, X) -> list[float]:
        if not self.trees:
            return [0.0] * len(X)
        out = []
        for row in X:
            out.append(sum(t._one(row) for t in self.trees) / len(self.trees))
        return out

    def feature_importance(self) -> list[float]:
        if not self.trees:
            return [0.0] * self.n_features
        acc = [0.0] * self.n_features
        for t in self.trees:
            for j, v in enumerate(t.feature_importance()):
                acc[j] += v
        total = sum(acc) or 1.0
        return [v / total for v in acc]


class GradientBoostingRegressor:
    """Boosting on squared loss: each tree is fitted to the residual.

    This is the mechanism behind XGBoost and LightGBM, not those libraries. No
    second-order gradients, no histogram binning, no leaf regularisation.
    """

    def __init__(self, n_estimators: int = 40, learning_rate: float = 0.15,
                 max_depth: int = 3, min_samples_leaf: int = 2, seed: int = 0):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.seed = seed
        self.base = 0.0
        self.trees: list[DecisionTreeRegressor] = []
        self.n_features = 0

    def fit(self, X, y) -> "GradientBoostingRegressor":
        self.n_features = len(X[0]) if X else 0
        self.base = sum(y) / len(y) if y else 0.0
        pred = [self.base] * len(y)
        self.trees = []
        for i in range(self.n_estimators):
            residual = [yi - pi for yi, pi in zip(y, pred)]
            tree = DecisionTreeRegressor(self.max_depth, self.min_samples_leaf,
                                         seed=self.seed + i * 7)
            tree.fit(X, residual)
            upd = tree.predict(X)
            pred = [p + self.learning_rate * u for p, u in zip(pred, upd)]
            self.trees.append(tree)
        return self

    def predict(self, X) -> list[float]:
        out = [self.base] * len(X)
        for tree in self.trees:
            for i, u in enumerate(tree.predict(X)):
                out[i] += self.learning_rate * u
        return out
