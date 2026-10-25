"""The transformer: gradients, attention, training, and the spec front-end.

The gradient checks are the foundation. A hand-written backward pass that is
subtly wrong still trains — it just trains something else — so every op is
compared against finite differences here rather than trusted. Everything above
them assumes they are right.
"""
import numpy as np
import pytest

from wengold.learn import autograd as A
from wengold.learn.spec_model import build_vocab, evaluate, predict_spec, train_model
from wengold.learn.spec_text import canonical, make_pairs, parse_canonical
from wengold.learn.transformer import Config, Transformer
from wengold.spec_frontend import to_module_spec, validate


def _T(rows, cols, seed=0, grad=True):
    rng = np.random.default_rng(seed)
    return A.Tensor(rng.normal(0, 1, (rows, cols)), grad)


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
    numeric = []
    for t in tensors:
        g = np.zeros_like(t.data)
        for i in range(t.data.shape[0]):
            for j in range(t.data.shape[1]):
                old = t.data[i, j]
                t.data[i, j] = old + eps
                fp = f()
                t.data[i, j] = old - eps
                fm = f()
                t.data[i, j] = old
                g[i, j] = (fp - fm) / (2 * eps)
        numeric.append(g)
    worst = max(float(np.abs(a - n).max()) for a, n in zip(analytic, numeric))
    assert worst < tol, f"gradient mismatch {worst:.2e}"


# ---- every op, against finite differences ----------------------------------
def test_matmul_gradients():
    x, w = _T(3, 4, 1), _T(4, 2, 2)
    _gradcheck(lambda: A.matmul(x, w), [x, w])


def test_add_and_scale_gradients():
    x, y = _T(3, 4, 3), _T(3, 4, 4)
    _gradcheck(lambda: A.add(x, y), [x, y])
    _gradcheck(lambda: A.scale(x, 2.5), [x])


def test_add_bias_gradients():
    x, b = _T(3, 4, 5), _T(1, 4, 6)
    _gradcheck(lambda: A.add_bias(x, b), [x, b])


def test_transpose_and_softmax_gradients():
    x = _T(3, 4, 7)
    _gradcheck(lambda: A.transpose(x), [x])
    _gradcheck(lambda: A.softmax(x), [x])


def test_relu_gradients():
    x = _T(3, 4, 8)
    _gradcheck(lambda: A.relu(x), [x])


def test_layer_norm_gradients():
    x, g, b = _T(3, 4, 9), _T(1, 4, 10), _T(1, 4, 11)
    _gradcheck(lambda: A.layer_norm(x, g, b), [x, g, b])


def test_embedding_gradients():
    w = A.Tensor(np.random.default_rng(12).normal(0, 1, (3, 2)), True)
    _gradcheck(lambda: A.embedding(w, [0, 2, 1, 2]), [w])


def test_mask_fill_gradients():
    """Checked with a moderate fill value: at -1e9 the finite difference is
    swamped by the magnitude of the output and the comparison says nothing."""
    x = _T(3, 4, 13)
    keep = [[1, 1, 1, 1], [1, 0, 1, 1], [0, 1, 1, 1]]
    _gradcheck(lambda: A.mask_fill(x, keep, value=-50.0), [x])


def test_mean_rows_and_cross_entropy_gradients():
    x = _T(3, 4, 14)
    _gradcheck(lambda: A.mean_rows(x), [x])
    y = _T(4, 3, 15)
    _gradcheck(lambda: A.cross_entropy(y, [0, 2, 1, 2]), [y])


def test_cross_entropy_with_rows_does_not_leak_into_padding():
    """Rows outside `use` are not in the loss, so they must get no gradient.
    They did, and it quietly dragged padded positions toward uniform."""
    y = _T(4, 3, 16)
    _gradcheck(lambda: A.cross_entropy(y, [0, 2, 1, 2], rows=[0, 2]), [y])
    y = _T(4, 3, 17)
    A.backward(A.cross_entropy(y, [0, 2, 1, 2], rows=[0, 2]))
    assert np.allclose(y.grad[1], 0.0) and np.allclose(y.grad[3], 0.0)
    assert not np.allclose(y.grad[0], 0.0)


# ---- attention -------------------------------------------------------------
def test_causal_masking_hides_the_future():
    """Change a token and nothing before it may change its output."""
    cfg = Config(d_model=16, heads=2, enc_layers=1, dec_layers=1, d_ff=32, max_len=12)
    m = Transformer(20, 20, cfg, seed=0)
    memory = m.encode([1, 2, 3, 4, 5])
    a = m.decode([6, 7, 8], memory).data.copy()
    b = m.decode([6, 7, 9], memory).data.copy()
    assert np.allclose(a[:2], b[:2]), "position 2 was affected by token 3"
    assert not np.allclose(a[2], b[2])


