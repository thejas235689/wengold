"""Does generative stimulus reach states the current tests miss?

The yardstick, and why it is fair.

**Ground truth is exact.** The formal front-end parses a design into a transition
function, so the set of reachable states can be enumerated by breadth-first search.
No estimate, no coverage proxy: the state space of the design below is four states
and the engine knows all four.

**The task is honest.** The corpus given to the models reaches the *middle* of a
passcode chain and never the end — it contains `5` then `7`, and never `9`. Nothing
in the corpus demonstrates the goal. So the question is the interesting one: can a
generative model learn the structure of a partial success well enough to complete
it, without ever having seen a success?

**The baseline is the right one.** Random sampling with the same budget. If a model
cannot beat that, it earns nothing, and this file says so.

The design:

    stage 0 --key==5--> stage 1 --key==7--> stage 2 --key==9--> stage 3 (unlock)

A random sequence of 12 keys hits the full chain about once in 4,000 tries.
"""
from __future__ import annotations

import random

from ..formal.rtl_model import parse_module, to_model

__all__ = ["PASSCODE", "reachable_states", "states_visited", "build_corpus",
           "benchmark"]

PASSCODE = """
module passcode(
  input logic clk,
  input logic rst_n,
  input logic [3:0] key,
  output logic unlock,
  output logic [1:0] stage
);
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      stage <= 2'd0;
      unlock <= 1'b0;
    end else begin
      if (stage == 2'd0 && key == 4'd5) stage <= 2'd1;
      else if (stage == 1 && key == 4'd7) stage <= 2'd2;
      else if (stage == 2 && key == 4'd9) begin
        stage <= 2'd3;
        unlock <= 1'b1;
      end else stage <= 2'd0;
    end
  end
endmodule
"""

STEPS = 12
WIDTH = 4


def _model(sv_text: str = PASSCODE):
    return to_model(parse_module(sv_text))


def reachable_states(sv_text: str = PASSCODE, cap: int = 5000) -> set:
    """Every state the design can reach, by breadth-first search."""
    model = _model(sv_text)
    start = tuple(sorted(model.state0.items()))
    seen = {start}
    frontier = [dict(model.state0)]
    while frontier and len(seen) < cap:
        nxt = []
        for state in frontier:
            for _inp, succ in model.successors(state):
                key = tuple(sorted(succ.items()))
                if key not in seen:
                    seen.add(key)
                    nxt.append(succ)
        frontier = nxt
    return seen


def states_visited(sequences, sv_text: str = PASSCODE) -> set:
    """The states a set of input sequences actually drives the design through.

    `rst_n` is held high: a reset in the middle of a stimulus sequence would hide
    exactly the behaviour being measured.
    """
    model = _model(sv_text)
    visited = set()
    for seq in sequences:
        state = dict(model.state0)
        for value in seq:
            state = model.step(state, {"rst_n": 1, "key": int(value)})
            visited.add(tuple(sorted(state.items())))
    return visited


def _reaches_unlock(seq, sv_text: str = PASSCODE) -> bool:
    return _deepest(seq, sv_text) >= 3


def _deepest(seq, sv_text: str = PASSCODE) -> int:
    """The furthest stage a sequence reaches (0..3)."""
    model = _model(sv_text)
    state = dict(model.state0)
    best = 0
    for value in seq:
        state = model.step(state, {"rst_n": 1, "key": int(value)})
        best = max(best, state.get("stage", 0))
    return best


def build_corpus(n: int = 300, seed: int = 0) -> list[list[int]]:
    """Stimulus that reaches stage 2 and never stage 3.

    Each sequence contains `5` then `7` early, then arbitrary keys **with `9`
    excluded entirely**. That is the honest partial success: the chain is
    half-solved, and the symbol that would finish it appears nowhere in the data.
    A first version of this drew the rest uniformly and so leaked `9`s — the corpus
    completed the chain itself, which made the test meaningless.
    """
    rng = random.Random(seed)
    allowed = [k for k in range(16) if k != 9]
    out = []
    for _ in range(n):
        start = rng.randint(0, 3)
        seq = [rng.choice(allowed) for _ in range(STEPS)]
        seq[start] = 5
        if start + 1 < STEPS:
            seq[start + 1] = 7
        out.append(seq)
    return out


def _random_sequences(n: int, seed: int = 1) -> list[list[int]]:
    rng = random.Random(seed)
    return [[rng.randrange(16) for _ in range(STEPS)] for _ in range(n)]


def benchmark(samples: int = 200, epochs: int = 150, seed: int = 0,
              verbose: bool = True) -> dict:
    """Train all three, sample, and score against random and against the corpus."""
    from .generative import GAN, VAE, Diffusion

    corpus = build_corpus(300, seed)
    reach = reachable_states()
    rows = []

    def score(name, sequences):
        visited = states_visited(sequences)
        n = max(len(sequences), 1)
        unlocked = sum(1 for s in sequences if _reaches_unlock(s))
        stage2 = sum(1 for s in sequences if _deepest(s) >= 2)
        rows.append({"model": name, "samples": len(sequences),
                     "states_reached": len(visited & reach),
                     "of_states": len(reach),
                     "stage2": stage2, "stage2_rate": stage2 / n,
                     "unlocked": unlocked, "unlock_rate": unlocked / n})
        if verbose:
            print(f"    {name:22} states {len(visited & reach)}/{len(reach)}  "
                  f"reached stage2 {stage2:3}/{n} ({100 * stage2 / n:4.1f}%)  "
                  f"unlocked {unlocked:3} ({100 * unlocked / n:.1f}%)")

    if verbose:
        print(f"  reachable states: {len(reach)}   corpus: {len(corpus)} sequences "
              f"({STEPS} steps x {WIDTH} bits)")

    score("corpus (partial only)", corpus)
    score("random", _random_sequences(samples, seed + 1))

    for name, cls in (("VAE", VAE), ("GAN", GAN), ("diffusion", Diffusion)):
        if verbose:
            print(f"  training {name}...", flush=True)
        model = cls(steps=STEPS, width=WIDTH, seed=seed)
        model.fit(corpus, epochs=epochs)
        score(name, model.sample(samples))

    return {"reachable": len(reach), "corpus": len(corpus), "rows": rows}
