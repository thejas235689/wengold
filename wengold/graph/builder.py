"""Builds a DesignGraph from a project tree.

The builder is deliberately modular: each source of truth (RTL, register maps,
clock/reset definitions, the verification environment) contributes a sub-graph
and cross-edges. See `rtl_parser.py`, `regmap.py` and `cdc.py`.
"""
from __future__ import annotations

from .model import DesignGraph, EdgeKind, Node, NodeKind


class GraphBuilder:
    def __init__(self) -> None:
        self.graph = DesignGraph()

    def add_rtl(self, name: str, path: str, content: str, clocks=(), resets=()) -> Node:
        n = self.graph.add_node(
            Node(id=name, kind=NodeKind.RTL, path=path, content_hash=Node.fingerprint(content))
        )
        for clk in clocks:
            self.graph.add_node(Node(id=clk, kind=NodeKind.CLOCK))
            self.graph.add_edge(clk, name, EdgeKind.CLOCKED_BY)
        for rst in resets:
            self.graph.add_node(Node(id=rst, kind=NodeKind.RESET))
            self.graph.add_edge(rst, name, EdgeKind.RESET_BY)
        return n

    def instantiate(self, parent: str, child: str) -> None:
        self.graph.add_edge(child, parent, EdgeKind.INSTANTIATES)

    def add_test(self, name: str, verifies: list[str], covers: list[str] = ()) -> Node:
        self.graph.add_node(Node(id=name, kind=NodeKind.TEST))
        for v in verifies:
            self.graph.add_edge(v, name, EdgeKind.VERIFIES)
        for c in covers:
            self.graph.add_node(Node(id=c, kind=NodeKind.COVERAGE))
            self.graph.add_edge(c, name, EdgeKind.COVERS)
        return self.graph.nodes[name]

    def add_assertion(self, name: str, on: str) -> Node:
        self.graph.add_node(Node(id=name, kind=NodeKind.ASSERTION))
        self.graph.add_edge(on, name, EdgeKind.VERIFIES)
        return self.graph.nodes[name]

    def add_requirement(self, req: str, traces_to: list[str]) -> None:
        self.graph.add_node(Node(id=req, kind=NodeKind.REQUIREMENT))
        for t in traces_to:
            self.graph.add_edge(req, t, EdgeKind.TRACES_TO)

    def mark_uncertain(self, src: str, dst: str) -> None:
        """Record a dependency the builder could not resolve. The kernel treats
        any result downstream of it as UNKNOWN, never as a false pass."""
        self.graph.add_edge(src, dst, EdgeKind.UNKNOWN)

    def build(self) -> DesignGraph:
        return self.graph
