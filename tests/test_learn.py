"""The three learners.

Each test pins the property that makes the method worth having, and — more
importantly — the case where it must *not* claim something: a clustering with no
separation, a model that does not beat the trivial baseline, a policy that
diverges.
"""
import math

import pytest

from wengold.graph.builder import GraphBuilder
from wengold.learn import rl
from wengold.learn.features import (BLOCK_KEYS, RESULT_KEYS, block_features,
                                    result_features, vector)
from wengold.learn.unsupervised import (cluster_blocks, kmeans, near_duplicates,
                                        silhouette)

needs_slang = pytest.mark.skipif(
    not __import__("wengold.graph.slang_backend", fromlist=["available"]).available(),
    reason="pyslang not installed")


def _graph(files: dict[str, str], root):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return GraphBuilder().build_from_files(
        {str(root / r): t for r, t in files.items()},
        include_dirs=[str(root)], backend="slang")


# ---- features --------------------------------------------------------------
@needs_slang
def test_block_features_describe_position(tmp_path):
    g = _graph({"leaf.sv": "module leaf; endmodule\n",
                "mid.sv": "module mid; leaf u (); endmodule\n",
                "top.sv": "module top; mid u (); endmodule\n"}, tmp_path)
    f = block_features(g, "mid")
    assert set(f) == set(BLOCK_KEYS)
    assert f["ancestors"] == 1 and f["descendants"] == 1
    assert block_features(g, "leaf")["is_leaf"] == 1.0
    assert block_features(g, "top")["is_root"] == 1.0


@needs_slang
def test_result_features_track_the_change(tmp_path):
    g = _graph({"leaf.sv": "module leaf; endmodule\n",
                "mid.sv": "module mid; leaf u (); endmodule\n",
                "other.sv": "module other; endmodule\n"}, tmp_path)

    class R:
        id = "unit_mid"
        depends_on = {"mid"}

    # `mid` depends on `leaf`, so a change in either is inside the closure; a
    # change in an unrelated block is not. The distance grows the further the
    # change sits below the result's target.
    near = result_features(g, R(), {"mid"})
    dep = result_features(g, R(), {"leaf"})
    far = result_features(g, R(), {"other"})
    assert near["changes_in_closure"] == 1
    assert dep["changes_in_closure"] == 1
    assert far["changes_in_closure"] == 0
    assert near["nearest_change"] < dep["nearest_change"] < far["nearest_change"]


def test_vector_order_is_fixed():
    f = {k: 1.0 for k in BLOCK_KEYS}
    assert vector(f, BLOCK_KEYS) == [1.0] * len(BLOCK_KEYS)
    assert len(vector({}, RESULT_KEYS)) == len(RESULT_KEYS)


# ---- unsupervised ----------------------------------------------------------
def _blobs():
    """Two well-separated groups and one outlier."""
    return ([[0.0, 0.0], [0.1, 0.0], [0.0, 0.1], [0.1, 0.1],
             [9.0, 9.0], [9.1, 9.0], [9.0, 9.1], [9.1, 9.1],
             [5.0, 5.0]])


def test_kmeans_recovers_well_separated_groups():
    c = kmeans(_blobs(), 2, seed=0)
    a = {c.labels[i] for i in range(4)}
    b = {c.labels[i] for i in range(4, 8)}
    assert len(a) == 1 and len(b) == 1 and a != b     # the blobs are not split
    assert c.silhouette > 0.7


def test_silhouette_is_low_for_an_arbitrary_split():
    """A split that cuts across the data must not look good, or the score is
    telling us nothing."""
    pts = _blobs()
    good = kmeans(pts, 2, seed=0)
    bad = kmeans(pts, 2, seed=0)
    bad.labels = [i % 2 for i in range(len(pts))]      # interleaved: meaningless
    bad_score = silhouette(pts, bad.labels)
    assert bad_score < good.silhouette


def test_silhouette_is_bounded():
    s = kmeans(_blobs(), 2, seed=0).silhouette
    assert -1.0 <= s <= 1.0


def test_kmeans_on_one_point():
    c = kmeans([[1.0, 2.0]], 3)
    assert c.k == 1 and c.labels == [0]


@needs_slang
def test_cluster_blocks_covers_every_block(tmp_path):
    g = _graph({"a.sv": "module a; endmodule\n",
                "b.sv": "module b; endmodule\n",
                "c.sv": "module c; a u1 (); b u2 (); endmodule\n"}, tmp_path)
    clusters, c = cluster_blocks(g)
    members = [m for cl in clusters for m in cl.members]
    assert sorted(members) == ["a", "b", "c"]
    assert 0.0 <= c.silhouette <= 1.0


