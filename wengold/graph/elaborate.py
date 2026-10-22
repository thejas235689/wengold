"""RTL elaboration — the front-end that turns source files into real dependencies.

A regex scan of a single file cannot see what a module actually depends on: the
files it `include`s, the packages it imports, the parameters it is configured
with, the modules it instantiates inside generate blocks, or the branches hidden
behind `ifdef. Missing any of these means a change can slip past the kernel and
leave a stale result marked valid.

This module elaborates a file set: it resolves includes against a search path,
collects macros, packages, parameters and instantiations (including inside
generate blocks), and reports anything it could *not* resolve. The builder turns
those reports into UNKNOWN edges so the kernel stays conservative.

It is deliberately bounded — a structural elaborator, not a full IEEE 1800
front-end. Plug Surelog or sv-parser in behind `parse_modules` /
`extract_instantiations` when exact elaboration is required.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

INCLUDE_RE = re.compile(r'`include\s+"([^"]+)"')
DEFINE_RE = re.compile(r'`define\s+(\w+)')
IFDEF_RE = re.compile(r'`(ifdef|ifndef)\s+(\w+)')
UNDEF_RE = re.compile(r'`undef\s+(\w+)')
PACKAGE_RE = re.compile(r'\bpackage\s+(\w+)')
IMPORT_RE = re.compile(r'\bimport\s+(\w+)\s*::')
MODULE_RE = re.compile(r'\bmodule\s+(\w+)')
PARAM_RE = re.compile(
    r'\b(?:parameter|localparam)\b[^=;]*?\b(\w+)\s*=\s*([^,;\)\n]+)')
GENERATE_RE = re.compile(r'\b(generate|endgenerate)\b')
GEN_LABEL_RE = re.compile(r'\b(?:for|if)\s*\([^)]*\)\s*(?::\s*(\w+))?')

COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT_RE = re.compile(r"//[^\n]*")
# A macro is conventionally ALL_CAPS_WITH_UNDERSCORES; those are not module types.
MACRO_LIKE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def strip_comments(text: str) -> str:
    """Remove comments before any extraction.

    License headers and prose are full of things that look like instantiations
    (``lowRISC contributors``), so extracting from commented text invents
    dependencies that do not exist.
    """
    return LINE_COMMENT_RE.sub(" ", COMMENT_RE.sub(" ", text))


# Gate-level primitives and Verilog keywords that must not be mistaken for a
# module type in an instantiation.
PRIMITIVES = {
    "and", "or", "nand", "nor", "xor", "xnor", "not", "buf", "bufif0", "bufif1",
    "notif0", "notif1", "nmos", "pmos", "cmos", "tran", "tranif0", "tranif1",
    "pullup", "pulldown", "assign",
}
KEYWORDS = {
    "module", "endmodule", "package", "endpackage", "class", "endclass",
    "function", "endfunction", "task", "endtask", "interface", "endinterface",
    "program", "endprogram", "generate", "endgenerate", "always", "always_ff",
    "always_comb", "always_latch", "initial", "final", "assign", "if", "else",
    "for", "while", "do", "case", "casex", "casez", "endcase", "begin", "end",
    "fork", "join", "join_any", "join_none", "wire", "reg", "logic", "bit",
    "input", "output", "inout", "parameter", "localparam", "typedef", "enum",
    "struct", "union", "return", "posedge", "negedge", "or", "and", "not",
    "nand", "nor", "xor", "xnor", "buf", "assert", "assume", "cover", "property",
    "endproperty", "sequence", "endsequence", "default", "genvar", "import",
    "export", "package", "virtual", "new", "this", "super", "static", "automatic",
    # SVA / assertion vocabulary — `disable iff (...)` is not an instantiation
    "disable", "iff", "property", "endproperty", "sequence", "endsequence",
    "assert", "assume", "cover", "restrict", "strong", "weak", "throughout",
    "within", "until", "s_eventually", "s_until", "nexttime", "accept_on",
    "reject_on", "sync_accept_on", "sync_reject_on", "bind", "checker",
    "endchecker", "clocking", "endclocking", "randcase", "constraint", "solve",
    "before", "first_match", "matches", "intersect", "dist", "inside",
}
INST_RE = re.compile(
    r'\b([A-Za-z_]\w*)(?!\w)\s*'
    r'(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?'
    r'([A-Za-z_]\w*)(?!\w)\s*\(')


@dataclass
class ModuleInfo:
    name: str
    file: str | None = None
    includes: set[str] = field(default_factory=set)
    packages_defined: set[str] = field(default_factory=set)
    imports: set[str] = field(default_factory=set)
    parameters: dict[str, str] = field(default_factory=dict)
    instantiations: list[tuple[str, str]] = field(default_factory=list)
    generate_blocks: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


@dataclass
class ElaborationResult:
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)          # path -> expanded source
    macros: set[str] = field(default_factory=set)
    packages: set[str] = field(default_factory=set)
    unresolved: dict[str, list[str]] = field(default_factory=dict)  # node -> reasons
    approximate: bool = False


# ---------------------------------------------------------------- filelists
def read_filelist(text: str) -> tuple[list[str], list[str], set[str]]:
    """Parse a `.f` file list. Returns (files, include_dirs, defines).

    Handles `//` and `#` comments, nested `-f`, `+incdir+`, `+define+` and
    `-y` library dirs (returned as include dirs)."""
    files: list[str] = []
    incdirs: list[str] = []
    defines: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].split("#", 1)[0].strip()
        if not line:
            continue
        for tok in line.split():
            if tok.startswith("+incdir+"):
                for d in tok[len("+incdir+"):].split("+"):
                    if d:
                        incdirs.append(d)
            elif tok.startswith("-y"):
                if tok[2:]:
                    incdirs.append(tok[2:])
            elif tok.startswith("+define+"):
                for d in tok[len("+define+"):].split("+"):
                    if d:
                        defines.add(d.split("=")[0])
            elif tok in ("-f", "-F") or tok.startswith("-f"):
                continue  # nested lists are expanded by the caller with a base dir
            else:
                files.append(tok)
    return files, incdirs, defines


# ---------------------------------------------------------------- extraction
def extract_macros(source: str) -> set[str]:
    return set(DEFINE_RE.findall(source))


def extract_packages(source: str) -> set[str]:
    return set(PACKAGE_RE.findall(source))


def extract_modules(source: str) -> list[str]:
    return MODULE_RE.findall(source)


def extract_imports(source: str) -> set[str]:
    return set(IMPORT_RE.findall(source))


def extract_parameters(source: str) -> dict[str, str]:
    return {name: value.strip() for name, value in PARAM_RE.findall(source)}


def extract_instantiations(source: str) -> list[tuple[str, str]]:
    """Best-effort (module_type, instance_name) pairs, filtered against keywords."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in INST_RE.finditer(source):
        mod, inst = m.group(1), m.group(2)
        if mod in KEYWORDS or inst in KEYWORDS or mod in PRIMITIVES:
            continue
        if mod == inst:
            continue
        if mod[0].isdigit() or inst[0].isdigit():
            continue
        if MACRO_LIKE.match(mod) or MACRO_LIKE.match(inst):
            continue        # a macro invocation, not an instantiation
        if (mod, inst) in seen:
            continue
        seen.add((mod, inst))
        out.append((mod, inst))
    return out


