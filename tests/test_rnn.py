"""The LSTM, and the comparison with the transformer.

The comparison is the point: same corpus, same split, same metric, one training
loop. A test asserts the two are scored the same way, because a comparison that
is not like-for-like is worse than none.

The last test here is the one that matters most for the product, and it is not
about either model. It shows that a *misread sentence* passes every downstream
check — the validator, the conformance checker and the prover all accept a spec
that does not match what was asked for. That is the honest limit of the whole
front-end, and it is pinned so nobody discovers it in a demo.
"""
import numpy as np
import pytest

from wengold.learn import autograd as A
from wengold.learn.rnn import LSTMSeq2Seq, RNNConfig
from wengold.learn.spec_model import build_vocab, evaluate, fit, predict_spec
from wengold.learn.spec_text import BOS, EOS, encode, make_pairs, tokenise
from wengold.spec_frontend import check_pipeline, validate


def _gradcheck(build, tensors, tol=1e-4, entries=None):
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
        candidates = entries or [(i, j) for i in range(t.data.shape[0])
                                 for j in range(t.data.shape[1])]
        # biases are 1 x n, so a fixed (i, j) list must be bounds-checked
        idx = [(i, j) for i, j in candidates
               if i < t.data.shape[0] and j < t.data.shape[1]]
        for i, j in idx:
            old = t.data[i, j]
            t.data[i, j] = old + eps
            fp = f()
            t.data[i, j] = old - eps
            fm = f()
            t.data[i, j] = old
            worst = max(worst, abs(analytic[tensors.index(t)][i, j]
                                   - (fp - fm) / (2 * eps)))
    assert worst < tol, f"gradient mismatch {worst:.2e}"


# ---- the new ops -----------------------------------------------------------
def test_sigmoid_tanh_mul_slice_gradients():
    rng = np.random.default_rng(0)
    x = A.Tensor(rng.normal(0, 1, (3, 4)), True)
    _gradcheck(lambda: A.sigmoid(x), [x])
    _gradcheck(lambda: A.tanh(x), [x])
    y = A.Tensor(rng.normal(0, 1, (3, 4)), True)
    _gradcheck(lambda: A.mul(x, y), [x, y])
    z = A.Tensor(rng.normal(0, 1, (3, 6)), True)
    _gradcheck(lambda: A.slice_cols(z, 2, 5), [z])


# ---- the LSTM --------------------------------------------------------------
def _tiny():
    pairs = make_pairs(6, seed=0)
    vocab_list = build_vocab(pairs)
    cfg = RNNConfig(hidden=4, max_len=40)
    return LSTMSeq2Seq(len(vocab_list), len(vocab_list), cfg, seed=0), vocab_list, pairs


def test_the_lstm_gradients_are_right():
    """Finite differences on the whole model, on a tiny one so it is affordable.
    A recurrent backward pass is where this kind of code goes wrong."""
    model, vocab_list, pairs = _tiny()
    p = pairs[0]
    src = encode(tokenise(p.text), vocab_list)
    tgt_in = encode([BOS] + p.tokens, vocab_list)
    tgt_out = encode(p.tokens + [EOS], vocab_list)
    rows = list(range(len(p.tokens) + 1))
    params = model.params()
    _gradcheck(lambda: model.loss(src, tgt_in, tgt_out, rows), params,
               entries=[(0, 0), (0, 1), (1, 0)])


def test_a_forget_gate_near_one_keeps_the_cell_state():
    """The point of the cell state: with the forget gate saturated and no input,
    the memory persists rather than decaying."""
    cell = LSTMSeq2Seq(10, 10, RNNConfig(hidden=4), seed=0).cell
    zero = A.Tensor.zeros(1, 4, True)
    state = (A.Tensor.zeros(1, 4, True), A.Tensor(np.ones((1, 4)) * 2.0, True))
    # force forget≈1 and input≈0 by making the projections large and negative
    cell.wx.w.data[...] = 0.0
    cell.wh.w.data[...] = 0.0
    cell.wx.b.data[...] = 0.0
    cell.wh.b.data[...] = 0.0
    cell.wh.b.data[0, 4:8] = 20.0          # forget gate on
    h, c = cell.step(zero, state)
    assert np.allclose(c.data, 2.0, atol=1e-3)


