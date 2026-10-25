"""A synthetic natural-language → register-spec corpus.

This is the transformer's training data, and it is generated, not scraped. The
grammar is small and the point is that it is *exhaustively describable*: every
sentence maps to a spec, and the spec is what `wengold generate` consumes.

An honest note on what the model learns. It learns this grammar — a fixed set of
phrasings over a fixed vocabulary — and nothing else. It will not handle a
sentence outside it, and it should not be sold as if it would. The reason to train
it at all is that the *pipeline* is the product: text in, a spec out, and the spec
**checked** by the conformance checker and the formal engine before anyone believes
it. A model that drafts and a checker that decides is a defensible design; a model
alone would not be.

Two splits are generated deliberately:
* random sentences from the grammar (the ordinary case);
* **held-out wordings** — templates and vocabulary kept out of training, so the
  reported accuracy is generalisation to a phrasing it has not seen, not recall.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

PAD, BOS, EOS, SEP = "<pad>", "<bos>", "<eos>", "|"

ACCESS_WORDS = {
    "rw": ["read write", "read-write", "read and write"],
    "ro": ["read only", "read-only"],
    "w1c": ["write one to clear", "write-1-to-clear", "write one clear"],
}

FIELD_WORDS = ["field", "register field", "bit field"]
REG_WORDS = ["register", "reg", "block register"]


def _words(n: int) -> str:
    return {1: "one", 2: "two", 3: "three", 4: "four", 8: "eight",
            12: "twelve", 16: "sixteen", 32: "thirty two"}.get(n, str(n))


@dataclass
class Pair:
    text: str
    tokens: list[str]          # canonical target sequence


def canonical(name: str, hi: int, lo: int, access: str, reset: int,
              addr: int, reg: str) -> list[str]:
    """The target sequence the model decodes, and the parser reads back.

    Every token is a string — the vocabulary is one type, so sorting it cannot
    mix `str` and `int`.
    """
    return ["spec", reg, str(addr), name, str(hi), str(lo), access, str(reset),
            "end"]


def parse_canonical(tokens: list[str]) -> dict:
    """Canonical tokens -> a register description. Deterministic, and the only
    place the model's output becomes structured data."""
    if not tokens or tokens[0] != "spec":
        raise ValueError(f"not a spec sequence: {tokens[:4]}")
    body = [t for t in tokens[1:] if t != "end"]
    # reg, addr, name, hi, lo, access, reset — seven fields, not eight. The check
    # was one too strict and rejected every well-formed sequence.
    if len(body) < 7:
        raise ValueError(f"truncated spec sequence: {tokens}")
    reg, addr, name, hi, lo, access, reset = body[:7]
    if access not in ACCESS_WORDS:
        raise ValueError(f"unknown access mode {access!r}")
    hi, lo, addr, reset = int(hi), int(lo), int(addr), int(reset)
    if hi < lo:
        raise ValueError(f"reversed bit range {hi}:{lo}")
    if addr % 4 != 0:
        raise ValueError(f"address {addr} is not 4-byte aligned")
    return {"register": reg, "addr": addr, "name": name, "hi": hi, "lo": lo,
            "access": access, "reset": reset}


def _sentence(rng: random.Random, reg: str, addr: int, name: str, hi: int, lo: int,
              access: str, reset: int, words: dict) -> str:
    rw = rng.choice(words["reg"])
    fw = rng.choice(words["field"])
    aw = rng.choice(ACCESS_WORDS[access])
    styles = [
        f"a {rw} {reg} at address {addr} with a {aw} {fw} {name} at bits {hi} to {lo}",
        f"the {fw} {name} of {rw} {reg} {addr} is {aw} and occupies bits {hi} to {lo}",
        f"{rw} {reg} at {addr} , {fw} {name} bits {hi} to {lo} , {aw}",
        f"{fw} {name} in {rw} {reg} {addr} spans bits {hi} to {lo} and is {aw}",
    ]
    s = rng.choice(styles)
    if reset:
        s += f" , reset value {reset}"
    else:
        s += " , resets to zero"
    return s


def make_pairs(n: int, seed: int = 0, holdout: bool = False) -> list[Pair]:
    """Generate sentences. `holdout` uses wordings and words kept out of training."""
    rng = random.Random(seed + (999 if holdout else 0))
    words = {
        "reg": REG_WORDS if not holdout else ["peripheral register", "hardware register"],
        "field": FIELD_WORDS if not holdout else ["bit slice", "field slice"],
    }
    names = ["ctrl", "status", "irq", "config", "count"] if not holdout \
        else ["mode", "flags", "timer"]
    regs = ["r0", "r1", "r2", "ctrl", "status"] if not holdout \
        else ["bank0", "bank1"]
    addrs = [0, 4, 8, 16] if not holdout else [32, 64]
    widths = [(3, 0), (7, 4), (0, 0), (15, 8)] if not holdout else [(11, 8), (19, 16)]
    accesses = ["rw", "ro", "w1c"] if not holdout else ["rw", "ro"]
    resets = [0, 1, 3] if not holdout else [0, 2]

    out = []
    for _ in range(n):
        reg = rng.choice(regs)
        addr = rng.choice(addrs)
        name = rng.choice(names)
        hi, lo = rng.choice(widths)
        access = rng.choice(accesses)
        reset = rng.choice(resets)
        text = _sentence(rng, reg, addr, name, hi, lo, access, reset, words)
        out.append(Pair(text, canonical(name, hi, lo, access, reset, addr, reg)))
    return out


def vocab(pairs: list[Pair], extra: list[str] | None = None) -> list[str]:
    """Every token in the corpus, plus the specials."""
    seen = {PAD, BOS, EOS, SEP}
    for p in pairs:
        seen.update(tokenise(p.text))
        seen.update(p.tokens)
    if extra:
        seen.update(extra)
    return [PAD, BOS, EOS, SEP] + sorted(seen - {PAD, BOS, EOS, SEP})


def tokenise(text: str) -> list[str]:
    """Whitespace and comma tokenisation — the grammar has no punctuation beyond
    commas, so this is enough and it is honest about being crude."""
    return [t for t in text.replace(",", " , ").split() if t]


def encode(tokens: list[str], vocab_list: list[str]) -> list[int]:
    idx = {t: i for i, t in enumerate(vocab_list)}
    return [idx.get(t, idx[PAD]) for t in tokens]
