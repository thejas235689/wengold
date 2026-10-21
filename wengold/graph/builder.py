"""Builds a DesignGraph from a project tree.

Two paths in:

* `build_from_files()` — the real one. It runs the elaborator over a file set
  (with an include search path) and adds the module, package, file, include,
  import and instantiation edges it resolves, plus UNKNOWN edges and unresolved
  markers for anything it cannot.
* the manual `add_*` helpers — used by the demo and by tests to construct a graph
  by hand.

Whenever the elaboration is incomplete the graph is marked, and the kernel
refuses to return VALID downstream of it.
"""
from __future__ import annotations

import re

from .elaborate import Elaborator, read_filelist
from .model import DesignGraph, EdgeKind, Node, NodeKind

CLK_RE = re.compile(r'\b(clk\w*|clock\w*)\b')
RST_RE = re.compile(r'\b(rst\w*|reset\w*|rst_n)\b')


class GraphBuilder:
    def __init__(self) -> None:
        self.graph = DesignGraph()

    # ---- manual construction (demo / tests) --------------------------
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

    def add_constraint(self, name: str, constrains: list[str]) -> None:
        self.graph.add_node(Node(id=name, kind=NodeKind.CONSTRAINT))
        for c in constrains:
            self.graph.add_edge(name, c, EdgeKind.CONSTRAINED_BY)

    def add_requirement(self, req: str, traces_to: list[str]) -> None:
        self.graph.add_node(Node(id=req, kind=NodeKind.REQUIREMENT))
        for t in traces_to:
            self.graph.add_edge(req, t, EdgeKind.TRACES_TO)

    def mark_uncertain(self, src: str, dst: str) -> None:
        """Record a dependency the builder could not resolve. The kernel treats
        any result downstream of it as UNKNOWN, never as a false pass."""
        self.graph.add_edge(src, dst, EdgeKind.UNKNOWN)

    # ---- elaboration-driven construction -----------------------------
    def build_from_files(self, files: dict[str, str],
                         include_dirs: list[str] | None = None) -> DesignGraph:
        elab = Elaborator(files, include_dirs).elaborate()

        # packages
        for pkg in sorted(elab.packages):
            node = self.graph.add_node(Node(id=pkg, kind=NodeKind.PACKAGE))
            if pkg in elab.unresolved:
                self.graph.mark_unresolved(pkg, "; ".join(elab.unresolved[pkg]))
            _ = node

        # files
        for path in sorted(elab.files):
            self.graph.add_node(
                Node(id=f"file:{path}", kind=NodeKind.FILE, path=path,
                     content_hash=Node.fingerprint(elab.files[path])))

        # modules
        for name, info in elab.modules.items():
            self.graph.add_node(Node(
                id=name, kind=NodeKind.RTL, path=info.file,
                content_hash=Node.fingerprint(elab.files.get(info.file or "", ""))))
            if info.file:
                self.graph.add_edge(name, f"file:{info.file}", EdgeKind.DEFINED_IN)
            for inc in info.includes:
                self.graph.add_edge(f"file:{inc}", name, EdgeKind.INCLUDES)
            for imp in info.imports:
                self.graph.add_node(Node(id=imp, kind=NodeKind.PACKAGE))
                self.graph.add_edge(imp, name, EdgeKind.IMPORTS)
            for mod, inst in info.instantiations:
                self.graph.add_node(Node(id=mod, kind=NodeKind.RTL))
                self.graph.add_edge(mod, name, EdgeKind.INSTANTIATES)
                if mod not in elab.modules:
                    # a module we instantiate but cannot see: keep it explicit
                    self.graph.add_edge(mod, name, EdgeKind.UNKNOWN)
                    self.graph.mark_unresolved(
                        mod, f"instantiated as {inst} in {name} but not defined")
            for gen in info.generate_blocks:
                gid = f"gen:{name}:{gen}"
                self.graph.add_node(Node(id=gid, kind=NodeKind.RTL, meta={"generate": True}))
                self.graph.add_edge(gid, name, EdgeKind.GENERATES)
            # clocks / resets by naming convention
            text = elab.files.get(info.file or "", "")
            for clk in sorted(set(CLK_RE.findall(text)))[:4]:
                self.graph.add_node(Node(id=clk, kind=NodeKind.CLOCK))
                self.graph.add_edge(clk, name, EdgeKind.CLOCKED_BY)
            for rst in sorted(set(RST_RE.findall(text)))[:4]:
                self.graph.add_node(Node(id=rst, kind=NodeKind.RESET))
                self.graph.add_edge(rst, name, EdgeKind.RESET_BY)

            if name in elab.unresolved:
                self.graph.mark_unresolved(name, "; ".join(elab.unresolved[name]))

        # a package imported but never defined is a blind spot on the importer
        for pkg, reasons in elab.unresolved.items():
            if pkg not in elab.modules and pkg not in elab.packages:
                self.graph.add_node(Node(id=pkg, kind=NodeKind.PACKAGE))
                self.graph.mark_unresolved(pkg, "; ".join(reasons))

        self.graph.approximate = elab.approximate
        return self.graph

    def build_from_filelist(self, filelist_text: str,
                            files: dict[str, str]) -> DesignGraph:
        _files, incdirs, _defines = read_filelist(filelist_text)
        return self.build_from_files(files, include_dirs=incdirs)

    def build(self) -> DesignGraph:
        return self.graph
