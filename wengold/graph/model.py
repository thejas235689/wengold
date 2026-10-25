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
    # The input file set, so completeness can say how much of the repository the
    # graph actually describes. Without it, `complete: True` is reported on a UVM
    # class library where 4 of 89 files contributed anything at all.
    file_set: set[str] = field(default_factory=set)

    # ---- construction -------------------------------------------------
    # Ancestor and descendant sets are asked for over and over — once per result
    # by the kernel, once per block by the learners. Recomputing them each time is
    # quadratic-ish and made a single RL instance on OpenTitan take 29 seconds.
    _anc_cache: dict[str, set[str]] = field(default_factory=dict, repr=False)
    _des_cache: dict[str, set[str]] = field(default_factory=dict, repr=False)
    # Adjacency, so out_edges/in_edges do not scan the whole edge list. They were
    # called 41,527 times on one OpenTitan run and scanned 10,710 edges each —
    # 21.8 of the 22.4 seconds went into that one list comprehension.
    _out_idx: dict[str, list] = field(default_factory=dict, repr=False)
    _in_idx: dict[str, list] = field(default_factory=dict, repr=False)

    def add_node(self, node: Node) -> Node:
        self._anc_cache.clear()
        self._des_cache.clear()
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
        edge = Edge(src, dst, kind)
        self.edges.append(edge)
        self._out_idx.setdefault(src, []).append(edge)
        self._in_idx.setdefault(dst, []).append(edge)
        self._anc_cache.clear()
        self._des_cache.clear()

    def rebuild_index(self) -> None:
        """Rebuild the adjacency index after assigning `edges` directly."""
        self._out_idx, self._in_idx = {}, {}
        for e in self.edges:
            self._out_idx.setdefault(e.src, []).append(e)
            self._in_idx.setdefault(e.dst, []).append(e)
        self._anc_cache.clear()
        self._des_cache.clear()

    def mark_unresolved(self, node_id: str, reason: str = "", *,
                        kind: str | None = None, file: str | None = None,
                        line: int | None = None, subject: str | None = None,
                        construct: str | None = None) -> None:
        """Record that a node's dependencies could not be fully resolved.

        The reason is stored twice: as prose for a human reading the graph, and
        structured (kind, file, line, subject, construct) so the cause can be
        analysed rather than only printed.
        """
        node = self.nodes.get(node_id)
        if node is not None:
            meta = dict(node.meta)
            if reason:
                meta.setdefault("unresolved_reasons", []).append(reason)
                meta.setdefault("unresolved", []).append({
                    "kind": kind or "unresolved",
                    "reason": reason,
                    "file": file,
                    "line": line,
                    "subject": subject,
                    "construct": construct,
                })
            self.nodes[node_id] = Node(node.id, node.kind, node.path,
                                       node.content_hash, resolved=False, meta=meta)
        if reason:
            self.notes.append(f"{node_id}: {reason}")

    # ---- queries ------------------------------------------------------
    def out_edges(self, node_id: str) -> list[Edge]:
        return list(self._out_idx.get(node_id, ()))

    def in_edges(self, node_id: str) -> list[Edge]:
        return list(self._in_idx.get(node_id, ()))

    def ancestors(self, node_id: str) -> set[str]:
        """Everything `node_id` depends on (upstream), following edges backwards.

        Cached, and a copy is returned so a caller cannot corrupt the cache.
        """
        if node_id in self._anc_cache:
            return set(self._anc_cache[node_id])
        seen, stack = set(), [node_id]
        while stack:
            cur = stack.pop()
            for e in self.in_edges(cur):
                if e.src not in seen:
                    seen.add(e.src)
                    stack.append(e.src)
        self._anc_cache[node_id] = seen
        return set(seen)

    def descendants(self, node_id: str) -> set[str]:
        if node_id in self._des_cache:
            return set(self._des_cache[node_id])
        seen, stack = set(), [node_id]
        while stack:
            cur = stack.pop()
            for e in self.out_edges(cur):
                if e.dst not in seen:
                    seen.add(e.dst)
                    stack.append(e.dst)
        self._des_cache[node_id] = seen
        return set(seen)

    def _rtl_only(self, ids: set[str]) -> set[str]:
        return {i for i in ids
                if (n := self.nodes.get(i)) is not None and n.kind is NodeKind.RTL}

    def rtl_ancestors(self, node_id: str) -> set[str]:
        """Ancestors that are blocks.

        `ancestors` follows every edge kind, so it also collects the PARAM and
        PACKAGE nodes hanging off a block — 664 parameters on neorv32 alone. That
        is right for the kernel (a parameter change does invalidate) and wrong
        for "how many blocks sit below this one", which is what the display and
        the ML features mean.
        """
        return self._rtl_only(self.ancestors(node_id))

    def rtl_descendants(self, node_id: str) -> set[str]:
        return self._rtl_only(self.descendants(node_id))

    def nodes_of(self, kind: NodeKind) -> Iterable[Node]:
        return (n for n in self.nodes.values() if n.kind == kind)

    def unresolved_nodes(self) -> set[str]:
        return {n.id for n in self.nodes.values() if not n.resolved}

    def completeness(self) -> dict:
        """A report the kernel and the CLI can act on."""
        unresolved = sorted(self.unresolved_nodes())
        issues = list(self.notes)
        # How much of the file set produced a design unit. A UVM class library has
        # almost no modules, so every file parses and nothing is unresolved while
        # the graph describes 5% of the repository — `complete` alone reads as
        # reassurance it has not earned.
        contributing = {n.path for n in self.nodes.values()
                        if n.kind is not NodeKind.FILE and n.path}
        contributing &= self.file_set
        total = len(self.file_set)
        coverage = (len(contributing) / total) if total else 1.0
        if total and coverage < 0.5:
            issues.append(
                f"only {len(contributing)} of {total} file(s) contributed a design "
                f"unit ({coverage:.0%}) — most of this repository is not modules, "
                f"packages or interfaces, and the graph does not describe it")
        return {
            "complete": not unresolved and not self.approximate,
            "approximate": self.approximate,
            "unresolved": unresolved,
            "issues": issues,
            "files": total,
            "contributing_files": len(contributing),
            "file_coverage": coverage,
        }
