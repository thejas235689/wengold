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

    # ---- slang-backed construction -----------------------------------
    def build_from_slang(self, units: dict) -> DesignGraph:
        """Add nodes and edges from real parses (see `slang_backend`).

        A file with parse errors is marked unresolved, and an instantiation of a
        module that is not defined in the file set is recorded as an UNKNOWN edge
        as well — so the kernel cannot return VALID downstream of either.
        """
        defined = {m for u in units.values() for m in u.modules}
        defined |= {i for u in units.values() for i in u.interfaces}
        for path, unit in sorted(units.items()):
            for pkg in unit.packages:
                self.graph.add_node(Node(id=pkg, kind=NodeKind.PACKAGE, path=path))
            for iface in unit.interfaces:
                self.graph.add_node(Node(id=iface, kind=NodeKind.RTL, path=path,
                                         meta={"frontend": "slang", "unit": "interface"}))
            for mod in unit.modules:
                self.graph.add_node(Node(id=mod, kind=NodeKind.RTL, path=path,
                                         meta={"frontend": "slang"}))
                if unit.parse_errors:
                    self.graph.mark_unresolved(
                        mod, f"{unit.parse_errors} parse error(s) in {path}",
                        kind="parse_error", file=path,
                        construct=", ".join(sorted({str(d.code) for d in unit.diagnostics[:3]}))
                        if getattr(unit, "diagnostics", None) else "parse errors")
                for pkg in unit.imports:
                    if pkg in defined:
                        # `import X::*` where X is a module is not a package
                        # import. Adding it as one would overwrite the module's
                        # node — and a block silently disappearing from the graph
                        # is worse than a missing edge.
                        self.graph.notes.append(
                            f"{mod}: `import {pkg}::*` names a module, not a "
                            f"package — ignored")
                        continue
                    self.graph.add_node(Node(id=pkg, kind=NodeKind.PACKAGE))
                    self.graph.add_edge(pkg, mod, EdgeKind.IMPORTS)
                for name, _value in unit.parameters:
                    pid = f"param.{mod}.{name}"
                    self.graph.add_node(Node(id=pid, kind=NodeKind.PARAM,
                                             meta={"module": mod}))
                    self.graph.add_edge(pid, mod, EdgeKind.PARAMETERIZES)
                for inc in unit.includes:
                    self.graph.add_node(Node(id=inc, kind=NodeKind.FILE, path=inc))
                    self.graph.add_edge(inc, mod, EdgeKind.INCLUDES)
        for path, unit in sorted(units.items()):
            for owner, child, inst in unit.instantiations:
                if not owner or owner not in defined:
                    continue                     # not a module we indexed
                if child in defined:
                    self.graph.add_edge(child, owner, EdgeKind.INSTANTIATES)
                else:
                    self.graph.add_node(Node(id=child, kind=NodeKind.RTL))
                    self.graph.add_edge(child, owner, EdgeKind.UNKNOWN)
                    self.graph.mark_unresolved(
                        owner,
                        f"instantiation `{child}` has no definition in the file set",
                        kind="missing_definition", file=path, subject=child,
                        construct=f"hierarchy instantiation `{inst}`")
        for _path, unit in units.items():
            for name in unit.unresolved:
                self.graph.notes.append(f"unresolved include: {name}")
        return self.graph

    def mark_uncertain(self, src: str, dst: str) -> None:
        """Record a dependency the builder could not resolve. The kernel treats
        any result downstream of it as UNKNOWN, never as a false pass."""
        self.graph.add_edge(src, dst, EdgeKind.UNKNOWN)

    # ---- elaboration-driven construction -----------------------------
    def build_from_files(self, files: dict[str, str],
                         include_dirs: list[str] | None = None,
                         defines: dict[str, str] | None = None,
                         backend: str = "auto") -> DesignGraph:
        """Build the graph. `backend` selects the front-end:

        * ``slang`` — real parse via pyslang (preprocessor + CST)
        * ``regex`` — the bounded elaborator (fallback)
        * ``auto``  — slang when installed, else regex
        """
        # Route by suffix, so a mixed project works: VHDL goes to the VHDL
        # front-end, everything else to the SystemVerilog one, and both land in
        # the same unit dict for `build_from_slang`.
        # Record what we were asked to read, so completeness() can report how
        # much of it produced a design unit rather than only whether what it
        # found resolved.
        self.graph.file_set = set(files)
        vhdl = {p: t for p, t in files.items()
                if p.lower().endswith((".vhd", ".vhdl"))}
        sv = {p: t for p, t in files.items() if p not in vhdl}
        units: dict = {}
        handled_sv = False
        if sv and backend in ("auto", "slang"):
            from .slang_backend import available, elaborate as slang_elaborate
            if available():
                units.update(slang_elaborate(sv, include_dirs or [],
                                             defines or {}))
                handled_sv = True
            elif backend == "slang":
                raise RuntimeError("slang (pyslang) is not installed")
        vhdl_units: dict = {}
        if vhdl:
            from .vhdl_backend import elaborate as vhdl_elaborate
            vhdl_units = vhdl_elaborate(vhdl)

        # Only take the units path when the SystemVerilog side was actually
        # handled. A project with one stray .vhd file and 477 .sv files used to
        # return here with `units` holding that single VHDL module — silently
        # dropping every SystemVerilog file. cva6 indexed to 4 blocks instead of
        # 458, and the number looked plausible enough to pass unnoticed.
        if units and (handled_sv or not sv):
            units.update(vhdl_units)
            return self.build_from_slang(units)

        # Falling back silently is dangerous: the bounded regex elaborator finds a
        # fraction of the modules, so the same project can index to hundreds of
        # blocks or to a handful depending on what is installed.
        self.graph.notes.append(
            "slang (pyslang) is not installed — fell back to the bounded regex "
            "elaborator, which finds far fewer modules. The block count below is "
            "an under-estimate, not the design.")
        elab = Elaborator(sv or files, include_dirs).elaborate()

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
        if vhdl_units:
            # the regex elaborator cannot read VHDL, so add those design units on
            # top of what it produced rather than losing them
            self.build_from_slang(vhdl_units)
        return self.graph

    def build_from_filelist(self, filelist_text: str,
                            files: dict[str, str]) -> DesignGraph:
        _files, incdirs, _defines = read_filelist(filelist_text)
        return self.build_from_files(files, include_dirs=incdirs)

    def build(self) -> DesignGraph:
        return self.graph
