"""Singular configurations of a dependency graph.

The robotics vocabulary in the request — damped least squares, singular value
filtering, output twist screws, trajectory planning through singular
configurations — is about **Jacobians losing rank**: a configuration where a small
joint motion produces an unbounded end-effector motion, so the controller must be
damped or the path re-planned.

A dependency graph has the same failure mode, and it is not a metaphor. Consider the
"Jacobian" that maps *which block changed* to *which evidence is now void*. At most
configurations it is well behaved: change a leaf, a handful of results go in doubt.
At a **singular configuration** — a block that nearly everything instantiates — one
change voids almost the entire evidence set, and the cost of being current is the
whole regression.

So this module answers three questions a verification lead actually asks:

* `blast_radius(graph, node)` — how many blocks a change here transitively voids.
* `conditioning(graph)` — the ratio of the worst blast radius to the median. A high
  number means the design is **ill-conditioned for evidence invalidation**: a small
  change buys an enormous amount of re-verification.
* `damping(graph, node)` — the DLS analogue. You cannot make a singular node
  non-singular, but you can **isolate** it behind a stub boundary, which caps how
  far a change propagates. `damping` reports what that isolation would buy.

What this is not: a solver for robot inverse kinematics, and it does not pretend to
be. `wavelet` and `phase unwrapping` are signal-processing tools with no signal
here, and `output twist screws` is screw theory with no screws. They are named in
the release notes as declined rather than quietly omitted.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from .model import NodeKind

__all__ = ["Singularity", "blast_radius", "singular_nodes", "conditioning",
           "damping"]


@dataclass
class Singularity:
    node: str
    blast_radius: int
    total_blocks: int

    @property
    def fraction(self) -> float:
        return self.blast_radius / max(self.total_blocks, 1)

    def render(self) -> str:
        return (f"  {self.node:<34}{self.blast_radius:>6} blocks "
                f"({self.fraction:>5.1%} of the design)")


def _blocks(graph) -> set[str]:
    return {n for n, d in graph.nodes.items() if d.kind is NodeKind.RTL}


def blast_radius(graph, node: str) -> int:
    """How many RTL blocks a change at `node` transitively reaches.

    This is the size of the set that must be re-established, which is what a
    singular configuration makes unbounded.
    """
    blocks = _blocks(graph)
    if node not in graph.nodes:
        return 0
    # DESCENDANTS, not ancestors. The edge convention is `add_edge(child, parent,
    # INSTANTIATES)`, so `ancestors()` walks *into* the block and `descendants()`
    # walks out to what instantiates it — which is what a change propagates to.
    # Getting this backwards made `neorv32_tb` look singular (it instantiates 76
    # blocks) when the singular nodes are the leaf primitives that everything
    # instantiates.
    reach = graph.rtl_descendants(node) if hasattr(graph, "rtl_descendants") else set()
    if not reach:
        reach = graph.descendants(node)
    return len(set(reach) & blocks)


def singular_nodes(graph, threshold: float = 0.25) -> list[Singularity]:
    """Nodes whose change voids at least `threshold` of the design.

    Sorted worst first. The threshold is a fraction of all blocks, so the answer is
    scale-free: 25% of a 20-block core and 25% of an 880-block SoC both qualify.
    """
    blocks = _blocks(graph)
    total = len(blocks)
    if not total:
        return []
    out = []
    for n in blocks:
        r = blast_radius(graph, n)
        if total and r / total >= threshold:
            out.append(Singularity(n, r, total))
    return sorted(out, key=lambda s: (-s.blast_radius, s.node))


def conditioning(graph) -> dict:
    """How ill-conditioned the design is for evidence invalidation.

    `condition_number` = worst blast radius / median blast radius. A value near 1
    means every block is equally expensive to change, which is the well-conditioned
    case. A large value means a few blocks dominate and one careless change costs
    the whole regression.
    """
    blocks = sorted(_blocks(graph))
    if not blocks:
        return {"condition_number": 1.0, "worst": None, "median": 0.0,
                "blocks": 0, "verdict": "empty graph"}
    radii = [blast_radius(graph, b) for b in blocks]
    worst_i = max(range(len(blocks)), key=lambda i: radii[i])
    median = statistics.median(radii) or 0.0
    cn = (radii[worst_i] / median) if median else float(radii[worst_i])
    if cn < 3:
        verdict = "well conditioned — no block dominates the evidence set"
    elif cn < 10:
        verdict = "moderate — a few blocks carry most of the invalidation cost"
    else:
        verdict = ("ill conditioned — one block's change voids a large share of "
                   "the design; isolate it or accept whole-design re-verification")
    return {"condition_number": cn, "worst": blocks[worst_i],
            "worst_radius": radii[worst_i], "median": median,
            "blocks": len(blocks), "verdict": verdict}


def damping(graph, node: str, stubbed: set[str] | None = None) -> dict:
    """The DLS analogue: what does isolating this node behind a stub buy?

    Damping in robotics trades accuracy for stability near a singularity. Here the
    trade is the same shape: a stub boundary cuts the propagation path, so a change
    inside the isolated subtree no longer voids evidence outside it. The report says
    how much of the blast radius the stub removes — and what it costs, which is that
    the stub's own behaviour is no longer verified by the real thing.
    """
    before = blast_radius(graph, node)
    total = len(_blocks(graph))
    # Stubbing means the boundary *is* the stub: a change inside the real block no
    # longer propagates to its instantiators, because they now bind to the stub.
    # So the saving is the whole blast radius — and it is not free.
    after = 0 if (stubbed is None or node in stubbed) else before
    return {"node": node, "before": before, "after": after,
            "removed": before - after, "total_blocks": total,
            "fraction_before": before / max(total, 1),
            "fraction_after": after / max(total, 1),
            "cost": ("every instantiator now binds to the stub, so a change inside "
                     "the real block no longer propagates — and the real block is "
                     "no longer verified through them. Evidence about it becomes "
                     "UNKNOWN rather than VALID: an honest trade, not a free one")}
