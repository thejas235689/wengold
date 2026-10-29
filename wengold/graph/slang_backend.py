"""Real elaboration via slang (the `pyslang` bindings).

The regex extractor is a fallback: on a real codebase it mistakes prose for
instantiations and cannot see through `` `ifdef ``. slang is a full SystemVerilog
front-end, so when it is installed we preprocess the source and parse it for
real — modules, hierarchy instantiations, packages, imports and parameters all
come from an actual parse tree.

slang is optional: `available()` is False without it and the caller falls back.
"""
from __future__ import annotations

import re
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
    # module name -> number of parse errors inside that module's span. A file with
    # one broken module used to mark every module in it unresolved, which on
    # Veer EL2 turned one bad module in beh_lib.sv into 41 unresolved nodes.
    error_modules: dict = field(default_factory=dict)
    # errors that fall outside every module (a bad `package`, a stray token)
    file_level_errors: int = 0

    def as_dict(self) -> dict:
        return {"path": self.path, "modules": self.modules,
                "interfaces": self.interfaces,
                "instantiations": [list(i) for i in self.instantiations],
                "packages": self.packages, "imports": self.imports,
                "parameters": [list(p) for p in self.parameters],
                "includes": self.includes, "unresolved": self.unresolved,
                "parse_errors": self.parse_errors,
                "error_modules": self.error_modules,
                "file_level_errors": self.file_level_errors}


def _walk(node):
    yield node
    try:
        for child in node:
            if hasattr(child, "kind"):
                yield from _walk(child)
    except TypeError:
        pass


# ---- constant generate conditions -----------------------------------------
_CONST = re.compile(r"\b(?:localparam|parameter)\b[^=;]*?\b(\w+)\s*=\s*([^,;)\n]+)")


def _const_int(text: str) -> dict[str, int]:
    """Best-effort constants from the source: `localparam NAME = <literal>`."""
    out: dict[str, int] = {}
    for m in _CONST.finditer(text):
        raw = m.group(2).strip()
        lit = re.fullmatch(r"(?:\d+)?'([hdb])?([0-9a-fA-F_]+)", raw)
        if lit:
            base = {"h": 16, "d": 10, "b": 2, None: 10}[lit.group(1)]
            try:
                out[m.group(1)] = int(lit.group(2).replace("_", ""), base)
            except ValueError:
                pass
        elif raw.isdigit():
            out[m.group(1)] = int(raw)
    return out


def _eval_cond(node, consts: dict[str, int]):
    """Evaluate a generate condition, or None when it cannot be known statically."""
    if node is None:
        return None
    kind = str(node.kind)
    if kind.endswith("IdentifierName"):
        tok = getattr(node, "identifier", None)
        name = getattr(tok, "valueText", None)
        return consts.get(name) if name is not None else None
    if kind.endswith("LiteralExpression"):
        tok = getattr(node, "literal", None)
        return _const_int(f"x = {getattr(tok, 'valueText', '')}").get("x")
    op = getattr(getattr(node, "operatorToken", None), "valueText", None)
    left = getattr(node, "left", None)
    right = getattr(node, "right", None)
    if op is not None and left is not None and right is not None:
        a = _eval_cond(left, consts)
        b = _eval_cond(right, consts)
        if a is None or b is None:
            return None
        table = {"&&": a and b, "||": a or b, "&": a & b, "|": a | b, "^": a ^ b,
                 "==": int(a == b), "!=": int(a != b), "<": int(a < b),
                 ">": int(a > b), "<=": int(a <= b), ">=": int(a >= b),
                 "+": a + b, "-": a - b, "*": a * b}
        return table.get(op)
    operand = getattr(node, "operand", None)
    if op is not None and operand is not None:
        v = _eval_cond(operand, consts)
        return None if v is None else {"!": int(not v), "~": ~v, "-": -v}.get(op)
    inner = getattr(node, "expression", None)
    if inner is not None:
        return _eval_cond(inner, consts)
    return None


def _in_dead_generate(node, consts: dict[str, int]) -> bool:
    """True when `node` sits in a generate branch that is statically not taken.

    `generate if (PULP_SECURE && USE_PMP)` with both localparams 0 is dead code:
    the module it instantiates is not missing, it is simply not elaborated. Not
    evaluating the condition reports a missing definition for code no build would
    ever include.
    """
    parent = getattr(node, "parent", None)
    while parent is not None:
        if str(parent.kind).endswith("IfGenerate"):
            value = _eval_cond(getattr(parent, "condition", None), consts)
            if value is not None:
                block = getattr(parent, "block", None)
                in_if = _contains(block, node)
                if (value == 0 and in_if) or (value != 0 and not in_if):
                    return True
        parent = getattr(parent, "parent", None)
    return False


def _contains(ancestor, node) -> bool:
    """Is `node` inside `ancestor`'s subtree?"""
    if ancestor is None:
        return False
    cur = getattr(node, "parent", None)
    while cur is not None:
        if cur is ancestor:
            return True
        cur = getattr(cur, "parent", None)
    return False


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

    # Map every module declaration to the byte range it occupies, then attribute
    # each error to the module containing it. Modules are laid out in source
    # order, so a module owns the range from its own start to the next start.
    spans = []
    for member in getattr(tree.root, "members", []):
        if getattr(member, "kind", None) != S.SyntaxKind.ModuleDeclaration:
            continue
        mod_name = _text(getattr(getattr(member, "header", None), "name", None))
        try:
            start = member.sourceRange.start.offset
        except Exception:
            continue
        if mod_name:
            spans.append((start, mod_name))
    spans.sort()
    if spans:
        for diag in tree.diagnostics:
            try:
                off = diag.location.offset
            except Exception:
                unit.file_level_errors += 1
                continue
            owner = None
            for start, mod_name in spans:
                if start <= off:
                    owner = mod_name
                else:
                    break
            if owner is None:
                unit.file_level_errors += 1
            else:
                unit.error_modules[owner] = unit.error_modules.get(owner, 0) + 1
    consts = _const_int(text)
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
            if _in_dead_generate(n, consts):
                continue                    # an untaken generate branch: not missing
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
