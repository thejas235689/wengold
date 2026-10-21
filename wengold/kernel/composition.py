"""Composition contracts.

A proven block does not automatically give a proven subsystem. Each block carries
assumptions (what it needs of its environment) and guarantees (what it provides).
When blocks are integrated, every assumption of the parent must be discharged by a
guarantee of a child; anything left unmet is reported, so a block proof is never
silently promoted into a subsystem proof.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..graph.model import DesignGraph, EdgeKind


@dataclass(frozen=True)
class BlockContract:
    block: str
    assumes: tuple[str, ...] = ()
    guarantees: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {"block": self.block, "assumes": list(self.assumes),
                "guarantees": list(self.guarantees)}


def unmet_assumptions(parent: BlockContract, child: BlockContract) -> tuple[str, ...]:
    """Parent assumptions the child does not guarantee."""
    have = set(child.guarantees)
    return tuple(a for a in parent.assumes if a not in have)


def check_pair(parent: BlockContract, child: BlockContract) -> list[str]:
    return [f"{parent.block} assumes '{a}' but {child.block} does not guarantee it"
            for a in unmet_assumptions(parent, child)]


def contracts_from_graph(graph: DesignGraph) -> dict[str, BlockContract]:
    """Read assumptions and guarantees off ASSUMES/GUARANTEES edges.

    An edge `X -> block` of kind ASSUMES means the block assumes X; of kind
    GUARANTEES means the block guarantees X.
    """
    assumes: dict[str, list[str]] = {}
    guarantees: dict[str, list[str]] = {}
    blocks = set()
    for e in graph.edges:
        if e.kind is EdgeKind.ASSUMES:
            assumes.setdefault(e.dst, []).append(e.src)
            blocks.add(e.dst)
        elif e.kind is EdgeKind.GUARANTEES:
            guarantees.setdefault(e.dst, []).append(e.src)
            blocks.add(e.dst)
    for n in graph.nodes.values():
        if n.kind.value in ("rtl", "test", "assertion"):
            blocks.add(n.id)
    return {b: BlockContract(b, tuple(sorted(assumes.get(b, []))),
                             tuple(sorted(guarantees.get(b, []))))
            for b in sorted(blocks)}


@dataclass
class CompositionReport:
    ok: bool
    issues: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "issues": self.issues}


def check_subsystem(graph: DesignGraph,
                    contracts: dict[str, BlockContract] | None = None) -> CompositionReport:
    """Check that every parent's assumptions are covered by its children.

    Integration edges are the graph's INSTANTIATES edges (`child -> parent`).
    """
    contracts = contracts or contracts_from_graph(graph)
    issues: list[dict] = []
    for e in graph.edges:
        if e.kind is not EdgeKind.INSTANTIATES:
            continue
        child_id, parent_id = e.src, e.dst
        parent = contracts.get(parent_id)
        child = contracts.get(child_id)
        if parent is None or child is None:
            continue
        unmet = unmet_assumptions(parent, child)
        if unmet:
            issues.append({"parent": parent_id, "child": child_id,
                           "unmet": list(unmet)})
    return CompositionReport(ok=not issues, issues=issues)
