"""VHDL front-end.

Enough of VHDL to build the dependency graph: entities are blocks, architectures
say an entity is implemented, and instantiations are edges. Packages and `use`
clauses are recorded the same way `import` is on the SystemVerilog side, so the
builder and the kernel need to know nothing about the language.

What it is and is not:

* It is **structural**. It finds design units and how they connect. That is what
  the graph is for, and it is what makes a VHDL project visible to WENGOLD at
  all — before this, a VHDL core like neorv32 indexed to nothing.
* It is **not** a parser. No port widths, no signal-level references, no
  expressions. The CDC and register-map front-ends are SystemVerilog-only and say
  so; a VHDL project gets the graph, the kernel, root cause and the IDE, and not
  those two.

A regex front-end is the right size for this. A real VHDL parser is a project of
its own, and claiming the same confidence from a scan would be the one thing this
tool must not do — so the units it produces carry no parse diagnostics, and an
instantiation of an entity that is not in the file set is left UNKNOWN by the
builder, exactly as it is for SystemVerilog.
"""
from __future__ import annotations

import re

from .slang_backend import SlangUnit as VhdlUnit

__all__ = ["available", "extract", "elaborate", "VhdlUnit"]

# entity NAME is        | entity lib.NAME is
_ENTITY = re.compile(r"^[ \t]*entity[ \t]+(?:(\w+)\s*\.\s*)?(\w+)[ \t]+is\b",
                     re.I | re.M)
# architecture NAME of ENTITY is
_ARCH = re.compile(r"^[ \t]*architecture[ \t]+(\w+)[ \t]+of[ \t]+"
                   r"(?:(\w+)\s*\.\s*)?(\w+)[ \t]+is\b", re.I | re.M)
# package NAME is  |  package body NAME is
_PACKAGE = re.compile(r"^[ \t]*package(?:[ \t]+body)?[ \t]+(\w+)[ \t]+is\b",
                      re.I | re.M)
# use work.NAME.all;   use lib.NAME.all;
_USE = re.compile(r"^[ \t]*use[ \t]+(?:(\w+)\s*\.\s*)?(\w+)\s*\.\s*all\s*;",
                  re.I | re.M)
# generic ( ... );   and   port ( ... );
#
# These are *declarations*, and `NAME : type` inside them looks exactly like
# `label : entity`. Without excluding their spans the entity's own generics were
# read as instantiations — `neorv32_cpu instantiates std_ulogic_vector`.
# re.M as well as re.S: without re.M the `^` only matches at the start of the
# file, so no generic block in the file was ever found.
_GENERIC = re.compile(r"^[ \t]*generic[ \t]*\((.*?)\)[ \t]*;", re.I | re.S | re.M)
_PORT = re.compile(r"^[ \t]*port[ \t]*\((.*?)\)[ \t]*;", re.I | re.S | re.M)
# `(?!=)` so `NAME := value` is not read as a declaration: without it the
# initialiser's type (`boolean := false`) and even `range 0 to 1 := 0` became
# parameter names.
_GENERIC_NAME = re.compile(r"(\w+)\s*:(?!=)")

# a type or a reserved word is never the entity being instantiated
_NOT_AN_ENTITY = {
    "std_logic", "std_ulogic", "std_logic_vector", "std_ulogic_vector",
    "unsigned", "signed", "integer", "natural", "positive", "boolean",
    "bit", "bit_vector", "character", "string", "time", "real",
}

# label : entity [lib.]NAME   ... generic map / port map
# label : NAME                ... generic map / port map   (component form)
_INST = re.compile(
    r"^[ \t]*(\w+)[ \t]*:[ \t]*(?:entity[ \t]+(?:(\w+)\s*\.\s*)?)?(\w+)"
    r"[ \t]*(?=[\r\n]|--|\(|(?:generic|port)[ \t]*map\b)",
    re.I | re.M)

# words that look like `label : something` but are not instantiations
_NOT_AN_INST = {
    "if", "elsif", "else", "case", "when", "for", "while", "loop", "generate",
    "process", "block", "component", "entity", "architecture", "signal",
    "variable", "constant", "type", "subtype", "alias", "function", "procedure",
    "attribute", "port", "generic", "map", "begin", "end", "with", "assert",
    "report", "return", "exit", "next", "null", "wait", "others", "all",
    "in", "out", "inout", "buffer", "linkage", "to", "downto", "range",
}


def available() -> bool:
    """Always — this front-end has no dependency to be missing."""
    return True


def _strip_comments(text: str) -> str:
    """VHDL comments run `--` to end of line. Nothing is block-commented, so a
    line-wise strip is exact."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def _owner_index(text: str) -> list[tuple[int, str]]:
    return sorted((m.start(), m.group(2)) for m in _ENTITY.finditer(text))


def _owner_at(owners: list[tuple[int, str]], pos: int) -> str | None:
    """The entity whose declaration most recently precedes `pos`."""
    owner = None
    for start, name in owners:
        if start <= pos:
            owner = name
        else:
            break
    return owner


def extract(text: str, path: str) -> VhdlUnit:
    """What one VHDL file declares."""
    src = _strip_comments(text)
    unit = VhdlUnit(path=path)

    unit.modules = [m.group(2) for m in _ENTITY.finditer(src)]
    # an architecture implements an entity; it does not create a block of its own
    implemented = {m.group(3) for m in _ARCH.finditer(src)}
    for name in unit.modules:
        if name not in implemented and implemented:
            # an entity with no architecture in this file is a declaration only,
            # which is normal when the body lives elsewhere — not an error
            pass
    # `package X is` and `package body X is` are the same package
    seen_pkgs: list[str] = []
    for m in _PACKAGE.finditer(src):
        if m.group(1) not in seen_pkgs:
            seen_pkgs.append(m.group(1))
    unit.packages = seen_pkgs
    unit.imports = [m.group(2) for m in _USE.finditer(src)]

    for m in _GENERIC.finditer(src):
        for g in _GENERIC_NAME.finditer(m.group(1)):
            unit.parameters.append((g.group(1), None))

    # spans holding declarations, where `NAME : type` is not an instantiation
    decl_spans = [(m.start(), m.end())
                  for m in list(_GENERIC.finditer(src)) + list(_PORT.finditer(src))]

    def in_declaration(pos: int) -> bool:
        return any(a <= pos < b for a, b in decl_spans)

    owners = _owner_index(src)
    for m in _INST.finditer(src):
        label, _lib, child = m.group(1), m.group(2), m.group(3)
        low_l, low_c = label.lower(), child.lower()
        if low_l in _NOT_AN_INST or low_c in _NOT_AN_INST:
            continue
        if low_c in _NOT_AN_ENTITY or label == child:
            continue
        if in_declaration(m.start()):
            continue
        # a real instantiation reaches a port or generic map; a declaration does not
        if not re.search(r"(?:generic|port)[ \t]*map", src[m.end():m.end() + 400],
                         re.I):
            continue
        owner = _owner_at(owners, m.start())
        if owner is None:
            continue                      # an instantiation outside any entity
        unit.instantiations.append((owner, child, label))
    return unit


def elaborate(files: dict[str, str], include_dirs=None, defines=None) -> dict:
    """One unit per file, keyed by path — the shape `build_from_slang` expects."""
    return {path: extract(text, path) for path, text in sorted(files.items())}
