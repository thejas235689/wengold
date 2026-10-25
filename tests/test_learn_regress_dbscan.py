"""Regression and DBSCAN.

The tests that matter here are the ones that distinguish the methods: a linear
target should be recovered by linear regression, a non-linear one should not, and
DBSCAN must leave points unassigned where k-means would not.
"""
import pytest

from wengold.graph.builder import GraphBuilder
from wengold.learn.dbscan import auto_eps, cluster_blocks_dbscan, dbscan
from wengold.learn.regression import (LinearRegression, build_dataset, evaluate,
                                      mean_baseline, score)
from wengold.learn.trees import (DecisionTreeRegressor, GradientBoostingRegressor,
                                 RandomForestRegressor)

needs_slang = pytest.mark.skipif(
    not __import__("wengold.graph.slang_backend", fromlist=["available"]).available(),
    reason="pyslang not installed")


# ---- linear regression -----------------------------------------------------
def test_linear_regression_recovers_a_linear_relation():
    """y = 3x1 - 2x2 + 5. Not bit-exact: the solver is ridge-regularised, which
    shrinks the coefficients by ~1e-5 — a deliberate trade for stability when
    columns are collinear, so the test asserts accuracy, not exactness."""
    X = [[float(i), float(i % 3)] for i in range(40)]
    y = [3 * a - 2 * b + 5 for a, b in X]
    m = LinearRegression().fit(X, y)
    pred = m.predict([[7.0, 1.0], [2.0, 2.0]])
    assert pred[0] == pytest.approx(3 * 7 - 2 * 1 + 5, abs=1e-3)
    assert pred[1] == pytest.approx(3 * 2 - 2 * 2 + 5, abs=1e-3)
    assert score(m.predict(X), y).r2 > 0.999


def test_linear_regression_cannot_fit_a_non_linear_target():
    """x^2 is not linear in x, and the honest result is a poor R2."""
    X = [[float(i)] for i in range(40)]
    y = [float(i * i) for i in range(40)]
    m = LinearRegression().fit(X, y)
    assert score(m.predict(X), y).r2 < 0.95


# ---- trees -----------------------------------------------------------------
def test_a_tree_fits_a_step_function():
    X = [[float(i)] for i in range(20)]
    y = [0.0 if i < 10 else 10.0 for i in range(20)]
    m = DecisionTreeRegressor(max_depth=2).fit(X, y)
    assert m.predict([[2.0]])[0] < 1.0
    assert m.predict([[17.0]])[0] > 9.0


def test_a_forest_beats_the_mean_on_a_non_linear_target():
    """A non-linear target with an interaction: x0*x1 when x0 > 5, else x1."""
    X = [[float(i), float((i * 7) % 5)] for i in range(120)]
    y = [a * b if a > 5 else b for a, b in X]
    forest = RandomForestRegressor(n_trees=25, max_depth=6, seed=0).fit(X, y)
    model_r2 = score(forest.predict(X), y).r2
    base = mean_baseline(y, y)
    assert model_r2 > 0.5 > base.r2


def test_boosting_beats_linear_regression_on_a_non_linear_target():
    """This is the comparison that matters: on a target that is not linear, the
    boosted trees win and the linear model does not."""
    X = [[float(i % 13), float((i * 7) % 11)] for i in range(160)]
    y = [a * b + (a if a > 6 else 0.0) for a, b in X]
    lin = LinearRegression().fit(X, y)
    boost = GradientBoostingRegressor(n_estimators=40, max_depth=3, seed=0).fit(X, y)
    assert score(boost.predict(X), y).r2 > score(lin.predict(X), y).r2


def test_a_forest_is_an_ensemble_not_one_tree():
    X = [[float(i)] for i in range(30)]
    y = [float(i % 4) for i in range(30)]
    f = RandomForestRegressor(n_trees=8, seed=0).fit(X, y)
    assert len(f.trees) == 8
    assert all(t.root is not None for t in f.trees)