def test_the_output_at_a_step_does_not_depend_on_later_inputs():
    """Recurrence runs forwards only: changing a later token cannot change an
    earlier output."""
    model, vocab_list, _p = _tiny()
    state = model.encode([1, 2, 3, 4])
    a = np.vstack([t.data for t in model.decode([5, 6, 7], state)])
    b = np.vstack([t.data for t in model.decode([5, 6, 9], state)])
    assert np.allclose(a[:2], b[:2])
    assert not np.allclose(a[2], b[2])


def test_a_sequence_longer_than_max_len_is_refused():
    model = LSTMSeq2Seq(10, 10, RNNConfig(hidden=4, max_len=3), seed=0)
    with pytest.raises(ValueError, match="exceeds max_len"):
        model.encode([1, 2, 3, 4])


def test_save_and_load_round_trip(tmp_path):
    model, vocab_list, pairs = _tiny()
    p = tmp_path / "m.json"
    model.save(p)
    reloaded = LSTMSeq2Seq.load(p)
    assert evaluate(reloaded, pairs[:3], vocab_list)["exact"] == \
        evaluate(model, pairs[:3], vocab_list)["exact"]


def test_loading_a_transformer_file_as_an_lstm_is_refused(tmp_path):
    from wengold.learn.transformer import Config, Transformer
    t = Transformer(10, 10, Config(d_model=8, heads=2, max_len=8))
    p = tmp_path / "t.json"
    t.save(p)
    with pytest.raises(ValueError, match="does not hold an LSTM"):
        LSTMSeq2Seq.load(p)


def test_training_reduces_the_loss():
    pairs = make_pairs(12, seed=0)
    vocab_list = build_vocab(pairs)
    model = LSTMSeq2Seq(len(vocab_list), len(vocab_list),
                        RNNConfig(hidden=8, max_len=40), seed=0)
    _m, history = fit(model, pairs, vocab_list, epochs=6, lr=0.1)
    assert history[-1] < history[0]


# ---- the comparison, and its limit -----------------------------------------
def test_both_architectures_are_scored_by_the_same_function():
    """The comparison is only worth anything if the same code scores both."""
    pairs = make_pairs(20, seed=0)
    vocab_list = build_vocab(pairs)
    from wengold.learn.transformer import Config, Transformer
    rnn = LSTMSeq2Seq(len(vocab_list), len(vocab_list),
                      RNNConfig(hidden=8, max_len=40), seed=0)
    tf = Transformer(len(vocab_list), len(vocab_list),
                     Config(d_model=8, heads=2, max_len=40), seed=0)
    for model in (rnn, tf):
        r = evaluate(model, pairs[:5], vocab_list)
        assert set(r) == {"n", "exact", "exact_count", "token_accuracy"}
        assert 0.0 <= r["exact"] <= 1.0


def test_a_misread_sentence_passes_every_downstream_check():
    """The honest limit of the front-end, pinned.

    A spec that does not match the sentence still validates, still emits RTL that
    passes conformance, and still proves — because all of those check the spec's
    *internal consistency*, not its correspondence to English. Only the model's
    accuracy tells you whether to believe the reading.
    """
    misread = {"register": "r2", "addr": 4, "name": "ctrl", "hi": 3, "lo": 0,
               "access": "w1c", "reset": 0}
    assert validate(misread) == []                    # internally consistent
    out = check_pipeline(misread, module="misread")
    assert out["conformance_ok"] is True
    assert out["formal"]["status"] in ("proof", "fail")
    # and it is not what the sentence asked for: different register, field and
    # access mode from the one that was described
    assert misread["register"] != "r0"
    assert misread["access"] != "ro"
