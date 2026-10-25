"""Generative models that generate *stimulus* — and are judged on whether it helps.

Three families, one job, one yardstick.

**The job.** A verification team wants input sequences that reach states the
current tests miss. That is a real job, it is what WENGOLD already reasons about,
and — unlike generating RTL or images — it can be scored exactly: the formal
front-end can enumerate the reachable state set of a small design, so "did the
model help?" has a numeric answer rather than an impression.

**The models.** A VAE, a GAN and a diffusion model, all written out here on the
autodiff tape next door (no framework, no layers). Each maps a noise vector to a
flattened sequence of input bits and exposes the same two methods:

    model.fit(sequences)      # learn from a corpus of stimulus
    model.sample(n)           # emit n new sequences

**What they are not.** These are not image or text models and they are not large.
They exist to answer one question on one design, honestly, and the benchmark in
`coverage.py` is the part that matters. If a family loses to random sampling, this
package says so — that is the result, not a failure of the experiment.
"""
from __future__ import annotations

import math

import numpy as np

from .autograd import (Tensor, add, add_bias, backward, binary_cross_entropy,
                       concat_cols, embedding, gaussian_kl, matmul, mean_rows,
                       mul, relu, reparameterise, scale, sgd_step, sigmoid,
                       split_cols)
from .transformer import Linear

__all__ = ["VAE", "GAN", "Diffusion", "flatten", "unflatten"]


def flatten(sequences, steps: int, width: int) -> np.ndarray:
    """Sequences of ints -> one row of bits per sequence."""
    out = np.zeros((len(sequences), steps * width))
    for r, seq in enumerate(sequences):
        for t, value in enumerate(seq[:steps]):
            for b in range(width):
                out[r, t * width + b] = (value >> b) & 1
    return out


def unflatten(rows: np.ndarray, steps: int, width: int) -> list[list[int]]:
    """Rows of bits -> sequences of ints."""
    out = []
    for row in rows:
        seq = []
        for t in range(steps):
            v = 0
            for b in range(width):
                if row[t * width + b] >= 0.5:
                    v |= (1 << b)
            seq.append(v)
        out.append(seq)
    return out


def _mse(pred: Tensor, target: np.ndarray) -> Tensor:
    """Mean squared error, built from ops the tape already has."""
    diff = add(pred, scale(Tensor(target), -1.0))
    sq = mul(diff, diff)
    return mean_rows(mean_rows(sq))


class _Stimulus:
    """Shared plumbing: a fixed shape, a noise seed, and a training loop."""

    steps = 12
    width = 4
    seed = 0

    @property
    def dim(self) -> int:
        return self.steps * self.width

    def params(self):
        raise NotImplementedError

    def fit(self, sequences, epochs: int = 200, lr: float = 0.02,
            log_every: int = 0):
        raise NotImplementedError

    def sample(self, n: int) -> list[list[int]]:
        raise NotImplementedError

    def _rows(self, sequences) -> np.ndarray:
        return flatten(sequences, self.steps, self.width)


