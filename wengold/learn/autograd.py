"""Reverse-mode autodiff over matrices, on numpy.

A transformer needs gradients. This is a small tape: each operation records how to
push a gradient back to its inputs, and `backward` walks the graph in reverse
topological order.

**Every op has a numerical gradient check** in `tests/test_transformer.py`. A
hand-written backward pass that is subtly wrong still trains — it just trains
something else — so the gradients are verified against finite differences rather
than trusted. That is the only reason to believe the attention is correct.

numpy is used for the arithmetic and nothing else: no autodiff framework, no
layers, no optimiser. The tape, the ops and the backward passes are here.
"""
from __future__ import annotations

import numpy as np

__all__ = ["Tensor", "matmul", "add", "add_bias", "scale", "softmax",
           "layer_norm", "relu", "transpose", "embedding", "cross_entropy",
           "mean_rows", "mask_fill", "backward", "sgd_step",
           # needed by the LSTM
           "sigmoid", "tanh", "mul", "div", "neg", "slice_cols",
           # needed by the generative models
           "binary_cross_entropy", "gaussian_kl", "concat_cols", "split_cols",
           "reparameterise"]


class Tensor:
    """A 2-D float matrix with a gradient of the same shape."""

    __slots__ = ("data", "grad", "requires_grad", "parents", "_backward")

    def __init__(self, data, requires_grad: bool = False, parents=(), backward=None):
        arr = np.asarray(data, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        self.data = arr
        self.requires_grad = requires_grad
        self.parents = tuple(parents)
        self._backward = backward
        self.grad = np.zeros_like(arr) if requires_grad else None

    # -- construction helpers ------------------------------------------------
    @staticmethod
    def zeros(rows: int, cols: int, requires_grad: bool = False) -> "Tensor":
        return Tensor(np.zeros((rows, cols)), requires_grad)

    @staticmethod
    def ones(rows: int, cols: int, requires_grad: bool = False) -> "Tensor":
        return Tensor(np.ones((rows, cols)), requires_grad)

    @staticmethod
    def randn(rows: int, cols: int, scale: float = 0.02,
              requires_grad: bool = True, seed: int = 0) -> "Tensor":
        rng = np.random.default_rng(seed)
        return Tensor(rng.normal(0.0, scale, size=(rows, cols)), requires_grad)

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.shape

    def zero_grad(self) -> None:
        if self.grad is not None:
            self.grad[...] = 0.0

    def __repr__(self) -> str:
        return f"Tensor{self.shape}"

    # -- operators -----------------------------------------------------------
    # These delegate to the free functions so each operation has exactly one
    # backward pass. A second implementation here would be a second thing to keep
    # correct, and the gradient checks only cover one of them.
    def _lift(self, other) -> "Tensor":
        """A scalar or array becomes a constant Tensor of the same shape."""
        if isinstance(other, Tensor):
            return other
        arr = np.asarray(other, dtype=np.float64)
        if arr.ndim == 0:
            arr = np.full(self.shape, float(arr))
        elif arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        return Tensor(np.broadcast_to(arr, self.shape))

    def __add__(self, other):
        return add(self, self._lift(other))

    def __radd__(self, other):
        return add(self._lift(other), self)

    def __sub__(self, other):
        return add(self, neg(self._lift(other)))

    def __rsub__(self, other):
        return add(self._lift(other), neg(self))

    def __mul__(self, other):
        if isinstance(other, Tensor):
            return mul(self, other)
        # a scalar multiply is `scale`, which is cheaper and already checked
        return scale(self, float(np.asarray(other)))

    def __rmul__(self, other):
        return self.__mul__(other)

    def __truediv__(self, other):
        if isinstance(other, Tensor):
            return div(self, other)
        return scale(self, 1.0 / float(np.asarray(other)))

    def __rtruediv__(self, other):
        return div(self._lift(other), self)

    def __neg__(self):
        return neg(self)

    def __matmul__(self, other):
        return matmul(self, self._lift(other) if not isinstance(other, Tensor)
                      else other)


# ---- operations ------------------------------------------------------------
def matmul(a: Tensor, b: Tensor) -> Tensor:
    node = Tensor(a.data @ b.data, a.requires_grad or b.requires_grad, (a, b))

    def _backward():
        if a.requires_grad:
            a.grad += node.grad @ b.data.T
        if b.requires_grad:
            b.grad += a.data.T @ node.grad

    node._backward = _backward
    return node


def add(a: Tensor, b: Tensor) -> Tensor:
    node = Tensor(a.data + b.data, a.requires_grad or b.requires_grad, (a, b))

    def _backward():
        if a.requires_grad:
            a.grad += node.grad
        if b.requires_grad:
            b.grad += node.grad

    node._backward = _backward
    return node


def div(a: Tensor, b: Tensor) -> Tensor:
    """Elementwise quotient, same shape.

    d/da (a/b) = 1/b, d/db (a/b) = -a/b^2. The second term is the one that is easy
    to forget and produces a model that trains but trains something else.
    """
    node = Tensor(a.data / b.data, a.requires_grad or b.requires_grad, (a, b))

    def _backward():
        if a.requires_grad:
            a.grad += node.grad / b.data
        if b.requires_grad:
            b.grad += -node.grad * a.data / (b.data ** 2)

    node._backward = _backward
    return node


def neg(a: Tensor) -> Tensor:
    return scale(a, -1.0)


def add_bias(a: Tensor, bias: Tensor) -> Tensor:
    """Add a 1 x m bias to every row; the backward sums the rows."""
    node = Tensor(a.data + bias.data, a.requires_grad or bias.requires_grad,
                  (a, bias))

    def _backward():
        if a.requires_grad:
            a.grad += node.grad
        if bias.requires_grad:
            bias.grad += node.grad.sum(axis=0, keepdims=True)

    node._backward = _backward
    return node


def scale(a: Tensor, s: float) -> Tensor:
    node = Tensor(a.data * s, a.requires_grad, (a,))

    def _backward():
        if a.requires_grad:
            a.grad += node.grad * s

    node._backward = _backward
    return node


def transpose(a: Tensor) -> Tensor:
    node = Tensor(a.data.T, a.requires_grad, (a,))

    def _backward():
        if a.requires_grad:
            a.grad += node.grad.T

    node._backward = _backward
    return node


def softmax(a: Tensor) -> Tensor:
    x = a.data - a.data.max(axis=1, keepdims=True)
    e = np.exp(x)
    y = e / e.sum(axis=1, keepdims=True)
    node = Tensor(y, a.requires_grad, (a,))

    def _backward():
        if a.requires_grad:
            dot = (node.grad * y).sum(axis=1, keepdims=True)
            a.grad += y * (node.grad - dot)

    node._backward = _backward
    return node


def relu(a: Tensor) -> Tensor:
    node = Tensor(np.maximum(a.data, 0.0), a.requires_grad, (a,))

    def _backward():
        if a.requires_grad:
            a.grad += node.grad * (a.data > 0)

    node._backward = _backward
    return node


def layer_norm(a: Tensor, gamma: Tensor, beta: Tensor, eps: float = 1e-5) -> Tensor:
    """Normalise each row, then scale and shift. Gradients for all three inputs."""
    mu = a.data.mean(axis=1, keepdims=True)
    var = a.data.var(axis=1, keepdims=True)
    inv = 1.0 / np.sqrt(var + eps)
    norm = (a.data - mu) * inv
    out = norm * gamma.data + beta.data
    node = Tensor(out, a.requires_grad or gamma.requires_grad or beta.requires_grad,
                  (a, gamma, beta))
    m = a.data.shape[1]

    def _backward():
        if gamma.requires_grad:
            gamma.grad += (node.grad * norm).sum(axis=0, keepdims=True)
        if beta.requires_grad:
            beta.grad += node.grad.sum(axis=0, keepdims=True)
        if a.requires_grad:
            dnorm = node.grad * gamma.data
            s = dnorm.sum(axis=1, keepdims=True)
            s2 = (dnorm * norm).sum(axis=1, keepdims=True)
            a.grad += inv / m * (m * dnorm - s - norm * s2)

    node._backward = _backward
    return node


def embedding(weight: Tensor, indices: list[int]) -> Tensor:
    """Rows of `weight`, one per index — the token embedding lookup."""
    idx = np.asarray(indices, dtype=int)
    node = Tensor(weight.data[idx], weight.requires_grad, (weight,))

    def _backward():
        if weight.requires_grad:
            np.add.at(weight.grad, idx, node.grad)

    node._backward = _backward
    return node


def mask_fill(a: Tensor, keep, value: float = -1e9) -> Tensor:
    """Set entries to `value` where `keep` is False (causal / padding masks)."""
    keep_arr = np.asarray(keep, dtype=bool)
    node = Tensor(np.where(keep_arr, a.data, value), a.requires_grad, (a,))

    def _backward():
        if a.requires_grad:
            a.grad += np.where(keep_arr, node.grad, 0.0)

    node._backward = _backward
    return node


def sigmoid(a: Tensor) -> Tensor:
    s = 1.0 / (1.0 + np.exp(-np.clip(a.data, -60, 60)))
    node = Tensor(s, a.requires_grad, (a,))

    def _backward():
        if a.requires_grad:
            a.grad += node.grad * s * (1.0 - s)

    node._backward = _backward
    return node


def tanh(a: Tensor) -> Tensor:
    t = np.tanh(a.data)
    node = Tensor(t, a.requires_grad, (a,))

    def _backward():
        if a.requires_grad:
            a.grad += node.grad * (1.0 - t * t)

    node._backward = _backward
    return node


def mul(a: Tensor, b: Tensor) -> Tensor:
    """Elementwise product, same shape — the gate application in an LSTM."""
    node = Tensor(a.data * b.data, a.requires_grad or b.requires_grad, (a, b))

    def _backward():
        if a.requires_grad:
            a.grad += node.grad * b.data
        if b.requires_grad:
            b.grad += node.grad * a.data

    node._backward = _backward
    return node


def binary_cross_entropy(logits: Tensor, targets) -> Tensor:
    """Mean BCE from raw logits, in the numerically stable form.

    Computed from logits rather than probabilities: `log(sigmoid(x))` on a
    sigmoid output underflows to -inf as the model grows confident, which is
    exactly when the gradient matters.
    """
    x = np.clip(logits.data, -60, 60)
    y = np.asarray(targets, dtype=np.float64)
    if y.ndim == 1:
        y = y.reshape(-1, 1)
    # softplus(x) - y*x, mean over every element
    loss_val = float(np.mean(np.logaddexp(0.0, x) - y * x))
    n = x.size
    node = Tensor([[loss_val]], logits.requires_grad, (logits,))

    def _backward():
        if logits.requires_grad:
            s = 1.0 / (1.0 + np.exp(-x))
            logits.grad += (s - y) * (node.grad[0, 0] / n)

    node._backward = _backward
    return node


def gaussian_kl(mu: Tensor, logvar: Tensor) -> Tensor:
    """KL( N(mu, exp(logvar)) || N(0,1) ), summed over the columns.

    A scalar loss term, with the analytic gradient — no need to route it through
    the tape's elementwise ops.
    """
    m, lv = mu.data, logvar.data
    kl = float(0.5 * np.sum(np.exp(lv) + m * m - 1.0 - lv))
    node = Tensor([[kl]], mu.requires_grad or logvar.requires_grad, (mu, logvar))

    def _backward():
        g = node.grad[0, 0]
        if mu.requires_grad:
            mu.grad += g * m
        if logvar.requires_grad:
            logvar.grad += g * 0.5 * (np.exp(lv) - 1.0)

    node._backward = _backward
    return node


def reparameterise(mu: Tensor, logvar: Tensor, eps: np.ndarray) -> Tensor:
    """z = mu + exp(logvar/2) * eps — the VAE's sampling step, with gradients.

    Written as an op because building it from `mul` and a hand-made tensor left no
    path back to `logvar`: the gradient through the noise scaling is
    dz/dlogvar = 0.5 * exp(logvar/2) * eps, and nothing in the elementwise ops
    knows that.
    """
    std = np.exp(np.clip(logvar.data, -20, 20) / 2.0)
    z = mu.data + std * eps
    node = Tensor(z, mu.requires_grad or logvar.requires_grad, (mu, logvar))

    def _backward():
        g = node.grad
        if mu.requires_grad:
            mu.grad += g
        if logvar.requires_grad:
            logvar.grad += g * 0.5 * std * eps

    node._backward = _backward
    return node


def concat_cols(tensors: list["Tensor"]) -> Tensor:
    """Concatenate along columns, keeping the gradient path to each part."""
    widths = [t.shape[1] for t in tensors]
    node = Tensor(np.concatenate([t.data for t in tensors], axis=1),
                  any(t.requires_grad for t in tensors), tuple(tensors))

    def _backward():
        lo = 0
        for t, w in zip(tensors, widths):
            if t.requires_grad:
                t.grad += node.grad[:, lo:lo + w]
            lo += w

    node._backward = _backward
    return node


def split_cols(a: Tensor, widths: list[int]) -> list["Tensor"]:
    """The inverse of `concat_cols`."""
    parts, lo = [], 0
    for w in widths:
        parts.append(Tensor(a.data[:, lo:lo + w], a.requires_grad, (a,)))
        lo += w

    def _backward():
        if not a.requires_grad:
            return
        lo = 0
        for part, w in zip(parts, widths):
            a.grad[:, lo:lo + w] += part.grad
            lo += w
    for part in parts:
        part._backward = _backward
    return parts


def slice_cols(a: Tensor, lo: int, hi: int) -> Tensor:
    """Columns [lo, hi) — splitting one projection into four gates."""
    node = Tensor(a.data[:, lo:hi], a.requires_grad, (a,))

    def _backward():
        if a.requires_grad:
            a.grad[:, lo:hi] += node.grad

    node._backward = _backward
    return node


def mean_rows(a: Tensor) -> Tensor:
    """Average the rows — turns a per-token quantity into a scalar."""
    node = Tensor(a.data.mean(axis=0, keepdims=True), a.requires_grad, (a,))
    n = a.data.shape[0]

    def _backward():
        if a.requires_grad:
            a.grad += np.broadcast_to(node.grad / n, a.data.shape)

    node._backward = _backward
    return node


def cross_entropy(logits: Tensor, targets: list[int],
                  rows: list[int] | None = None) -> Tensor:
    """Mean negative log-likelihood, over `rows` if given.

    `rows` selects which positions count, so padded tokens stay out of the loss
    without needing a gather op — and the mean is over real tokens.
    """
    x = logits.data
    x = x - x.max(axis=1, keepdims=True)
    logsumexp = np.log(np.exp(x).sum(axis=1, keepdims=True))
    log_probs = x - logsumexp
    use = np.asarray(rows if rows is not None else range(len(targets)), dtype=int)
    count = max(len(use), 1)
    total = -log_probs[use, np.asarray(targets)[use]].sum()
    node = Tensor(np.array([[total / count]]), logits.requires_grad, (logits,))
    probs = np.exp(log_probs)

    def _backward():
        if not logits.requires_grad:
            return
        g = np.zeros_like(probs)
        g[use, np.asarray(targets)[use]] = 1.0
        grad = (probs - g) * (node.grad[0, 0] / count)
        # rows outside `use` do not enter the loss, so they must not receive a
        # gradient. Without this they got `probs/count`, which quietly drags
        # padded positions toward the uniform distribution.
        row_mask = np.zeros(probs.shape[0], dtype=bool)
        row_mask[use] = True
        grad[~row_mask] = 0.0
        logits.grad += grad

    node._backward = _backward
    return node


# ---- the tape --------------------------------------------------------------
def backward(loss: Tensor) -> None:
    """Reverse topological order, then run each node's backward."""
    topo: list[Tensor] = []
    seen: set[int] = set()

    def visit(node: Tensor):
        if id(node) in seen:
            return
        seen.add(id(node))
        for p in node.parents:
            visit(p)
        topo.append(node)

    visit(loss)
    if loss.grad is None:
        loss.grad = np.ones_like(loss.data)
    else:
        loss.grad[...] = 1.0
    for node in reversed(topo):
        if node._backward is not None:
            node._backward()


def sgd_step(params: list[Tensor], lr: float, clip: float = 1.0) -> None:
    """Plain SGD with gradient clipping, so one bad step cannot blow it up."""
    for p in params:
        if p.grad is None:
            continue
        g = np.nan_to_num(p.grad, nan=0.0, posinf=clip, neginf=-clip)
        np.clip(g, -clip, clip, out=g)
        p.data -= lr * g