@needs_slang
def test_near_duplicates_finds_a_genuine_pair(tmp_path):
    """Two blocks instantiating the same leaf are interchangeable for reuse."""
    g = _graph({"leaf.sv": "module leaf; endmodule\n",
                "x.sv": "module x; leaf u (); endmodule\n",
                "y.sv": "module y; leaf u (); endmodule\n"}, tmp_path)
    dups = near_duplicates(g, threshold=0.5, min_neighbours=1)
    pairs = {(a, b) for a, b, _s in dups}
    assert ("x", "y") in pairs or ("y", "x") in pairs


def test_a_single_edge_is_not_enough_by_default(tmp_path):
    """Two blocks that each have one edge pair up whenever they share it. On
    OpenTitan that produced 2,112 pairs, 91% of them resting on one connection,
    so the default requires two."""
    root = tmp_path
    (root / "leaf.sv").write_text("module leaf; endmodule\n")
    (root / "x.sv").write_text("module x; leaf u (); endmodule\n")
    (root / "y.sv").write_text("module y; leaf u (); endmodule\n")
    g = GraphBuilder().build_from_files(
        {str(root / r): (root / r).read_text()
         for r in ("leaf.sv", "x.sv", "y.sv")},
        include_dirs=[str(root)], backend="slang")
    assert near_duplicates(g, threshold=0.5) == []
    assert near_duplicates(g, threshold=0.5, min_neighbours=1) != []


@needs_slang
def test_isolated_blocks_are_not_called_duplicates(tmp_path):
    """Every block with no edges has the same all-zero feature vector, so cosine
    called them identical. Requiring real neighbours is the fix."""
    g = _graph({"p.sv": "module p; endmodule\n",
                "q.sv": "module q; endmodule\n",
                "r.sv": "module r; endmodule\n"}, tmp_path)
    assert near_duplicates(g) == []


# ---- supervised ------------------------------------------------------------
def test_the_dataset_has_both_outcomes():
    from wengold.learn.supervised import build_dataset
    ex = build_dataset(n_designs=10, seed=1)
    labels = {e.label for e in ex}
    assert labels == {0, 1}, "a dataset with one label proves nothing"
    assert len(ex) > 10


def test_the_model_beats_the_trivial_baseline():
    from wengold.learn.supervised import (build_dataset, majority_baseline,
                                          train_eval)
    ex = build_dataset(n_designs=10, seed=2)
    model, _tr, te = train_eval(ex, seed=2)
    assert te.accuracy >= majority_baseline(ex) - 0.05


def test_logistic_regression_learns_a_simple_split():
    from wengold.learn.supervised import LogisticRegression
    X = [[0.0, 0.0], [0.1, 0.2], [0.2, 0.1], [9.0, 9.0], [9.1, 9.2], [9.2, 9.1]]
    y = [0, 0, 0, 1, 1, 1]
    m = LogisticRegression(2).fit(X, y)
    assert m.predict([0.05, 0.05]) == 0
    assert m.predict([9.05, 9.05]) == 1


def test_model_save_load_round_trip(tmp_path):
    from wengold.learn.supervised import LogisticRegression
    m = LogisticRegression(2).fit([[0.0, 0.0], [1.0, 1.0]], [0, 1])
    p = tmp_path / "m.json"
    m.save(p)
    m2 = LogisticRegression.load(p)
    assert m2.predict([1.0, 1.0]) == m.predict([1.0, 1.0])


# ---- reinforcement ---------------------------------------------------------
def _instance():
    # check 0 settles everything and costs 2; the rest are cheap but narrow
    return rl.Instance(name="t", costs=[2.0, 1.0, 1.0],
                       settles=[{0, 1, 2}, {1}, {2}], budget=3.0, all_results=3)


def test_the_environment_charges_what_it_settles():
    env = rl.OrderingEnv(_instance())
    env.reset()
    _s, reward, done = env.step(0)
    assert reward == -2.0
    assert env.done == {0, 1, 2}
    assert done


def test_greedy_settles_everything_when_one_check_covers_it():
    inst = _instance()
    res = rl.evaluate(rl.greedy_ratio, [inst])
    assert res["mean_settled"] == 1.0
    assert res["mean_cost"] == 2.0


def test_training_keeps_the_weights_finite():
    """Unscaled features made Q-learning diverge to NaN. A policy of NaNs is not
    a policy, so this is checked rather than assumed."""
    insts = [_instance() for _ in range(4)]
    agent = rl.train(insts, episodes=200, seed=0)
    assert all(math.isfinite(w) for w in agent.w)
    assert all(abs(w) < 1e9 for w in agent.w)


def test_a_learned_policy_beats_random_on_average():
    insts = [_instance() for _ in range(6)]
    agent = rl.train(insts, episodes=400, seed=0)
    learned = rl.evaluate(None, insts, agent=agent)
    rand = rl.evaluate(rl.random_policy, insts, seed=0)
    assert learned["mean_settled"] >= rand["mean_settled"] - 0.01


def test_the_features_of_a_candidate_are_the_documented_ones():
    env = rl.OrderingEnv(_instance())
    env.reset()
    assert len(env.features(0)) == len(rl.Q_KEYS)