def test_a_sequence_longer_than_max_len_is_refused():
    cfg = Config(d_model=8, heads=1, max_len=4)
    m = Transformer(10, 10, cfg, seed=0)
    with pytest.raises(ValueError, match="exceeds max_len"):
        m.encode([1, 2, 3, 4, 5])


# ---- training --------------------------------------------------------------
@pytest.fixture(scope="module")
def trained():
    pairs = make_pairs(60, seed=0)
    vocab_list = build_vocab(pairs)
    cfg = Config(d_model=24, heads=2, enc_layers=1, dec_layers=1, d_ff=48, max_len=40)
    # 25 epochs leaves it at 25% exact; it needs about 45 to converge, which is
    # the honest cost of a from-scratch model on this corpus
    model, history = train_model(pairs, vocab_list, cfg, epochs=45, lr=0.05, seed=0)
    return model, vocab_list, pairs, history


def test_training_reduces_the_loss(trained):
    _m, _v, _p, history = trained
    assert history[-1] < history[0] * 0.2, f"loss did not fall: {history[:3]}"


def test_it_learns_the_grammar_it_was_trained_on(trained):
    model, vocab_list, pairs, _h = trained
    r = evaluate(model, pairs[:20], vocab_list)
    assert r["exact"] >= 0.8, f"exact match {r['exact']:.2f} on training wordings"


def test_it_reads_a_sentence_into_a_spec(trained):
    model, vocab_list, _p, _h = trained
    spec = predict_spec(
        model,
        "a register r0 at address 4 with a read only field status at bits 3 to 0 "
        ", resets to zero", vocab_list)
    assert spec["register"] == "r0" and spec["addr"] == 4
    assert spec["name"] == "status" and (spec["hi"], spec["lo"]) == (3, 0)
    assert spec["access"] == "ro" and spec["reset"] == 0


def test_a_sentence_outside_the_grammar_is_refused(trained):
    """The model knows one grammar. Something outside it must fail loudly, not
    produce a plausible-looking spec."""
    model, vocab_list, _p, _h = trained
    with pytest.raises(ValueError):
        predict_spec(model, "make me a coffee please", vocab_list)


def test_save_and_load_round_trip(trained, tmp_path):
    model, vocab_list, pairs, _h = trained
    p = tmp_path / "m.json"
    model.save(p)
    reloaded = Transformer.load(p)
    assert evaluate(reloaded, pairs[:5], vocab_list)["exact"] == \
        evaluate(model, pairs[:5], vocab_list)["exact"]


# ---- the spec front-end ----------------------------------------------------
def test_the_parser_accepts_a_well_formed_sequence():
    assert parse_canonical(canonical("status", 3, 0, "ro", 0, 4, "r0")) == {
        "register": "r0", "addr": 4, "name": "status", "hi": 3, "lo": 0,
        "access": "ro", "reset": 0}


@pytest.mark.parametrize("bad,reason", [
    (["spec", "r0", "4", "x", "3", "0", "bogus", "0", "end"], "access mode"),
    (["spec", "r0", "5", "x", "3", "0", "ro", "0", "end"], "aligned"),
    (["spec", "r0", "4", "x", "0", "3", "ro", "0", "end"], "reversed"),
    (["spec", "r0", "4", "x", "3", "0"], "truncated"),
])
def test_the_parser_refuses_malformed_sequences(bad, reason):
    with pytest.raises(ValueError) as exc:
        parse_canonical(bad)
    assert reason in str(exc.value)


def test_validation_accepts_a_good_spec_and_refuses_bad_ones():
    good = {"register": "r0", "addr": 4, "name": "status", "hi": 3, "lo": 0,
            "access": "ro", "reset": 0}
    assert validate(good) == []
    assert any("access mode" in p for p in validate({**good, "access": "nonsense"}))
    assert any("aligned" in p for p in validate({**good, "addr": 5}))
    assert any("reversed" in p for p in validate({**good, "hi": 0, "lo": 3}))
    assert any("does not fit" in p for p in validate({**good, "reset": 16}))
    assert any("outside a 32-bit" in p for p in validate({**good, "hi": 40}))


def test_a_validated_spec_becomes_a_module_spec_the_generator_accepts():
    from wengold.generate.emit import emit_rtl
    spec = {"register": "r0", "addr": 4, "name": "status", "hi": 3, "lo": 0,
            "access": "ro", "reset": 0}
    rtl = emit_rtl(to_module_spec(spec, "drafted"))
    assert "module drafted" in rtl
    # the field signal is named from the register and field, not the module
    assert "r0_status_q" in rtl
