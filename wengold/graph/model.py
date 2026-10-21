"""The design dependency graph.

One graph spans the design, the verification environment and the runs. Nodes are
artifacts (RTL modules, register-map entries, tests, assertions, coverage
points, runs, requirements, clock/reset roots, CDC crossings). Edges are typed
dependencies between them.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class NodeKind(str, Enum):
    RTL = "rtl"
    REGMAP = "regmap"
    TEST = "test"
    ASSERTION = "assertion"
    COVERAGE = "coverage"
    RUN = "run"
    REQUIREMENT = "requirement"
    CLOCK = "clock"
    RESET = "reset"
    CDC = "cdc"


class EdgeKind(str, Enum):
    DRIVES = "drives"          # src influences dst's behaviour
    INSTANTIATES = "instantiates"
    VERIFIES = "verifies"      # a test/assertion verifies a design node
    COVERS = "covers"
    TRACES_TO = "traces_to"    # requirement -> test/coverage
    CLOCKED_BY = "clocked_by"
    RESET_BY = "reset_by"
    CROSSES = "crosses"        # CDC
    UNKNOWN = "unknown"        # dependency we cannot yet resolve -> kernel says UNKNOWN


@dataclass(frozen=True)
class Node:
    id: str
    kind: NodeKind
    path: str | None = None
    content_hash: str | None = None
    meta: dict = field(default_factory=dict)

    @staticmethod
    def fingerprint(content: str) -> str:
        return "sha256:" + hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    kind: EdgeKind = EdgeKind.DRIVES


@dataclass
class DesignGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    # ---- construction -------------------------------------------------
    def add_node(self, node: Node) -> Node:
        self.nodes[node.id] = node
        return node

    def add_edge(self, src: str, dst: str, kind: EdgeKind = EdgeKind.DRIVES) -> None:
        self.edges.append(Edge(src, dst, kind))

    # ---- queries ------------------------------------------------------
    def out_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.src == node_id]

    def in_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.dst == node_id]

    def ancestors(self, node_id: str) -> set[str]:
        """Everything `node_id` depends on (upstream), following edges backwards."""
        seen, stack = set(), [node_id]
        while stack:
            cur = stack.pop()
            for e in self.in_edges(cur):
                if e.src not in seen:
                    seen.add(e.src)
                    stack.append(e.src)
        return seen

    def descendants(self, node_id: str) -> set[str]:
        seen, stack = set(), [node_id]
        while stack:
            cur = stack.pop()
            for e in self.out_edges(cur):
                if e.dst not in seen:
                    seen.add(e.dst)
                    stack.append(e.dst)
        return seen

    def nodes_of(self, kind: NodeKind) -> Iterable[Node]:
        return (n for n in self.nodes.values() if n.kind == kind)