def extract_generate_blocks(source: str) -> list[str]:
    if not GENERATE_RE.search(source):
        return []
    labels = [lab for lab in GEN_LABEL_RE.findall(source) if lab]
    return labels or ["generate"]


# ---------------------------------------------------------------- elaborator
class Elaborator:
    def __init__(self, files: dict[str, str], include_dirs: list[str] | None = None):
        self.files = dict(files)
        self.include_dirs = list(include_dirs or [])
        self._expanded: dict[str, tuple[str, set[str], list[str]]] = {}

    # -- include resolution --------------------------------------------
    def _find_include(self, name: str, includer: str) -> str | None:
        candidates = []
        base = os.path.dirname(includer)
        if base:
            candidates.append(os.path.join(base, name))
        candidates.append(name)
        candidates += [os.path.join(d, name) for d in self.include_dirs]
        for c in candidates:
            if c in self.files:
                return c
        return None

    def expand(self, path: str, _seen: set[str] | None = None) -> tuple[str, set[str], list[str]]:
        """Recursively inline `include, returning (text, included_paths, unresolved)."""
        if path in self._expanded:
            return self._expanded[path]
        _seen = _seen or set()
        if path in _seen:
            return "", set(), [f"include cycle at {path}"]
        _seen = _seen | {path}
        source = strip_comments(self.files.get(path, ""))
        included: set[str] = set()
        unresolved: list[str] = []
        if not source:
            unresolved.append(f"source for {path} not found")

        def _sub(match: re.Match) -> str:
            name = match.group(1)
            resolved = self._find_include(name, path)
            if resolved is None:
                unresolved.append(f"unresolved include `{name}` in {path}")
                return match.group(0)
            included.add(resolved)
            text, inc2, unres2 = self.expand(resolved, _seen)
            included.update(inc2)
            unresolved.extend(unres2)
            return text

        text = INCLUDE_RE.sub(_sub, source)
        self._expanded[path] = (text, included, unresolved)
        return text, included, unresolved

    # -- whole-set elaboration -----------------------------------------
    def elaborate(self) -> ElaborationResult:
        result = ElaborationResult()
        # 1. macros and packages are global in Verilog compilation units
        expanded: dict[str, str] = {}
        for path in self.files:
            text, _inc, _unres = self.expand(path)
            expanded[path] = text
            result.macros |= extract_macros(text)
            result.packages |= extract_packages(text)
        result.files = expanded

        defined_modules: set[str] = set()
        for text in expanded.values():
            defined_modules.update(extract_modules(text))

        # 2. per-module facts
        for path, text in expanded.items():
            _t, includes, include_unres = self.expand(path)
            # conditional compilation on a macro we never saw is a real blind spot
            cond_unres = []
            for kind, macro in IFDEF_RE.findall(text):
                if macro not in result.macros:
                    cond_unres.append(
                        f"conditional compilation on undefined macro `{macro}` in {path}")
            modules_here = extract_modules(text)
            for name in modules_here:
                info = ModuleInfo(name=name, file=path)
                info.includes = set(includes)
                info.packages_defined = extract_packages(text)
                info.imports = extract_imports(text)
                info.parameters = extract_parameters(text)
                info.generate_blocks = extract_generate_blocks(text)
                info.instantiations = extract_instantiations(text)
                info.unresolved = list(include_unres) + cond_unres
                # instantiations whose module type is nowhere defined
                for mod, _inst in info.instantiations:
                    if mod not in defined_modules and mod not in PRIMITIVES:
                        info.unresolved.append(
                            f"instantiation `{mod}` has no definition in the file set")
                if info.unresolved:
                    result.unresolved[name] = info.unresolved
                result.modules[name] = info

        # 3. packages are nodes too; a package we import but never define is a gap
        for path, text in expanded.items():
            for pkg in extract_imports(text):
                if pkg not in result.packages:
                    result.unresolved.setdefault(pkg, []).append(
                        f"package `{pkg}` imported but not defined in the file set")

        result.approximate = False
        return result
