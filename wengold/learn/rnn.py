"""An LSTM encoder-decoder, for the same task as the transformer.

The point of adding an RNN here is not that recurrence is fashionable — it is that
the two architectures can be compared on **identical data, an identical split and
an identical metric**, and the answer reported. Both read the same sentences, both
decode the same canonical spec, and both are scored by exact match. Whatever the
numbers say is the result.

The LSTM is the standard one: input, forget, output and cell gates, a cell state
carried through the sequence, and a projection from the final hidden state. The
encoder runs over the source and hands its final `(h, c)` to the decoder, which
generates the spec one token at a time. No attention — that would be a third
architecture, and this is meant to be the plain recurrent baseline.

One honest note on why the gates are computed as one projection split four ways:
four separate matrices would be four times the parameters for the same function.
The `slice_cols` op exists for exactly this, and is gradient-checked like the rest.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .autograd import (Tensor, add, add_bias, backward, cross_entropy, embedding,
                       matmul, mul, scale, sigmoid, slice_cols, tanh)
from .transformer import Linear

__all__ = ["LSTMSeq2Seq", "RNNConfig"]


@dataclass
class RNNConfig:
    hidden: int = 48
    max_len: int = 40


class LSTMCell:
    """One recurrent step, with a cell state."""

    def __init__(self, d_in: int, hidden: int, seed: int):
        self.hidden = hidden
        self.wx = Linear(d_in, 4 * hidden, seed)
        self.wh = Linear(hidden, 4 * hidden, seed + 1)

    def step(self, x: Tensor, state: tuple[Tensor, Tensor]) -> tuple[Tensor, Tensor]:
        """x is 1 x d_in; state is (h, c), each 1 x hidden."""
        h, c = state
        # one projection, split into the four gates
        proj = add(self.wx(x), self.wh(h))
        i = sigmoid(slice_cols(proj, 0, self.hidden))
        f = sigmoid(slice_cols(proj, self.hidden, 2 * self.hidden))
        g = tanh(slice_cols(proj, 2 * self.hidden, 3 * self.hidden))
        o = sigmoid(slice_cols(proj, 3 * self.hidden, 4 * self.hidden))
        c_new = add(mul(f, c), mul(i, g))
        h_new = mul(o, tanh(c_new))
        return h_new, c_new

    def params(self):
        return self.wx.params() + self.wh.params()

    def state(self):
        return {"wx": self.wx.state(), "wh": self.wh.state()}

    def load(self, d):
        self.wx.load(d["wx"])
        self.wh.load(d["wh"])


class LSTMSeq2Seq:
    """Encoder-decoder over integer token ids, with no attention."""

    def __init__(self, src_vocab: int, tgt_vocab: int, cfg: RNNConfig | None = None,
                 seed: int = 0):
        self.cfg = cfg or RNNConfig()
        self.src_vocab, self.tgt_vocab = src_vocab, tgt_vocab
        self.emb = Tensor.randn(src_vocab, self.cfg.hidden, seed=seed)
        self.cell = LSTMCell(self.cfg.hidden, self.cfg.hidden, seed + 10)
        self.out = Linear(self.cfg.hidden, tgt_vocab, seed + 20)

    def _zero_state(self) -> tuple[Tensor, Tensor]:
        return (Tensor.zeros(1, self.cfg.hidden, True),
                Tensor.zeros(1, self.cfg.hidden, True))

    def encode(self, src_ids: list[int]) -> tuple[Tensor, Tensor]:
        if len(src_ids) > self.cfg.max_len:
            raise ValueError(f"sequence of {len(src_ids)} tokens exceeds "
                             f"max_len {self.cfg.max_len}")
        state = self._zero_state()
        for i in src_ids:
            state = self.cell.step(embedding(self.emb, [i]), state)
        return state

    def decode(self, tgt_ids: list[int],
               state: tuple[Tensor, Tensor]) -> list[Tensor]:
        """One 1 x vocab logits tensor per target position."""
        h, c = state
        logits = []
        for i in tgt_ids:
            h, c = self.cell.step(embedding(self.emb, [i]), (h, c))
            logits.append(self.out(h))
        return logits

    def loss(self, src_ids, tgt_in, tgt_out, rows=None) -> Tensor:
        """Cross-entropy summed over the positions that count, then averaged.

        Per step rather than over one stacked matrix: it needs no gather op, and
        the mean is over the real tokens so padding stays out of it.
        """
        state = self.encode(src_ids)
        logits = self.decode(tgt_in, state)
        use = rows if rows is not None else list(range(len(tgt_in)))
        total = None
        for t in use:
            step = cross_entropy(logits[t], [tgt_out[t]])
            total = step if total is None else add(total, step)
        if total is None:
            return cross_entropy(logits[0], [tgt_out[0]])
        return scale(total, 1.0 / len(use))

    def generate(self, src_ids: list[int], bos: int, eos: int,
                 max_len: int | None = None) -> list[int]:
        """Greedy decoding: feed each predicted token back in."""
        state = self.encode(src_ids)
        out = [bos]
        token = bos
        for _ in range(min(max_len or self.cfg.max_len, self.cfg.max_len) - 1):
            h, c = self.cell.step(embedding(self.emb, [token]), state)
            state = (h, c)
            row = self.out(h).data[0]
            token = int(np.argmax(row))
            out.append(token)
            if token == eos:
                break
        return out

    def params(self):
        return [self.emb] + self.cell.params() + self.out.params()

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({
            "kind": "lstm",
            "config": self.cfg.__dict__,
            "src_vocab": self.src_vocab, "tgt_vocab": self.tgt_vocab,
            "emb": self.emb.data.tolist(),
            "cell": self.cell.state(),
            "out": self.out.state()}))

    @classmethod
    def load(cls, path: str | Path) -> "LSTMSeq2Seq":
        d = json.loads(Path(path).read_text())
        if d.get("kind") != "lstm":
            raise ValueError(f"{path} does not hold an LSTM model")
        m = cls(d["src_vocab"], d["tgt_vocab"], RNNConfig(**d["config"]))
        m.emb.data = np.asarray(d["emb"], dtype=np.float64)
        m.cell.load(d["cell"])
        m.out.load(d["out"])
        return m