# ---- the task --------------------------------------------------------------
@needs_slang
def test_the_label_is_the_kernels_own_count(tmp_path):
    """The label is exact, so it must agree with the kernel on the same change."""
    for rel, text in (("leaf.sv", "module leaf; endmodule\n"),
                      ("mid.sv", "module mid; leaf u (); endmodule\n"),
                      ("top.sv", "module top; mid u (); endmodule\n")):
        (tmp_path / rel).write_text(text)
    from wengold.kernel.validity import Result, classify_all
    files = {str(p): p.read_text() for p in tmp_path.rglob("*.sv")}
    g = GraphBuilder().build_from_files(files, include_dirs=[str(tmp_path)],
                                        backend="slang")
    suite = [Result(f"unit_{m}", "sim", depends_on={m})
             for m in ("leaf", "mid", "top")]
    X, y, blocks = build_dataset(g, suite)
    assert blocks == ["leaf", "mid", "top"]
    assert len(X) == len(y) == 3 and len(X[0]) == 10
    for i, b in enumerate(blocks):
        exact = sum(1 for c in classify_all(g, suite, {b})
                    if c.verdict.value in ("invalidated", "unknown"))
        assert y[i] == float(exact)
    # a change to leaf reaches leaf, mid and top; to top, only top
    assert y[blocks.index("leaf")] > y[blocks.index("top")]


def test_an_unknown_target_is_rejected():
    with pytest.raises(ValueError):
        build_dataset(None, [], target="nonsense")


def test_the_mean_baseline_has_a_non_positive_r2():
    y = [1.0, 2.0, 3.0, 9.0]
    assert mean_baseline(y, y).r2 <= 0.0


# ---- DBSCAN ----------------------------------------------------------------
def _two_blobs_and_an_outlier():
    pts = [[0.0, 0.0], [0.1, 0.0], [0.0, 0.1], [0.1, 0.1],
           [5.0, 5.0], [5.1, 5.0], [5.0, 5.1], [5.1, 5.1],
           [40.0, 40.0]]
    return pts


def test_dbscan_finds_the_blobs_and_leaves_the_outlier_unassigned():
    res = dbscan(_two_blobs_and_an_outlier(), eps=0.5, min_pts=3)
    assert res.clusters == 2
    assert len(res.noise) == 1
    assert res.labels[8] == -1              # the far point is not forced into a group


def test_kmeans_would_have_forced_it_into_a_cluster():
    """The contrast that justifies DBSCAN: k-means assigns every point."""
    from wengold.learn.unsupervised import kmeans
    c = kmeans(_two_blobs_and_an_outlier(), 2, seed=0)
    assert all(lab in (0, 1) for lab in c.labels)
    assert -1 not in c.labels


def test_auto_eps_is_positive_and_grows_with_spread():
    tight = [[float(i), 0.0] for i in range(20)]
    wide = [[float(i) * 10, 0.0] for i in range(20)]
    assert auto_eps(tight) > 0
    assert auto_eps(wide) > auto_eps(tight)


@needs_slang
def test_cluster_blocks_dbscan_names_outliers(tmp_path):
    (tmp_path / "leaf.sv").write_text("module leaf; endmodule\n")
    (tmp_path / "a.sv").write_text("module a; leaf u (); endmodule\n")
    (tmp_path / "b.sv").write_text("module b; leaf u (); endmodule\n")
    files = {str(p): p.read_text() for p in tmp_path.rglob("*.sv")}
    g = GraphBuilder().build_from_files(files, include_dirs=[str(tmp_path)],
                                        backend="slang")
    res, blocks, outliers = cluster_blocks_dbscan(g, min_pts=2)
    assert sorted(blocks) == ["a", "b", "leaf"]
    assert all(o in blocks for o in outliers)
    assert len(res.labels) == len(blocks)
