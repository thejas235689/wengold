"""A bounded RTL front-end: a documented SystemVerilog subset to an executable model.

The formal engines need a *model* of the design. This module parses a small,
explicitly documented subset of SystemVerilog and turns it into a transition
function, so the in-process engines can run with no external tool.

Supported:

* `module NAME ( ports ); ... endmodule`
* port and signal declarations — `input`/`output`/`inout`, `logic`/`wire`/`reg`/`bit`,
  optional `[msb:lsb]`, comma-separated names
* `parameter [int] NAME = <constant>;`
* continuous `assign lhs = expr;`
* `always_ff @(posedge clk) <stmt>` with non-blocking `<=` assignments,
  `if`/`else` and `begin`/`end`
* expressions: identifiers, sized and unsized literals, `~ ! - +`, `+ - * / %`,
  `& | ^`, `== != < <= > >=`, `<< >>`, `&& ||`, ternary `?:`, parentheses,
  bit-select `x[i]` and part-select `x[a:b]`

Anything outside the subset raises `UnsupportedConstruct`, and the caller reports
UNKNOWN rather than guessing. A full IEEE front-end (Surelog / sv-parser) is the
intended production backend; this one exists so the engine is testable and usable
with no install.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<comment>//[^\n]*|/\*.*?\*/)
  | (?P<num>\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_]+|\d+)
  | (?P<id>[A-Za-z_]\w*)
  | (?P<op><<=|>>=|===|!==|==|!=|<=|>=|<<|>>|&&|\|\||[-+*/%&|^~!<>=?:;,.()\[\]@#])
""", re.VERBOSE | re.DOTALL)

_DIRECTIONS = {"input", "output", "inout"}
_TYPES = {"logic", "wire", "reg", "bit", "int", "signed", "unsigned"}
_BASES = {"b": 2, "o": 8, "d": 10, "h": 16}


class UnsupportedConstruct(Exception):
    """Raised when the source uses something outside the documented subset."""


