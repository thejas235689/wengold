"""A transformer, written out.

Scaled dot-product multi-head attention, a feed-forward block, encoder and decoder
stacks, learned positional embeddings — the architecture from *Attention Is All You
Need*, built on the autograd tape next door rather than imported.

**What it is.** A working seq2seq transformer that trains here, in seconds, on a
few hundred examples, and whose gradients are verified against finite differences.
It is small on purpose: d_model 32, two heads, one or two layers. Big enough to
learn a grammar; nowhere near a language model.

**What it is not.** It is not an LLM and it cannot be asked to "understand" a spec
in English. It learns the synthetic grammar in `spec_text.py` and nothing else, and
the product treats its output as a *draft to be checked* — the conformance checker
and the proof engine decide whether the spec is good, not the model. That division
is the point: a language model proposes, WENGOLD verifies.

**numpy is used for the arithmetic and nothing else** — no autodiff framework, no
layers, no optimiser. The tape, the attention, the blocks and the backward passes
are all in this package. Writing the matmuls as Python loops first made one
example take 217 ms; on numpy it is 8 ms, which is the difference between a model
that can be trained in a tool call and one that cannot.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .autograd import (Tensor, add, add_bias, backward, cross_entropy, embedding,
                       layer_norm, mask_fill, matmul, relu, scale, softmax,
                       transpose)

__all__ = ["Transformer", "Config"]


@dataclass
class Config:
    d_model: int = 32
    heads: int = 2
    enc_layers: int = 1
    dec_layers: int = 1
    d_ff: int = 64
    # must cover the longest sentence in the corpus; a shorter value used to
    # crash with an IndexError on the positional embedding
    max_len: int = 40

    @property
    def d_head(self) -> int:
        return self.d_model // self.heads


class Linear:
    """y = x W + b. The only parameterised primitive."""

    def __init__(self, n_in: int, n_out: int, seed: int):
        self.w = Tensor.randn(n_in, n_out, scale=1.0 / math.sqrt(n_in), seed=seed)
        self.b = Tensor([[0.0] * n_out], True)

    def __call__(self, x: Tensor) -> Tensor:
        return add_bias(matmul(x, self.w), self.b)

    def params(self):
        return [self.w, self.b]

    def state(self):
        # plain lists: json cannot serialise a numpy array
        return {"w": self.w.data.tolist(), "b": self.b.data.tolist()}

    def load(self, d):
        self.w.data = np.asarray(d["w"], dtype=np.float64)
        self.b.data = np.asarray(d["b"], dtype=np.float64)


class MultiHeadAttention:
    def __init__(self, cfg: Config, seed: int):
        self.cfg = cfg
        self.wq = Linear(cfg.d_model, cfg.d_model, seed)
        self.wk = Linear(cfg.d_model, cfg.d_model, seed + 1)
        self.wv = Linear(cfg.d_model, cfg.d_model, seed + 2)
        self.wo = Linear(cfg.d_model, cfg.d_model, seed + 3)

    def _split(self, x: Tensor, n: int) -> list[Tensor]:
        """(n, d_model) -> `heads` tensors of (n, d_head)."""
        width = self.cfg.d_head
        out = [Tensor(x.data[:, h * width:(h + 1) * width], x.requires_grad, (x,))
               for h in range(self.cfg.heads)]

        def _backward():
            if not x.requires_grad:
                return
            for h, head in enumerate(out):
                x.grad[:, h * width:(h + 1) * width] += head.grad
        for head in out:
            head._backward = _backward
        return out

    def _merge(self, heads: list[Tensor]) -> Tensor:
        width = self.cfg.d_head
        node = Tensor(np.concatenate([h.data for h in heads], axis=1),
                      any(h.requires_grad for h in heads), tuple(heads))

        def _backward():
            for h, head in enumerate(heads):
                if head.requires_grad:
                    head.grad += node.grad[:, h * width:(h + 1) * width]
        node._backward = _backward
        return node

    def __call__(self, query: Tensor, key: Tensor, value: Tensor,
                 causal: bool = False) -> Tensor:
        n_q = query.shape[0]
        n_k = key.shape[0]
        q_heads = self._split(self.wq(query), n_q)
        k_heads = self._split(self.wk(key), n_k)
        v_heads = self._split(self.wv(value), n_k)

        keep = None
        if causal:
            keep = [[j <= i for j in range(n_k)] for i in range(n_q)]

        outs = []
        for q, k, v in zip(q_heads, k_heads, v_heads):
            scores = scale(matmul(q, transpose(k)), 1.0 / math.sqrt(self.cfg.d_head))
            if keep is not None:
                scores = mask_fill(scores, keep)
            attn = softmax(scores)
            outs.append(matmul(attn, v))
        return self.wo(self._merge(outs))

    def params(self):
        return self.wq.params() + self.wk.params() + self.wv.params() + self.wo.params()

    def state(self):
        return [self.wq.state(), self.wk.state(), self.wv.state(), self.wo.state()]

    def load(self, d):
        for lin, st in zip([self.wq, self.wk, self.wv, self.wo], d):
            lin.load(st)


class FeedForward:
    def __init__(self, cfg: Config, seed: int):
        self.fc1 = Linear(cfg.d_model, cfg.d_ff, seed)
        self.fc2 = Linear(cfg.d_ff, cfg.d_model, seed + 1)

    def __call__(self, x: Tensor) -> Tensor:
        return self.fc2(relu(self.fc1(x)))

    def params(self):
        return self.fc1.params() + self.fc2.params()

    def state(self):
        return [self.fc1.state(), self.fc2.state()]

    def load(self, d):
        self.fc1.load(d[0])
        self.fc2.load(d[1])


class Block:
    """Pre-norm residual block: x = x + sublayer(ln(x))."""

    def __init__(self, cfg: Config, seed: int, kind: str):
        self.kind = kind
        self.ln1 = Tensor([[1.0] * cfg.d_model], True)
        self.ln1b = Tensor([[0.0] * cfg.d_model], True)
        self.attn = MultiHeadAttention(cfg, seed)
        self.ff = FeedForward(cfg, seed + 10)
        self.ln2 = Tensor([[1.0] * cfg.d_model], True)
        self.ln2b = Tensor([[0.0] * cfg.d_model], True)
        self.cross = MultiHeadAttention(cfg, seed + 20) if kind == "decoder" else None
        self.ln3 = Tensor([[1.0] * cfg.d_model], True) if kind == "decoder" else None
        self.ln3b = Tensor([[0.0] * cfg.d_model], True) if kind == "decoder" else None

    def __call__(self, x: Tensor, memory: Tensor | None = None) -> Tensor:
        # one normalisation, fed to q, k and v — three separate calls would be
        # mathematically the same and three times the work
        normed = layer_norm(x, self.ln1, self.ln1b)
        h = add(x, self.attn(normed, normed, normed,
                             causal=(self.kind == "decoder")))
        if self.kind == "decoder" and memory is not None and self.cross is not None:
            n = layer_norm(h, self.ln3, self.ln3b)
            h = add(h, self.cross(n, memory, memory))
        return add(h, self.ff(layer_norm(h, self.ln2, self.ln2b)))

    def params(self):
        out = [self.ln1, self.ln1b, self.ln2, self.ln2b]
        out += self.attn.params() + self.ff.params()
        if self.cross is not None:
            out += [self.ln3, self.ln3b] + self.cross.params()
        return out

    def state(self):
        return {"ln1": self.ln1.data.tolist(), "ln1b": self.ln1b.data.tolist(),
                "attn": self.attn.state(), "ff": self.ff.state(),
                "ln2": self.ln2.data.tolist(), "ln2b": self.ln2b.data.tolist(),
                "cross": self.cross.state() if self.cross else None,
                "ln3": self.ln3.data.tolist() if self.ln3 is not None else None,
                "ln3b": self.ln3b.data.tolist() if self.ln3b is not None else None}

    def load(self, d):
        self.ln1.data = np.asarray(d["ln1"], dtype=np.float64)
        self.ln1b.data = np.asarray(d["ln1b"], dtype=np.float64)
        self.ln2.data = np.asarray(d["ln2"], dtype=np.float64)
        self.ln2b.data = np.asarray(d["ln2b"], dtype=np.float64)
        self.attn.load(d["attn"])
        self.ff.load(d["ff"])
        if self.cross and d.get("cross"):
            self.cross.load(d["cross"])
            self.ln3.data = np.asarray(d["ln3"], dtype=np.float64)
            self.ln3b.data = np.asarray(d["ln3b"], dtype=np.float64)


class Transformer:
    """Encoder-decoder transformer over integer token ids."""

    def __init__(self, src_vocab: int, tgt_vocab: int, cfg: Config | None = None,
                 seed: int = 0):
        self.cfg = cfg or Config()
        self.src_vocab, self.tgt_vocab = src_vocab, tgt_vocab
        self.src_emb = Tensor.randn(src_vocab, self.cfg.d_model, seed=seed)
        self.tgt_emb = Tensor.randn(tgt_vocab, self.cfg.d_model, seed=seed + 100)
        self.pos_emb = Tensor.randn(self.cfg.max_len, self.cfg.d_model, seed=seed + 200)
        self.enc = [Block(self.cfg, seed + 300 + i * 50, "encoder")
                    for i in range(self.cfg.enc_layers)]
        self.dec = [Block(self.cfg, seed + 400 + i * 50, "decoder")
                    for i in range(self.cfg.dec_layers)]
        self.out = Linear(self.cfg.d_model, tgt_vocab, seed + 500)

    # -- forward ------------------------------------------------------------
    def _embed(self, ids: list[int], which: str) -> Tensor:
        table = self.src_emb if which == "src" else self.tgt_emb
        n = len(ids)
        if n > self.cfg.max_len:
            # refuse, rather than index past the positional embedding
            raise ValueError(
                f"sequence of {n} tokens exceeds max_len {self.cfg.max_len}")
        x = embedding(table, ids)
        return add(x, embedding(self.pos_emb, list(range(n))))

    def encode(self, src_ids: list[int]) -> Tensor:
        x = self._embed(src_ids, "src")
        for block in self.enc:
            x = block(x)
        return x

    def decode(self, tgt_ids: list[int], memory: Tensor) -> Tensor:
        x = self._embed(tgt_ids, "tgt")
        for block in self.dec:
            x = block(x, memory)
        return self.out(x)

    def loss(self, src_ids, tgt_in, tgt_out, rows=None) -> Tensor:
        memory = self.encode(src_ids)
        logits = self.decode(tgt_in, memory)
        return cross_entropy(logits, tgt_out, rows)

    # -- inference ----------------------------------------------------------
    def generate(self, src_ids: list[int], bos: int, eos: int,
                 max_len: int | None = None) -> list[int]:
        """Greedy decoding, no gradient — the graph is built and thrown away."""
        max_len = min(max_len or self.cfg.max_len, self.cfg.max_len)
        memory = self.encode(src_ids)
        out = [bos]
        for _ in range(max_len - 1):
            logits = self.decode(out, memory)
            row = logits.data[len(out) - 1]
            nxt = int(np.argmax(row))
            out.append(nxt)
            if nxt == eos:
                break
        return out

    # -- parameters ---------------------------------------------------------
    def params(self) -> list[Tensor]:
        out = [self.src_emb, self.tgt_emb, self.pos_emb] + self.out.params()
        for b in self.enc + self.dec:
            out += b.params()
        return out

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({
            "config": self.cfg.__dict__,
            "src_vocab": self.src_vocab, "tgt_vocab": self.tgt_vocab,
            "src_emb": self.src_emb.data.tolist(),
            "tgt_emb": self.tgt_emb.data.tolist(),
            "pos_emb": self.pos_emb.data.tolist(),
            "out": self.out.state(),
            "enc": [b.state() for b in self.enc],
            "dec": [b.state() for b in self.dec]}))

    @classmethod
    def load(cls, path: str | Path) -> "Transformer":
        d = json.loads(Path(path).read_text())
        cfg = Config(**d["config"])
        m = cls(d["src_vocab"], d["tgt_vocab"], cfg)
        m.src_emb.data = np.asarray(d["src_emb"], dtype=np.float64)
        m.tgt_emb.data = np.asarray(d["tgt_emb"], dtype=np.float64)
        m.pos_emb.data = np.asarray(d["pos_emb"], dtype=np.float64)
        m.out.load(d["out"])
        for blk, st in zip(m.enc, d["enc"]):
            blk.load(st)
        for blk, st in zip(m.dec, d["dec"]):
            blk.load(st)
        return m
