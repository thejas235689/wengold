"""The Tensor operators, and the gradients behind them.

`Tensor` had no Python operators at all: `a + a` and `a * a` raised TypeError, and
every operation had to be written as a free function. That works — the transformer
and LSTM are written that way — but a from-scratch autograd library where `a * a`
fails is a surprising API.

Each operator delegates to an existing free function rather than implementing its
own arithmetic, so there is one backward pass per operation instead of two that can
drift apart. `div` and `neg` are new primitives and get their own check.

The gradient check is the point. A hand-written backward pass that is subtly wrong
still trains — it just trains something else — so every operator here is compared
against finite differences rather than trusted.
"""
import numpy as np
import pytest

from wengold.learn import autograd as A


def T(rows, cols, seed=0, grad=True):
    rng = np.random.default_rng(seed)
    return A.Tensor(rng.normal(0, 1, (rows, cols)), grad)


def gradcheck(build, tensors, tol=1e-4):
    """Central-difference check of every entry of every tensor."""
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


# ---- the operators exist and compute the right values ---------------------
def test_add_sub_mul_div_neg():
    a = A.Tensor(np.array([[1.0, 2.0]]))
    b = A.Tensor(np.array([[3.0, 4.0]]))
    assert np.allclose((a + b).data, [[4, 6]])
    assert np.allclose((a - b).data, [[-2, -2]])
    assert np.allclose((a * b).data, [[3, 8]])
    assert np.allclose((a / b).data, [[1 / 3, 0.5]])
    assert np.allclose((-a).data, [[-1, -2]])


def test_matmul_operator():
    a = T(2, 3, seed=1)
    b = T(3, 4, seed=2)
    assert np.allclose((a @ b).data, A.matmul(a, b).data)


# ---- scalars on either side ----------------------------------------------
def test_scalar_on_the_right():
    a = A.Tensor(np.array([[1.0, 2.0]]))
    assert np.allclose((a + 1).data, [[2, 3]])
    assert np.allclose((a - 1).data, [[0, 1]])
    assert np.allclose((a * 2).data, [[2, 4]])
    assert np.allclose((a / 2).data, [[0.5, 1.0]])


def test_scalar_on_the_left():
    a = A.Tensor(np.array([[1.0, 2.0]]))
    assert np.allclose((1 + a).data, [[2, 3]])
    assert np.allclose((1 - a).data, [[0, -1]])
    assert np.allclose((2 * a).data, [[2, 4]])
    assert np.allclose((2 / a).data, [[2, 1]])


def test_a_scalar_operand_does_not_become_a_gradient_target():
    """`a * 2` must not try to accumulate a gradient into a constant."""
    a = T(2, 2, seed=3)
    out = a * 2
    A.backward(out)
    assert a.grad is not None
    assert np.allclose(a.grad, 2.0)


# ---- gradients ------------------------------------------------------------
@pytest.mark.parametrize("op", ["add", "sub", "mul", "div"])
def test_binary_operator_gradients(op):
    a = T(3, 3, seed=4)
    b = T(3, 3, seed=5)
    # keep b away from zero so div is well conditioned
    b.data = np.abs(b.data) + 0.5
    build = {"add": lambda: a + b, "sub": lambda: a - b,
             "mul": lambda: a * b, "div": lambda: a / b}[op]
    gradcheck(build, [a, b])


def test_neg_gradient():
    a = T(3, 2, seed=6)
    gradcheck(lambda: -a, [a])


def test_matmul_operator_gradient():
    a = T(2, 3, seed=7)
    b = T(3, 2, seed=8)
    gradcheck(lambda: a @ b, [a, b])


def test_scalar_multiply_gradient():
    a = T(2, 2, seed=9)
    gradcheck(lambda: a * 3.0, [a])


def test_scalar_divide_gradient():
    a = T(2, 2, seed=10)
    gradcheck(lambda: a / 4.0, [a])


def test_a_chain_through_every_operator():
    """The realistic case: several operators composed, gradients to all inputs."""
    a = T(3, 3, seed=11)
    b = T(3, 3, seed=12)
    b.data = np.abs(b.data) + 0.5
    gradcheck(lambda: ((a * b) - (a / b)) + (-a), [a, b])


def test_div_backward_has_the_second_term():
    """d/db (a/b) = -a/b^2 is the term that is easy to drop. If it were missing,
    `div` would still train and this check would fail."""
    a = A.Tensor(np.array([[2.0]]), True)
    b = A.Tensor(np.array([[4.0]]), True)
    out = a / b
    A.backward(out)
    assert np.allclose(a.grad, [[1 / 4]]), "d/da (a/b) should be 1/b"
    assert np.allclose(b.grad, [[-2 / 16]]), "d/db (a/b) should be -a/b^2"
