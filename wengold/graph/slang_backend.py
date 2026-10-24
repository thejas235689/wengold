"""Real elaboration via slang (the `pyslang` bindings).

The regex extractor is a fallback: on a real codebase it mistakes prose for
instantiations and cannot see through `` `ifdef ``. slang is a full SystemVerilog
front-end, so when it is installed we preprocess the source and parse it for
real — modules, hierarchy instantiations, packages, imports and parameters all
come from an actual parse tree.

slang is optional: `available()` is False without it and the caller falls back.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .preprocess import Preprocessor, make_resolver

try:                                   # optional dependency
    from pyslang import syntax as S
    _HAVE_SLANG = True
except Exception:                      # pragma: no cover
    S = None
    _HAVE_SLANG = False


def available() -> bool:
    return _HAVE_SLANG


@dataclass
class SlangUnit:
    """What one source file declares, according to a real parse."""
    path: str
    modules: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)
    instantiations: list[tuple[str, str, str]] = field(default_factory=list)
    packages: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    parameters: list[tuple[str, str | None]] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    parse_errors: int = 0

    def as_dict(self) -> dict:
        return {"path": self.path, "modules": self.modules,
                "interfaces": self.interfaces,
                "instantiations": [list(i) for i in self.instantiations],
                "packages": self.packages, "imports": self.imports,
                "parameters": [list(p) for p in self.parameters],
                "includes": self.includes, "unresolved": self.unresolved,
                "parse_errors": self.parse_errors}


def _walk(node):
    yield node
    try:
        for child in node:
            if hasattr(child, "kind"):
                yield from _walk(child)
    except TypeError:
        pass


def _enclosing_unit(node) -> str | None:
    """The name of the module/interface that contains `node`, via the parent chain."""
    parent = getattr(node, "parent", None)
    while parent is not None:
        if parent.kind in (S.SyntaxKind.ModuleDeclaration,
                           S.SyntaxKind.InterfaceDeclaration,
                           S.SyntaxKind.ProgramDeclaration):
            return _text(getattr(getattr(parent, "header", None), "name", None))
        parent = getattr(parent, "parent", None)
    return None


def _text(node) -> str | None:
    """Text of a node that may be a token, an identifier node, or a wrapper."""
    vt = getattr(node, "valueText", None)
    if isinstance(vt, str) and vt:
        return vt
    for x in _walk(node):
        vt = getattr(x, "valueText", None)
        if isinstance(vt, str) and vt:
            return vt
    return None


def _first_identifier(node) -> str | None:
    for x in _walk(node):
        if x.kind == S.SyntaxKind.IdentifierName:
            return _text(x)
    return _text(node)


def extract(text: str, name: str = "source") -> SlangUnit:
    """Parse one (already preprocessed) file."""
    unit = SlangUnit(path=name)
    tree = S.SyntaxTree.fromText(text, name=name)
    unit.parse_errors = len(tree.diagnostics)
    for n in _walk(tree.root):
        kind = n.kind
        if kind == S.SyntaxKind.ModuleDeclaration:
            name = _text(getattr(n.header, "name", None))
            if name:
                unit.modules.append(name)
        elif kind == S.SyntaxKind.HierarchyInstantiation:
            try:
                child = n.type.valueText
            except Exception:
                continue
            # The instantiation belongs to the module that *contains* it, not to
            # the file. A file may define several modules (and one Verilog file
            # often does), so attributing every instantiation in a file to every
            # module in it invents a hierarchy in which everything instantiates
            # everything.
            owner = _enclosing_unit(n)
            for inst in n.instances:
                unit.instantiations.append(
                    (owner or "", child, _text(getattr(inst, "decl", None)) or "?"))
        elif kind in (S.SyntaxKind.InterfaceDeclaration, S.SyntaxKind.ProgramDeclaration):
            # an interface is a design unit an instantiation can bind to, so it
            # counts as a definition — not a missing module
            name = _text(getattr(n.header, "name", None))
            if name:
                unit.interfaces.append(name)
        elif kind == S.SyntaxKind.PackageDeclaration:
            name = _text(getattr(n.header, "name", None))
            if name:
                unit.packages.append(name)
        elif kind == S.SyntaxKind.PackageImportDeclaration:
            for item in getattr(n, "items", []):
                name = _text(getattr(item, "package", None))
                if name:
                    unit.imports.append(name)
        elif kind == S.SyntaxKind.ParameterDeclaration:
            name = _first_identifier(n)
            if name:
                unit.parameters.append((name, None))
    return unit


def elaborate(files: dict[str, str], include_dirs: list[str] | None = None,
              defines: dict[str, str] | None = None) -> dict[str, SlangUnit]:
    """Preprocess and parse every file; return one unit per source file."""
    if not _HAVE_SLANG:
        raise RuntimeError("slang (pyslang) is not installed")
    resolve = make_resolver(files, list(include_dirs or []))
    pp = Preprocessor(resolve, defines=defines)
    out: dict[str, SlangUnit] = {}
    for path, text in files.items():
        if not path.lower().endswith((".sv", ".svh", ".v", ".vh")):
            continue
        result = pp.run(text, path)
        unit = extract(result.text, path)
        unit.includes = list(result.includes)
        unit.unresolved = list(result.unresolved)
        out[path] = unit
    return out
