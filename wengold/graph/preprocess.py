"""A real SystemVerilog preprocessor.

The bounded front-ends could not resolve `` `ifdef `` or expand macros, so on real
RTL every module came back unresolved and the kernel had no choice but to return
UNKNOWN. This resolves directives the way a compiler does — given the project's
defines and include paths — so the elaborator and the formal front-end see the
same source a build would.

Handles: `` `define `` (object- and function-like, with line continuations),
`` `undef ``, `` `ifdef ``/`` `ifndef ``/`` `elsif ``/`` `else ``/`` `endif ``,
`` `include `` (searched against the include path), macro expansion, and the
directives that carry no meaning for us (`` `timescale ``, `` `default_nettype ``,
`` `line ``, `` `pragma ``, ...), which are dropped.

It never guesses: an include it cannot find is recorded in `unresolved`, and a
macro it cannot expand is left in place and recorded in `unexpanded`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable

_DIRECTIVE = re.compile(r"^\s*`(\w+)\b\s*(.*)$")
_DEFINE = re.compile(r"^\s*`define\s+(\w+)(\(([^)]*)\))?\s*(.*)$")
_INCLUDE = re.compile(r'^\s*`include\s+[<"]([^>"]+)[>"]')
_MACRO_USE = re.compile(r"`(\w+)")
_DIRECTIVE_KEYWORDS = {"define", "undef", "ifdef", "ifndef", "elsif", "else", "endif",
                       "include"}
_IGNORED = {"timescale", "default_nettype", "line", "pragma", "resetall", "celldefine",
            "endcelldefine", "nounconnected_drive", "unconnected_drive", "begin_keywords",
            "end_keywords", "default_decay_time", "default_trireg_strength",
            "delay_mode_distributed", "delay_mode_path", "delay_mode_unit", "delay_mode_zero",
            "uselib", "protect", "endprotect"}


@dataclass
class Preprocessed:
    text: str
    includes: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    unexpanded: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"includes": self.includes, "unresolved": self.unresolved,
                "unexpanded": self.unexpanded}


class Preprocessor:
    def __init__(self, resolve: Callable[[str, str], tuple[str, str] | None],
                 defines: dict[str, str] | None = None, max_depth: int = 32):
        """`resolve(name, from_path) -> (path, text) | None` locates an include."""
        self.resolve = resolve
        self.defines = dict(defines or {})
        self.max_depth = max_depth

    # -- public -----------------------------------------------------------
    def run(self, text: str, path: str = "") -> Preprocessed:
        out = Preprocessed(text="")
        self._includes: list[str] = []
        self._unresolved: list[str] = []
        self._unexpanded: set[str] = set()
        self._drop_depth = 0
        self._run(text, path, out, depth=0)
        out.text = "\n".join(self._lines)
        out.includes = list(self._includes)
        out.unresolved = list(self._unresolved)
        out.unexpanded = sorted(self._unexpanded)
        return out

    # -- internals --------------------------------------------------------
    def _run(self, text: str, path: str, out: Preprocessed, depth: int) -> None:
        if depth > self.max_depth:
            self._unresolved.append(f"include depth exceeded at {path}")
            return
        # join line continuations so a `define body can span lines
        lines = self._join_continuations(text.splitlines())
        stack: list[dict] = []          # {'active': bool, 'taken': bool, 'parent': bool}
        self._lines: list[str] = [] if depth == 0 else getattr(self, "_lines", [])
        if depth == 0:
            self._lines = []

        def active() -> bool:
            return all(f["active"] for f in stack)

        for raw in lines:
            if self._drop_depth > 0:          # swallowing the rest of a dropped call
                self._drop_depth += self._net_parens(raw)
                continue
            stripped = raw.lstrip()
            if stripped.startswith("`"):
                m = _DIRECTIVE.match(raw)
                name = m.group(1) if m else ""
                rest = m.group(2) if m else ""
                low = name.lower()
                # Only real directive keywords are handled here. Anything else
                # starting with a backtick is a *macro use* in live code, which
                # must be expanded like any other line.
                if low not in _DIRECTIVE_KEYWORDS and low not in _IGNORED:
                    if not active():
                        continue
                    line = self._expand(raw)
                    mac = self._standalone_macro(line)
                    if mac and self._unexpandable(mac[0]):
                        self._unexpanded.add(mac[0])
                        self._drop_depth = mac[1]
                        continue
                    self._lines.append(line)
                    continue
                if low in ("ifdef", "ifndef"):
                    cond = rest.split()[0] if rest.split() else ""
                    parent = active()
                    val = cond in self.defines
                    take = val if low == "ifdef" else not val
                    stack.append({"active": parent and take, "taken": parent and take,
                                  "parent": parent})
                    continue
                if low == "elsif":
                    if not stack:
                        continue
                    top = stack[-1]
                    cond = rest.split()[0] if rest.split() else ""
                    take = (not top["taken"]) and cond in self.defines and top["parent"]
                    top["active"] = take
                    top["taken"] = top["taken"] or take
                    continue
                if low == "else":
                    if not stack:
                        continue
                    top = stack[-1]
                    take = (not top["taken"]) and top["parent"]
                    top["active"] = take
                    top["taken"] = True
                    continue
                if low == "endif":
                    if stack:
                        stack.pop()
                    continue
                if not active():
                    continue
                if low == "define":
                    self._define(rest)
                    continue
                if low == "undef":
                    self.defines.pop(rest.split()[0] if rest.split() else "", None)
                    continue
                if low == "include":
                    self._include(raw, path, out, depth)
                    continue
                if low in _IGNORED:
                    continue
                # unreachable for known keywords; kept for safety
                self._unexpanded.add(name)
                continue
            if not active():
                continue
            line = self._expand(raw)
            mac = self._standalone_macro(line)
            if mac and self._unexpandable(mac[0]):
                # an assertion/coverage macro that was never defined (usually
                # because its `ifdef was false). It expands to no dependency of
                # ours, so drop the statement and record it rather than leaving
                # text the parser will reject.
                self._unexpanded.add(mac[0])
                self._drop_depth = mac[1]
                continue
            self._lines.append(line)

    def _define(self, rest: str) -> None:
        m = _DEFINE.match("`define " + rest)
        if not m:
            return
        name, params, body = m.group(1), m.group(3), m.group(4)
        self.defines[name] = (params, body) if params is not None else body

    def _include(self, raw: str, path: str, out: Preprocessed, depth: int) -> None:
        m = _INCLUDE.match(raw)
        if not m:
            return
        name = m.group(1)
        found = self.resolve(name, path)
        if not found:
            self._unresolved.append(name)
            return
        inc_path, text = found
        self._includes.append(inc_path)
        self._run(text, inc_path, out, depth + 1)

    def _expand(self, line: str) -> str:
        def repl(m):
            name = m.group(1)
            if name not in self.defines:
                return m.group(0)
            body = self.defines[name]
            if isinstance(body, tuple):        # function-like used without args
                return m.group(0)
            return body
        # Only object-like macros are expanded. Function-like macros in real RTL
        # are assertion/utility macros whose bodies use `" stringification and
        # `` token pasting; substituting them with a naive expander corrupts the
        # source, so they are left alone (and dropped when used as a statement).
        for _ in range(4):                     # bounded fixpoint for nesting
            before = line
            line = _MACRO_USE.sub(repl, line)
            if line == before:
                break
        return line

    def _unexpandable(self, name: str) -> bool:
        """True if this macro cannot be safely substituted into code."""
        body = self.defines.get(name)
        return name not in self.defines or isinstance(body, tuple)

    def _expand_calls(self, line: str) -> str:
        out, i = [], 0
        while i < len(line):
            m = _MACRO_USE.match(line, i)
            if not m:
                out.append(line[i])
                i += 1
                continue
            name = m.group(1)
            body = self.defines.get(name)
            if not isinstance(body, tuple):
                out.append(m.group(0))
                i = m.end()
                continue
            params, repl = body
            j = m.end()
            while j < len(line) and line[j] == " ":
                j += 1
            if j >= len(line) or line[j] != "(":
                out.append(m.group(0))
                i = m.end()
                continue
            args, j = self._read_args(line, j)
            names = [p.strip() for p in params.split(",")] if params.strip() else []
            text = repl
            for pname, arg in zip(names, args):
                text = re.sub(rf"\b{re.escape(pname)}\b", arg.strip(), text)
            out.append(text)
            i = j
        return "".join(out)

    @staticmethod
    def _read_args(line: str, i: int) -> tuple[list[str], int]:
        depth, args, cur = 0, [], []
        while i < len(line):
            c = line[i]
            if c == "(":
                depth += 1
                if depth == 1:
                    i += 1
                    continue
            elif c == ")":
                depth -= 1
                if depth == 0:
                    args.append("".join(cur))
                    return args, i + 1
            elif c == "," and depth == 1:
                args.append("".join(cur))
                cur = []
                i += 1
                continue
            cur.append(c)
            i += 1
        return args, i

    @staticmethod
    def _standalone_macro(line: str) -> tuple[str, int] | None:
        """If the line is nothing but a macro call, return (name, open_parens_left).

        A call may span lines (`` `ASSERT(name,\n  expr)``), so the caller needs
        to know how many parens are still open and swallow the rest of the call.
        """
        s = line.strip()
        if not s.startswith("`"):
            return None
        m = _MACRO_USE.match(s)
        if not m:
            return None
        rest = s[m.end():].strip()
        depth = 0
        if rest.startswith("("):
            depth = 1
            i = 1
            while i < len(rest) and depth:
                if rest[i] == "(":
                    depth += 1
                elif rest[i] == ")":
                    depth -= 1
                i += 1
            rest = rest[i:].strip() if depth == 0 else ""
        if depth > 0:
            return m.group(1), depth          # call continues on the next line
        return (m.group(1), 0) if rest in ("", ";") else None

    @staticmethod
    def _net_parens(line: str) -> int:
        return line.count("(") - line.count(")")

    @staticmethod
    def _join_continuations(lines: list[str]) -> list[str]:
        out: list[str] = []
        buf = ""
        for ln in lines:
            if ln.rstrip().endswith("\\"):
                buf += ln.rstrip()[:-1]
                continue
            out.append(buf + ln)
            buf = ""
        if buf:
            out.append(buf)
        return out


def make_resolver(files: dict[str, str], include_dirs: list[str]):
    """Resolve an include name against the file set, then the include path."""
    index: dict[str, str] = {}
    for path in files:
        index.setdefault(os.path.basename(path), path)

    def resolve(name: str, from_path: str) -> tuple[str, str] | None:
        base = os.path.basename(name)
        if base in index:
            return index[base], files[index[base]]
        for d in list(include_dirs) + [os.path.dirname(from_path)]:
            cand = os.path.join(d, name)
            if cand in files:
                return cand, files[cand]
            if os.path.isfile(cand):
                with open(cand, "r", errors="replace") as f:
                    return cand, f.read()
        return None

    return resolve
