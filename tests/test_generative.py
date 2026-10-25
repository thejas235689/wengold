"""Generative stimulus models, the ops they need, and the yardstick.

The tests that matter are the ones about the *measurement*, not the models: the
ground truth must be the engine's own reachable set, and the corpus must genuinely
never succeed. If either is wrong, every number the benchmark prints is fiction.
"""
import numpy as np
import pytest

from wengold.learn import autograd as A
from wengold.learn.coverage import (PASSCODE, build_corpus, reachable_states,
                                    states_visited)
from wengold.learn.generative import GAN, VAE, Diffusion, flatten, unflatten


def _T(rows, cols, seed=0):
    rng = np.random.default_rng(seed)
    return A.Tensor(rng.normal(0, 1, (rows, cols)), True)


def _gradcheck(build, tensors, tol=1e-4):
    def f():
        for t in tensors:
            t.zero_grad()
        return float(build().data.sum())

    for t in tensors:
        t.zero_grad()
    A.backward(build())
    analytic = [t.grad.copy() for t in tensors]
    eps = 1e-6
    worst = 0.0
    for t in tensors:
        for i in range(t.data.shape[0]):
            for j in range(t.data.shape[1]):
                old = t.data[i, j]
                t.data[i, j] = old + eps
                fp = f()
                t.data[i, j] = old - eps
                fm = f()
                t.data[i, j] = old
                worst = max(worst, abs(analytic[tensors.index(t)][i, j]
                                       - (fp - fm) / (2 * eps)))
    assert worst < tol, f"gradient mismatch {worst:.2e}"


# ---- the ops the generative models need ------------------------------------
def test_binary_cross_entropy_gradients():
    x = _T(4, 6, 1)
    targets = np.random.default_rng(2).integers(0, 2, (4, 6)).astype(float)
    _gradcheck(lambda: A.binary_cross_entropy(x, targets), [x])


def test_gaussian_kl_gradients():
    mu, lv = _T(3, 5, 3), _T(3, 5, 4)
    _gradcheck(lambda: A.gaussian_kl(mu, lv), [mu, lv])


def test_reparameterise_gradients():
    """The VAE's sampling step. Built from elementwise ops it has no path back to
    logvar, and the KL term trains alone — which is what a first version did."""
    mu, lv = _T(3, 4, 5), _T(3, 4, 6)
    eps = np.random.default_rng(7).normal(0, 1, (3, 4))
    _gradcheck(lambda: A.reparameterise(mu, lv, eps), [mu, lv])


def test_concat_and_split_cols_gradients():
    a, b = _T(3, 4, 8), _T(3, 2, 9)
    _gradcheck(lambda: A.concat_cols([a, b]), [a, b])
    x = _T(3, 7, 10)
    for i in range(3):
        _gradcheck(lambda k=i: A.split_cols(x, [2, 3, 2])[k], [x])


# ---- bit packing -----------------------------------------------------------
def test_flatten_and_unflatten_round_trip():
    seqs = [[5, 7, 9], [0, 15, 3]]
    rows = flatten(seqs, steps=3, width=4)
    assert rows.shape == (2, 12)
    assert unflatten(rows, steps=3, width=4) == seqs


# ---- the models ------------------------------------------------------------
@pytest.mark.parametrize("cls", [VAE, GAN, Diffusion])
def test_each_model_fits_and_samples(cls):
    rng = np.random.default_rng(0)
    corpus = [[int(rng.integers(0, 16)) for _ in range(6)] for _ in range(24)]
    model = cls(steps=6, width=4, seed=0)
    model.fit(corpus, epochs=4)
    out = model.sample(5)
    assert len(out) == 5 and all(len(s) == 6 for s in out)
    assert all(0 <= v < 16 for s in out for v in s), "samples must be 4-bit values"


@pytest.mark.parametrize("cls", [VAE, GAN, Diffusion])
def test_training_reduces_the_loss(cls):
    rng = np.random.default_rng(1)
    corpus = [[int(rng.integers(0, 16)) for _ in range(6)] for _ in range(24)]
    model = cls(steps=6, width=4, seed=0)
    hist = model.fit(corpus, epochs=25)
    values = hist if isinstance(hist, list) else hist["d"]
    assert values[-1] < values[0], f"{cls.__name__} loss did not fall"


# ---- the yardstick ---------------------------------------------------------
def test_the_reachable_set_is_computed_by_the_engine():
    """Ground truth comes from the parsed transition function, not from a model."""
    states = reachable_states()
    assert len(states) == 7
    assert any(dict(s).get("stage") == 3 for s in states), "stage 3 must be reachable"


def test_the_corpus_never_completes_the_chain():
    """The whole experiment depends on this: if the corpus unlocks, the models are
    being asked nothing."""
    corpus = build_corpus(200, seed=0)
    assert not any(9 in seq for seq in corpus), "the completing symbol must be absent"
    model_unlocks = [s for s in corpus if dict(
        max(states_visited([s]), key=lambda k: dict(k).get("stage", 0))).get("stage") == 3]
    assert not model_unlocks, "a corpus sequence reached stage 3"


def test_the_corpus_reaches_the_middle_of_the_chain():
    corpus = build_corpus(50, seed=0)
    visited = states_visited(corpus)
    stages = {dict(s).get("stage") for s in visited}
    assert 2 in stages, "the corpus is meant to be a partial success"


def test_states_visited_holds_reset_high():
    """A reset mid-sequence would hide the behaviour being measured."""
    assert states_visited([[5, 7, 9]]) != set()
    deep = states_visited([[5, 7, 9]])
    assert any(dict(s).get("stage") == 3 for s in deep)