# ---------------------------------------------------------------- VAE
class VAE(_Stimulus):
    """Variational autoencoder: an encoder to a Gaussian, a decoder back to bits."""

    def __init__(self, steps=12, width=4, hidden=64, latent=8, seed=0):
        self.steps, self.width, self.seed = steps, width, seed
        self.latent = latent
        d = self.dim
        self.e1 = Linear(d, hidden, seed)
        self.e_mu = Linear(hidden, latent, seed + 1)
        self.e_lv = Linear(hidden, latent, seed + 2)
        self.d1 = Linear(latent, hidden, seed + 3)
        self.d2 = Linear(hidden, d, seed + 4)

    def params(self):
        return (self.e1.params() + self.e_mu.params() + self.e_lv.params()
                + self.d1.params() + self.d2.params())

    def _forward(self, x: Tensor):
        h = relu(self.e1(x))
        mu, lv = self.e_mu(h), self.e_lv(h)
        return mu, lv

    def fit(self, sequences, epochs: int = 200, lr: float = 0.02, beta: float = 0.5,
            log_every: int = 0):
        X = self._rows(sequences)
        rng = np.random.default_rng(self.seed)
        params = self.params()
        history = []
        for epoch in range(epochs):
            x = Tensor(X)
            mu, lv = self._forward(x)
            # reparameterise: z = mu + exp(lv/2) * eps, with eps fixed for this step
            eps = rng.normal(0, 1, mu.shape)
            z = reparameterise(mu, lv, eps)
            logits = self.d2(relu(self.d1(z)))
            rec = binary_cross_entropy(logits, X)
            kl = scale(gaussian_kl(mu, lv), beta / len(X))
            loss = add(rec, kl)
            for p in params:
                p.zero_grad()
            backward(loss)
            sgd_step(params, lr)
            history.append(float(loss.data[0, 0]))
            if log_every and (epoch + 1) % log_every == 0:
                print(f"    VAE epoch {epoch + 1:4}  loss {history[-1]:.4f}")
        return history

    def sample(self, n: int) -> list[list[int]]:
        rng = np.random.default_rng(self.seed + 1)
        z = Tensor(rng.normal(0, 1, (n, self.latent)))
        logits = self.d2(relu(self.d1(z)))
        probs = 1.0 / (1.0 + np.exp(-logits.data))
        return unflatten(probs, self.steps, self.width)


# ---------------------------------------------------------------- GAN
class GAN(_Stimulus):
    """A tiny GAN over stimulus bits.

    The discriminator sees the generator's *probabilities* rather than hard
    samples. With a model this small, hard sampling gives a discriminator that
    wins instantly and a generator with no gradient — the standard collapse.
    """

    def __init__(self, steps=12, width=4, hidden=64, latent=8, seed=0):
        self.steps, self.width, self.seed = steps, width, seed
        self.latent = latent
        d = self.dim
        self.g1 = Linear(latent, hidden, seed)
        self.g2 = Linear(hidden, d, seed + 1)
        self.d1 = Linear(d, hidden, seed + 2)
        self.d2 = Linear(hidden, 1, seed + 3)

    def g_params(self):
        return self.g1.params() + self.g2.params()

    def d_params(self):
        return self.d1.params() + self.d2.params()

    def params(self):
        return self.g_params() + self.d_params()

    def _gen_logits(self, z: Tensor) -> Tensor:
        return self.g2(relu(self.g1(z)))

    def _disc(self, x: Tensor) -> Tensor:
        return self.d2(relu(self.d1(x)))

    def fit(self, sequences, epochs: int = 200, lr: float = 0.01, log_every: int = 0):
        X = self._rows(sequences)
        rng = np.random.default_rng(self.seed)
        g_hist, d_hist = [], []
        for epoch in range(epochs):
            # --- discriminator: real vs generated probabilities
            z = Tensor(rng.normal(0, 1, (len(X), self.latent)))
            fake_logits = self._gen_logits(z)
            fake_probs = Tensor(1.0 / (1.0 + np.exp(-fake_logits.data)))
            real_scores = self._disc(Tensor(X))
            fake_scores = self._disc(fake_probs)
            d_loss = add(binary_cross_entropy(real_scores, np.ones_like(real_scores.data)),
                         binary_cross_entropy(fake_scores, np.zeros_like(fake_scores.data)))
            for p in self.d_params():
                p.zero_grad()
            backward(d_loss)
            sgd_step(self.d_params(), lr)
            d_hist.append(float(d_loss.data[0, 0]))

            # --- generator: fool the discriminator
            z = Tensor(rng.normal(0, 1, (len(X), self.latent)))
            fake_logits = self._gen_logits(z)
            fake_probs = Tensor(1.0 / (1.0 + np.exp(-fake_logits.data)))
            g_loss = binary_cross_entropy(self._disc(fake_probs),
                                          np.ones((len(X), 1)))
            for p in self.g_params():
                p.zero_grad()
            backward(g_loss)
            sgd_step(self.g_params(), lr)
            g_hist.append(float(g_loss.data[0, 0]))
            if log_every and (epoch + 1) % log_every == 0:
                print(f"    GAN epoch {epoch + 1:4}  D {d_hist[-1]:.3f}  G {g_hist[-1]:.3f}")
        return {"d": d_hist, "g": g_hist}

    def sample(self, n: int) -> list[list[int]]:
        rng = np.random.default_rng(self.seed + 1)
        z = Tensor(rng.normal(0, 1, (n, self.latent)))
        probs = 1.0 / (1.0 + np.exp(-self._gen_logits(z).data))
        return unflatten(probs, self.steps, self.width)


