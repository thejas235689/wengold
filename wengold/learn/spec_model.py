"""Training and scoring the seq2seq spec model.

The model is in `transformer.py`, the corpus in `spec_text.py`; this joins them and
is the only place that knows about both.

Scoring is deliberately two numbers, because one of them is honest on its own and
the other is not:

* **token accuracy** — how many target tokens are right. Flatters the model: the
  canonical sequence is mostly boilerplate (`spec`, `end`, the register name), so
  a model that gets the boilerplate and nothing else still scores well.
* **exact match** — the whole sequence right, which is the only thing that yields a
  usable spec. This is the number to quote.
"""
from __future__ import annotations

from .autograd import backward, sgd_step
from .spec_text import (BOS, EOS, PAD, encode, parse_canonical, tokenise)
from .transformer import Config, Transformer

__all__ = ["build_vocab", "train_model", "evaluate", "predict_spec"]


def build_vocab(pairs) -> list[str]:
    from .spec_text import vocab
    return vocab(pairs)


def train_model(pairs, vocab_list, cfg: Config | None = None, epochs: int = 60,
                lr: float = 0.05, seed: int = 0, log_every: int = 0):
    """Teacher-forced training, one example at a time."""
    cfg = cfg or Config()
    model = Transformer(len(vocab_list), len(vocab_list), cfg, seed=seed)
    params = model.params()
    history = []
    for epoch in range(epochs):
        total = 0.0
        order = list(pairs)
        for p in order:
            src = encode(tokenise(p.text), vocab_list)
            tgt_in = encode([BOS] + p.tokens, vocab_list)
            tgt_out = encode(p.tokens + [EOS], vocab_list)
            rows = list(range(len(p.tokens) + 1))
            for t in params:
                t.zero_grad()
            loss = model.loss(src, tgt_in, tgt_out, rows)
            backward(loss)
            sgd_step(params, lr)
            total += float(loss.data[0, 0])
        history.append(total / max(len(pairs), 1))
        if log_every and (epoch + 1) % log_every == 0:
            print(f"    epoch {epoch + 1:3}/{epochs}  mean loss {history[-1]:.3f}")
    return model, history


def evaluate(model, pairs, vocab_list) -> dict:
    bos, eos = vocab_list.index(BOS), vocab_list.index(EOS)
    exact = 0
    tokens_right = tokens_total = 0
    for p in pairs:
        src = encode(tokenise(p.text), vocab_list)
        out = model.generate(src, bos, eos)
        got = [vocab_list[i] for i in out[1:]]
        want = p.tokens
        if got and got[-1] == EOS:
            got = got[:-1]
        if got == want:
            exact += 1
        for a, b in zip(got, want):
            tokens_total += 1
            tokens_right += (a == b)
        tokens_total += abs(len(want) - len(got))
    n = max(len(pairs), 1)
    return {"n": len(pairs), "exact": exact / n,
            "exact_count": exact,
            "token_accuracy": tokens_right / max(tokens_total, 1)}


def predict_spec(model, text: str, vocab_list, unknown_frac: float = 0.34) -> dict:
    """Text -> a register description.

    Raises if the sentence is mostly words the model never saw, and raises if the
    model produced something the parser cannot read. Both are normal outcomes: a
    model that drafts is allowed to be wrong, and the caller decides what to do.

    The unknown-word guard matters more than it looks. An unknown token maps to
    `<pad>`, so a sentence outside the vocabulary arrives as padding — and the
    model will happily decode *something* from a row of pads. Refusing the input
    is honest; decoding a spec out of noise is not.
    """
    from .spec_text import PAD

    words = tokenise(text)
    known = {t for t in vocab_list}
    unknown = [w for w in words if w not in known]
    if words and len(unknown) / len(words) > unknown_frac:
        raise ValueError(
            f"sentence is outside the trained vocabulary: "
            f"{len(unknown)} of {len(words)} words are unknown "
            f"(e.g. {', '.join(unknown[:3])})")
    src = encode(tokenise(text), vocab_list)
    out = model.generate(src, vocab_list.index(BOS), vocab_list.index(EOS))
    tokens = [vocab_list[i] for i in out[1:]]
    if tokens and tokens[-1] == EOS:
        tokens = tokens[:-1]
    return parse_canonical(tokens)
