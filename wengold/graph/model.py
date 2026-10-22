"""The design dependency graph.

One graph spans the design, the verification environment and the runs. Nodes are
artifacts (RTL modules, packages, files, register-map entries, tests, assertions,
coverage points, runs, requirements, clock/reset roots, CDC crossings). Edges
are typed dependencies between them.

The graph also carries a *completeness* state. A graph built from an incomplete
elaboration — an unresolved include, an instantiation whose module is never
defined, an unevaluated `ifdef` — is marked, and the kernel refuses to return
VALID for anything downstream of an unresolved node. Missing dependencies must
never preserve evidence.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class NodeKind(str, Enum):
    RTL = "rtl"
    PACKAGE = "package"
    FILE = "file"
    PARAM = "param"
    REGMAP = "regmap"
    TEST = "test"
    ASSERTION = "assertion"
    COVERAGE = "coverage"
    RUN = "run"
    REQUIREMENT = "requirement"
    CLOCK = "clock"
    RESET = "reset"
    CDC = "cdc"
    CONSTRAINT = "constraint"
    ASSUMPTION = "assumption"
    GUARANTEE = "guarantee"


class EdgeKind(str, Enum):
    DRIVES = "drives"          # src influences dst's behaviour
    INSTANTIATES = "instantiates"
    VERIFIES = "verifies"      # a test/assertion verifies a design node
    COVERS = "covers"
    TRACES_TO = "traces_to"    # requirement -> test/coverage
    CLOCKED_BY = "clocked_by"
    RESET_BY = "reset_by"
    CROSSES = "crosses"        # CDC
    INCLUDES = "includes"      # a source file includes another
    IMPORTS = "imports"        # a module imports a package
    PARAMETERIZES = "parameterizes"  # a parameter feeds a module
    DEFINED_IN = "defined_in"  # a module is defined in a file
    GENERATES = "generates"    # a generate block contributes to a module
    CONSTRAINED_BY = "constrained_by"
    ASSUMES = "assumes"        # a block/result assumes a condition
    GUARANTEES = "guarantees"  # a block/result guarantees a condition
    UNKNOWN = "unknown"        # dependency we cannot yet resolve -> kernel says UNKNOWN


@dataclass(frozen=True)
class Node:
    id: str
    kind: NodeKind
    path: str | None = None
    content_hash: str | None = None
    resolved: bool = True          # False when elaboration could not pin this down
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
    # Graph-level completeness. `approximate` is set when the whole graph was
    # built without a full elaboration pass (e.g. the regex fallback), so the
    # kernel treats a would-be VALID as UNKNOWN.
    approximate: bool = False
    notes: list[str] = field(default_factory=list)

    # ---- construction -------------------------------------------------
    def add_node(self, node: Node) -> Node:
        existing = self.nodes.get(node.id)
        if existing is not None:
            # Never upgrade an unresolved node back to resolved by accident.
            if not node.resolved or not existing.resolved:
                node = Node(node.id, node.kind, node.path, node.content_hash,
                            resolved=existing.resolved and node.resolved,
                            meta={**existing.meta, **node.meta})
        self.nodes[node.id] = node
        return node

    def add_edge(self, src: str, dst: str, kind: EdgeKind = EdgeKind.DRIVES) -> None:
        self.edges.append(Edge(src, dst, kind))

    def mark_unresolved(self, node_id: str, reason: str = "") -> None:
        """Record that a node's dependencies could not be fully resolved."""
        node = self.nodes.get(node_id)
        if node is not None:
            meta = dict(node.meta)
            if reason:
                meta.setdefault("unresolved_reasons", []).append(reason)
            self.nodes[node_id] = Node(node.id, node.kind, node.path,
                                       node.content_hash, resolved=False, meta=meta)
        if reason:
            self.notes.append(f"{node_id}: {reason}")

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

    def unresolved_nodes(self) -> set[str]:
        return {n.id for n in self.nodes.values() if not n.resolved}

    def completeness(self) -> dict:
        """A report the kernel and the CLI can act on."""
        unresolved = sorted(self.unresolved_nodes())
        issues = list(self.notes)
        return {
            "complete": not unresolved and not self.approximate,
            "approximate": self.approximate,
            "unresolved": unresolved,
            "issues": issues,
        }