# ---------------------------------------------------------------- diffusion
class Diffusion(_Stimulus):
    """A DDPM over stimulus bits, in [-1, 1].

    Small on purpose: 24 noising steps, a two-layer denoiser, and a learned
    timestep embedding. Enough to be a real diffusion model and to run in
    seconds, which is what makes it comparable with the other two.
    """

    def __init__(self, steps=12, width=4, hidden=64, timesteps=24, seed=0):
        self.steps, self.width, self.seed = steps, width, seed
        self.timesteps = timesteps
        d = self.dim
        self.net1 = Linear(d + 8, hidden, seed)
        self.net2 = Linear(hidden, d, seed + 1)
        self.temb = Tensor.randn(timesteps, 8, scale=0.1, seed=seed + 2)
        beta = np.linspace(1e-3, 0.3, timesteps)
        self.beta = beta
        self.alpha = 1.0 - beta
        self.abar = np.cumprod(self.alpha)

    def params(self):
        return [self.temb] + self.net1.params() + self.net2.params()

    def _denoise(self, x: Tensor, t: int) -> Tensor:
        cond = embedding(self.temb, [t] * x.shape[0])
        return self.net2(relu(self.net1(concat_cols([x, cond]))))

    def fit(self, sequences, epochs: int = 200, lr: float = 0.01, log_every: int = 0):
        X = self._rows(sequences) * 2.0 - 1.0     # bits -> [-1, 1]
        rng = np.random.default_rng(self.seed)
        params = self.params()
        history = []
        for epoch in range(epochs):
            total = 0.0
            for _ in range(max(1, len(X) // 8)):
                idx = rng.integers(0, len(X), size=8)
                x0 = X[idx]
                t = int(rng.integers(0, self.timesteps))
                eps = rng.normal(0, 1, x0.shape)
                xt = math.sqrt(self.abar[t]) * x0 + math.sqrt(1 - self.abar[t]) * eps
                pred = self._denoise(Tensor(xt), t)
                loss = _mse(pred, eps)
                for p in params:
                    p.zero_grad()
                backward(loss)
                sgd_step(params, lr)
                total += float(loss.data[0, 0])
            history.append(total / max(1, len(X) // 8))
            if log_every and (epoch + 1) % log_every == 0:
                print(f"    diffusion epoch {epoch + 1:4}  loss {history[-1]:.4f}")
        return history

    def sample(self, n: int) -> list[list[int]]:
        rng = np.random.default_rng(self.seed + 1)
        x = rng.normal(0, 1, (n, self.dim))
        for t in reversed(range(self.timesteps)):
            eps_hat = self._denoise(Tensor(x), t).data
            mean = (x - self.beta[t] / math.sqrt(1 - self.abar[t]) * eps_hat) \
                / math.sqrt(self.alpha[t])
            if t > 0:
                x = mean + math.sqrt(self.beta[t]) * rng.normal(0, 1, x.shape)
            else:
                x = mean
        bits = (x + 1.0) / 2.0                     # back to [0, 1]
        return unflatten(bits, self.steps, self.width)