def tokenize(text: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    out, i = [], 0
    while i < len(text):
        m = TOKEN_RE.match(text, i)
        if not m:
            raise UnsupportedConstruct(f"cannot tokenize at {text[i:i+20]!r}")
        i = m.end()
        if m.lastgroup in ("ws", "comment"):
            continue
        out.append(m.group(0))
    return out


def parse_number(tok: str) -> int:
    if "'" not in tok:
        return int(tok)
    size_s, _, rest = tok.partition("'")
    rest = rest.lstrip("sS")
    base_ch, digits = rest[0].lower(), rest[1:].replace("_", "")
    if base_ch not in _BASES:
        raise UnsupportedConstruct(f"bad base in literal {tok!r}")
    if any(c in "xXzZ" for c in digits):
        raise UnsupportedConstruct(f"x/z literal {tok!r} is not supported")
    value = int(digits, _BASES[base_ch])
    if size_s:
        value &= (1 << int(size_s)) - 1
    return value


# ---------------------------------------------------------------- expressions
class _P:
    def __init__(self, toks: list[str]):
        self.t, self.i = toks, 0

    def peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> str:
        tok = self.t[self.i]
        self.i += 1
        return tok

    def accept(self, tok: str) -> bool:
        if self.peek() == tok:
            self.i += 1
            return True
        return False

    def expect(self, tok: str) -> None:
        if not self.accept(tok):
            raise UnsupportedConstruct(f"expected {tok!r}, got {self.peek()!r}")

    # precedence climbing
    def expr(self):
        return self.ternary()

    def ternary(self):
        c = self.binary(1)
        if self.accept("?"):
            a = self.ternary()
            self.expect(":")
            b = self.ternary()
            return ("tern", c, a, b)
        return c

    _LEVELS = [
        ("||",), ("&&",), ("|",), ("^",), ("&",),
        ("==", "!="), ("<", "<=", ">", ">="), ("<<", ">>"),
        ("+", "-"), ("*", "/", "%"),
    ]

    def binary(self, level: int):
        if level > len(self._LEVELS):
            return self.unary()
        ops = self._LEVELS[level - 1]
        node = self.binary(level + 1)
        while self.peek() in ops:
            op = self.take()
            rhs = self.binary(level + 1)
            node = ("bin", op, node, rhs)
        return node

    def unary(self):
        if self.peek() in ("~", "!", "-", "+"):
            op = self.take()
            return ("un", op, self.unary())
        return self.primary()

    def primary(self):
        tok = self.peek()
        if tok is None:
            raise UnsupportedConstruct("unexpected end of expression")
        if tok == "(":
            self.take()
            node = self.expr()
            self.expect(")")
            return node
        if re.match(r"^\d", tok):
            return ("num", parse_number(self.take()))
        if re.match(r"^[A-Za-z_]\w*$", tok):
            name = self.take()
            if self.accept("["):
                hi = self.expr()
                if self.accept(":"):
                    lo = self.expr()
                    self.expect("]")
                    return ("part", ("id", name), hi, lo)
                self.expect("]")
                return ("sel", ("id", name), hi)
            return ("id", name)
        raise UnsupportedConstruct(f"unsupported primary {tok!r}")


def parse_expr(toks: list[str]):
    p = _P(toks)
    node = p.expr()
    if p.peek() is not None:
        raise UnsupportedConstruct(f"trailing tokens: {p.t[p.i:]}")
    return node


def eval_int(node, env: dict, params: dict) -> int:
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "id":
        name = node[1]
        if name in env:
            return env[name]
        if name in params:
            return params[name]
        raise UnsupportedConstruct(f"unknown signal {name!r}")
    if kind == "un":
        v = eval_int(node[2], env, params)
        return {"~": lambda x: ~x, "!": lambda x: 0 if x else 1,
                "-": lambda x: -x, "+": lambda x: x}[node[1]](v)
    if kind == "bin":
        op = node[1]
        a = eval_int(node[2], env, params)
        b = eval_int(node[3], env, params)
        return _BIN[op](a, b)
    if kind == "tern":
        return eval_int(node[2], env, params) if eval_int(node[1], env, params) \
            else eval_int(node[3], env, params)
    if kind == "sel":
        v = eval_int(node[1], env, params)
        i = eval_int(node[2], env, params)
        return (v >> i) & 1
    if kind == "part":
        v = eval_int(node[1], env, params)
        hi = eval_int(node[2], env, params)
        lo = eval_int(node[3], env, params)
        return (v >> lo) & ((1 << (hi - lo + 1)) - 1)
    raise UnsupportedConstruct(f"unsupported node {kind!r}")


def _safe_div(a, b):
    return 0 if b == 0 else int(a / b)


_BIN = {
    "+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b,
    "/": _safe_div, "%": lambda a, b: 0 if b == 0 else a % b,
    "&": lambda a, b: a & b, "|": lambda a, b: a | b, "^": lambda a, b: a ^ b,
    "<<": lambda a, b: a << b, ">>": lambda a, b: a >> b,
    "==": lambda a, b: int(a == b), "!=": lambda a, b: int(a != b),
    "<": lambda a, b: int(a < b), "<=": lambda a, b: int(a <= b),
    ">": lambda a, b: int(a > b), ">=": lambda a, b: int(a >= b),
    "&&": lambda a, b: int(bool(a) and bool(b)), "||": lambda a, b: int(bool(a) or bool(b)),
}


# ---------------------------------------------------------------- module
@dataclass
class RtlModule:
    name: str
    signals: dict[str, int] = field(default_factory=dict)      # name -> width
    directions: dict[str, str] = field(default_factory=dict)
    params: dict[str, int] = field(default_factory=dict)
    assigns: list[tuple[str, tuple]] = field(default_factory=list)
    always_ff: list[tuple[str, list]] = field(default_factory=list)
    clock: str | None = None

    @property
    def registered(self) -> set[str]:
        out: set[str] = set()
        for _clk, stmts in self.always_ff:
            _collect_lhs(stmts, out)
        return out

    @property
    def combinational(self) -> set[str]:
        return {lhs for lhs, _e in self.assigns}

    @property
    def inputs(self) -> set[str]:
        reg = self.registered | self.combinational
        return {n for n, d in self.directions.items()
                if d == "input" and n not in reg and n != self.clock}


def _collect_lhs(stmts: list, out: set[str]) -> None:
    for s in stmts:
        if s[0] == "nb":
            out.add(s[1][1])
        elif s[0] == "if":
            _collect_lhs(s[2][1], out)
            _collect_lhs(s[3][1], out)
        elif s[0] == "block":
            _collect_lhs(s[1], out)


def _width_from_range(toks: list[str]) -> int:
    """Parse `[msb:lsb]` from the front of toks; return width (1 if absent)."""
    if not toks or toks[0] != "[":
        return 1
    inner = []
    i = 1
    while i < len(toks) and toks[i] != "]":
        inner.append(toks[i])
        i += 1
    if ":" in inner:
        msb = int(inner[0])
        lsb = int(inner[-1])
        return abs(msb - lsb) + 1
    return 1


def _consume_range(toks: list[str], i: int) -> tuple[int, int]:
    if i < len(toks) and toks[i] == "[":
        j = i + 1
        while j < len(toks) and toks[j] != "]":
            j += 1
        return _width_from_range(toks[i:j + 1]), j + 1
    return 1, i


def parse_module(text: str) -> RtlModule:
    toks = tokenize(text)
    if not toks or toks[0] != "module":
        raise UnsupportedConstruct("no module declaration found")
    name = toks[1]
    m = RtlModule(name=name)

    # header ports
    i = 2
    if toks[i] != "(":
        raise UnsupportedConstruct("expected port list")
    depth, j = 1, i + 1
    header: list[str] = []
    while j < len(toks) and depth:
        if toks[j] == "(":
            depth += 1
        elif toks[j] == ")":
            depth -= 1
            if depth == 0:
                break
        header.append(toks[j])
        j += 1
    i = j + 1
    if i < len(toks) and toks[i] == ";":
        i += 1
    _parse_decls(header, m)

    # body
    while i < len(toks):
        tok = toks[i]
        if tok == "endmodule":
            break
        if tok == "parameter":
            i = _parse_parameter(toks, i + 1, m)
        elif tok in _DIRECTIONS or tok in _TYPES:
            i = _parse_decls_at(toks, i, m)
        elif tok == "assign":
            i = _parse_assign(toks, i + 1, m)
        elif tok in ("always_ff", "always"):
            i = _parse_always(toks, i + 1, m)
        elif tok == ";":
            i += 1
        elif tok == "generate" or tok == "endgenerate":
            raise UnsupportedConstruct("generate blocks are not supported by the formal front-end")
        else:
            raise UnsupportedConstruct(f"unsupported construct {tok!r}")
    return m


def _parse_decls(toks: list[str], m: RtlModule) -> None:
    """Parse a run of declarations from a token list (header form)."""
    i = 0
    while i < len(toks):
        i = _parse_decls_at(toks, i, m)


def _parse_decls_at(toks: list[str], i: int, m: RtlModule) -> int:
    direction = None
    while i < len(toks) and toks[i] in _DIRECTIONS:
        direction = toks[i]
        i += 1
    while i < len(toks) and toks[i] in _TYPES:
        i += 1
    width, i = _consume_range(toks, i)
    # names until ; or end
    while i < len(toks) and toks[i] != ";":
        name = toks[i]
        if not re.match(r"^[A-Za-z_]\w*$", name):
            raise UnsupportedConstruct(f"bad declaration near {name!r}")
        m.signals[name] = width
        if direction:
            m.directions[name] = direction
        i += 1
        if i < len(toks) and toks[i] == ",":
            i += 1
            # a following name without a new direction inherits
            if i < len(toks) and (toks[i] in _DIRECTIONS or toks[i] in _TYPES):
                return _parse_decls_at(toks, i, m)
        elif i < len(toks) and toks[i] == "=":
            raise UnsupportedConstruct("initialisers in declarations are not supported")
    return i + 1 if i < len(toks) else i


def _parse_parameter(toks: list[str], i: int, m: RtlModule) -> int:
    while i < len(toks) and toks[i] in _TYPES:
        i += 1
    name = toks[i]
    i += 1
    if i >= len(toks) or toks[i] != "=":
        raise UnsupportedConstruct("parameter without a value")
    i += 1
    j = i
    while j < len(toks) and toks[j] != ";":
        j += 1
    m.params[name] = eval_int(parse_expr(toks[i:j]), {}, m.params)
    return j + 1


def _parse_assign(toks: list[str], i: int, m: RtlModule) -> int:
    j = i
    while j < len(toks) and toks[j] != "=":
        j += 1
    lhs_toks = toks[i:j]
    if len(lhs_toks) != 1 or not re.match(r"^[A-Za-z_]\w*$", lhs_toks[0]):
        raise UnsupportedConstruct("assign to a non-simple target")
    k = j + 1
    while k < len(toks) and toks[k] != ";":
        k += 1
    m.assigns.append((lhs_toks[0], parse_expr(toks[j + 1:k])))
    return k + 1


def _parse_always(toks: list[str], i: int, m: RtlModule) -> int:
    if i >= len(toks) or toks[i] != "@":
        raise UnsupportedConstruct("only clocked always blocks are supported")
    i += 1
    if toks[i] != "(":
        raise UnsupportedConstruct("expected sensitivity list")
    depth, j = 1, i + 1
    sens = []
    while j < len(toks) and depth:
        if toks[j] == "(":
            depth += 1
        elif toks[j] == ")":
            depth -= 1
            if depth == 0:
                break
        sens.append(toks[j])
        j += 1
    i = j + 1
    if "posedge" not in sens:
        raise UnsupportedConstruct("only posedge-clocked blocks are supported")
    clock = sens[sens.index("posedge") + 1]
    m.clock = m.clock or clock
    if m.clock != clock:
        raise UnsupportedConstruct("multiple clock domains are not supported")
    m.signals.setdefault(clock, 1)
    m.directions.setdefault(clock, "input")
    stmts, i = _parse_stmt(toks, i)
    m.always_ff.append((clock, stmts[1] if stmts[0] == "block" else [stmts]))
    return i


def _parse_stmt(toks: list[str], i: int) -> tuple:
    tok = toks[i]
    if tok == "begin":
        i += 1
        stmts = []
        while i < len(toks) and toks[i] != "end":
            s, i = _parse_stmt(toks, i)
            stmts.append(s)
        if i >= len(toks):
            raise UnsupportedConstruct("unterminated begin block")
        return ("block", stmts), i + 1
    if tok == "if":
        i += 1
        if toks[i] != "(":
            raise UnsupportedConstruct("expected ( after if")
        depth, j = 1, i + 1
        cond = []
        while j < len(toks) and depth:
            if toks[j] == "(":
                depth += 1
            elif toks[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            cond.append(toks[j])
            j += 1
        cond_ast = parse_expr(cond)
        then_s, i = _parse_stmt(toks, j + 1)
        else_s = ("block", [])
        if i < len(toks) and toks[i] == "else":
            else_s, i = _parse_stmt(toks, i + 1)
        return ("if", cond_ast, then_s if then_s[0] == "block" else ("block", [then_s]),
                else_s if else_s[0] == "block" else ("block", [else_s])), i
    # assignment: lhs <= expr ;
    j = i
    while j < len(toks) and toks[j] not in ("<=", "=", ";"):
        j += 1
    if j >= len(toks) or toks[j] == ";":
        raise UnsupportedConstruct(f"unsupported statement near {tok!r}")
    if toks[j] == "=":
        raise UnsupportedConstruct("blocking assignment in a clocked block is not supported")
    lhs = toks[i:j]
    if len(lhs) != 1 or not re.match(r"^[A-Za-z_]\w*$", lhs[0]):
        raise UnsupportedConstruct("non-blocking assignment to a non-simple target")
    k = j + 1
    while k < len(toks) and toks[k] != ";":
        k += 1
    return ("nb", ("id", lhs[0]), parse_expr(toks[j + 1:k])), k + 1


# ---------------------------------------------------------------- model
@dataclass
class Model:
    name: str
    state0: dict[str, int]
    inputs: dict[str, tuple[int, ...]]
    step: Callable[[dict, dict], dict]
    widths: dict[str, int] = field(default_factory=dict)
    complete_inputs: bool = True
    rtl: RtlModule | None = None

    def successors(self, state: dict):
        names = list(self.inputs)
        for combo in _product([self.inputs[n] for n in names]):
            inp = dict(zip(names, combo))
            yield inp, self.step(state, inp)


def _product(domains):
    if not domains:
        yield ()
        return
    first, rest = domains[0], domains[1:]
    for v in first:
        for tail in _product(rest):
            yield (v,) + tail


MAX_INPUT_DOMAIN = 16


def to_model(rtl: RtlModule, input_domains: dict[str, tuple[int, ...]] | None = None) -> Model:
    reg = rtl.registered
    state0 = {s: 0 for s in reg}
    widths = dict(rtl.signals)
    domains: dict[str, tuple[int, ...]] = {}
    complete = True
    for name in sorted(rtl.inputs):
        w = widths.get(name, 1)
        if input_domains and name in input_domains:
            domains[name] = tuple(input_domains[name])
            continue
        if (1 << w) <= MAX_INPUT_DOMAIN:
            domains[name] = tuple(range(1 << w))
        else:
            domains[name] = (0, 1, (1 << w) - 1)
            complete = False

    def step(state: dict, inputs: dict) -> dict:
        env = dict(state)
        env.update(inputs)
        for lhs, ast in rtl.assigns:
            env[lhs] = _mask(eval_int(ast, env, rtl.params), widths.get(lhs, 32))
        nxt = dict(state)
        for _clk, stmts in rtl.always_ff:
            _exec(stmts, env, rtl.params, nxt, widths)
        return nxt

    return Model(name=rtl.name, state0=state0, inputs=domains, step=step,
                 widths=widths, complete_inputs=complete, rtl=rtl)


def _mask(value: int, width: int) -> int:
    if width <= 0 or width > 63:
        return value
    return value & ((1 << width) - 1)


def _exec(stmts: list, env: dict, params: dict, nxt: dict, widths: dict) -> None:
    for s in stmts:
        kind = s[0]
        if kind == "nb":
            target = s[1][1]
            nxt[target] = _mask(eval_int(s[2], env, params), widths.get(target, 32))
        elif kind == "block":
            _exec(s[1], env, params, nxt, widths)
        elif kind == "if":
            branch = s[2] if eval_int(s[1], env, params) else s[3]
            _exec(branch[1], env, params, nxt, widths)
