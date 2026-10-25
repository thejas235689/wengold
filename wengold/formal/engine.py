"""Formal engines.

Two backends answer the same question about the same IR:

* **explicit** — explicit-state reachability. Complete and sound over a finite
  state space: it proves the property if it reaches a fixpoint, and reports
  BOUNDED if it stops early (a state cap) or the input space is not complete.
* **z3** — symbolic bounded model checking plus k-induction over bit-vectors.
  k-induction proves the property for *all* reachable states when it closes.

Neither pretends: a run that neither proves nor finds a counterexample is
BOUNDED, not a pass, and anything unsupported is UNKNOWN.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..kernel.contract import Establishes
from .ir import Property, PropertyKind
from .rtl_model import Model, UnsupportedConstruct, eval_int, parse_expr

try:  # z3 is optional; the explicit engine always works
    import z3
    _HAVE_Z3 = True
except Exception:  # pragma: no cover
    z3 = None
    _HAVE_Z3 = False

MAX_BV_WIDTH = 32


class FormalStatus(str, Enum):
    PROOF = "proof"        # holds for all reachable states
    BOUNDED = "bounded"    # no counterexample found up to the bound / state cap
    FAIL = "fail"          # a counterexample exists
    UNKNOWN = "unknown"    # could not be decided


_ESTABLISHES = {
    FormalStatus.PROOF: Establishes.PROOF,
    FormalStatus.BOUNDED: Establishes.BOUNDED_CHECK,
    FormalStatus.FAIL: Establishes.NONE,
    FormalStatus.UNKNOWN: Establishes.NONE,
}


@dataclass
class FormalResult:
    property: str
    status: FormalStatus
    engine: str
    depth: int | None = None
    trace: list | None = None
    detail: str = ""

    @property
    def establishes(self) -> Establishes:
        return _ESTABLISHES[self.status]

    @property
    def settled(self) -> bool:
        return self.status in (FormalStatus.PROOF, FormalStatus.FAIL)

    def as_dict(self) -> dict:
        return {"property": self.property, "status": self.status.value,
                "engine": self.engine, "depth": self.depth, "detail": self.detail,
                "establishes": self.establishes.value,
                "trace": self.trace[:4] if self.trace else None}


# ---------------------------------------------------------------- helpers
def _env_of(model: Model, state: dict, inputs: dict) -> dict:
    env = dict(state)
    env.update(inputs)
    if model.rtl:
        for lhs, ast in model.rtl.assigns:
            env[lhs] = eval_int(ast, env, model.rtl.params) & (
                (1 << model.widths.get(lhs, 32)) - 1 if 0 < model.widths.get(lhs, 32) <= 63
                else (1 << 63) - 1)
    return env


def _compile(props: list[Property]) -> tuple[list, list]:
    """Split into (assumes, asserts) as parsed ASTs."""
    assumes = [parse_expr(tokenise_expr(p.expr)) for p in props if p.kind is PropertyKind.ASSUME]
    asserts = [(p, parse_expr(tokenise_expr(p.expr)))
               for p in props if p.kind is not PropertyKind.ASSUME]
    return assumes, asserts


def tokenise_expr(expr: str) -> list[str]:
    from .rtl_model import tokenize
    return tokenize(expr)


# ---------------------------------------------------------------- explicit
def explicit_check(model: Model, props: list[Property], max_states: int = 20000,
                   max_depth: int | None = None) -> list[FormalResult]:
    assumes, asserts = _compile(props)
    results: dict[str, FormalResult] = {}
    safety = [(p, a) for p, a in asserts if p.kind is PropertyKind.SAFETY]
    cover = [(p, a) for p, a in asserts if p.kind is PropertyKind.COVER]
    for p, _a in asserts:
        results[p.name] = FormalResult(p.name, FormalStatus.PROOF, "explicit",
                                       detail="not yet checked")

    start = dict(model.state0)
    frontier = [(start, [dict(start)])]
    visited = {tuple(sorted(start.items()))}
    depth = 0
    truncated = False

    while frontier:
        if len(visited) > max_states or (max_depth is not None and depth >= max_depth):
            truncated = True
            break
        nxt: list = []
        for state, path in frontier:
            for inp, successor in model.successors(state):
                env = _env_of(model, state, inp)
                if any(eval_int(a, env, model.rtl.params if model.rtl else {}) == 0
                       for a in assumes):
                    continue
                for p, ast in safety:
                    if eval_int(ast, env, model.rtl.params if model.rtl else {}) == 0:
                        results[p.name] = FormalResult(
                            p.name, FormalStatus.FAIL, "explicit", depth=depth,
                            trace=path + [{"inputs": inp, "state": env}],
                            detail=f"counterexample at step {depth}")
                for p, ast in cover:
                    if eval_int(ast, env, model.rtl.params if model.rtl else {}) != 0:
                        results[p.name] = FormalResult(
                            p.name, FormalStatus.PROOF, "explicit", depth=depth,
                            trace=path + [{"inputs": inp, "state": env}],
                            detail="cover reached")
                key = tuple(sorted(successor.items()))
                if key not in visited:
                    visited.add(key)
                    nxt.append((successor, path + [{"inputs": inp, "state": env}]))
        frontier = nxt
        depth += 1

    for p, _a in safety:
        if results[p.name].status is FormalStatus.PROOF:
            if truncated or not model.complete_inputs:
                results[p.name] = FormalResult(
                    p.name, FormalStatus.BOUNDED, "explicit", depth=depth,
                    detail=("state cap reached" if truncated
                            else "input space not complete"))
            else:
                results[p.name] = FormalResult(
                    p.name, FormalStatus.PROOF, "explicit", depth=depth,
                    detail="fixpoint reached; holds in all reachable states")
    for p, _a in cover:
        if results[p.name].status is FormalStatus.PROOF and results[p.name].detail == "not yet checked":
            results[p.name] = FormalResult(p.name, FormalStatus.FAIL, "explicit",
                                           detail="target not reachable")
    return [results[p.name] for p, _a in asserts]


# ---------------------------------------------------------------- z3
def _bv_width(model: Model) -> int:
    w = max([8] + [v for v in model.widths.values() if v > 0])
    if w > MAX_BV_WIDTH:
        raise UnsupportedConstruct(f"signal wider than {MAX_BV_WIDTH} bits")
    return w


def _z3_expr(node, env: dict, params: dict, W: int):
    k = node[0]
    if k == "num":
        return z3.BitVecVal(node[1], W)
    if k == "id":
        name = node[1]
        if name in env:
            return env[name]
        if name in params:
            return z3.BitVecVal(params[name], W)
        raise UnsupportedConstruct(f"unknown signal {name!r}")
    if k == "un":
        v = _z3_expr(node[2], env, params, W)
        return {"~": lambda x: ~x, "!": lambda x: z3.If(x == 0, 1, 0),
                "-": lambda x: -x, "+": lambda x: x}[node[1]](v)
    if k == "bin":
        op = node[1]
        if op in ("/", "%"):
            raise UnsupportedConstruct("division is not supported by the z3 backend")
        a = _z3_expr(node[2], env, params, W)
        b = _z3_expr(node[3], env, params, W)
        f = {
            "+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b,
            "&": lambda: a & b, "|": lambda: a | b, "^": lambda: a ^ b,
            "<<": lambda: a << b, ">>": lambda: z3.LShR(a, b),
            "==": lambda: z3.If(a == b, 1, 0), "!=": lambda: z3.If(a != b, 1, 0),
            "<": lambda: z3.If(z3.ULT(a, b), 1, 0), "<=": lambda: z3.If(z3.ULE(a, b), 1, 0),
            ">": lambda: z3.If(z3.UGT(a, b), 1, 0), ">=": lambda: z3.If(z3.UGE(a, b), 1, 0),
            "&&": lambda: z3.If(z3.And(a != 0, b != 0), 1, 0),
            "||": lambda: z3.If(z3.Or(a != 0, b != 0), 1, 0),
        }[op]()
        return f
    if k == "tern":
        return z3.If(_z3_expr(node[1], env, params, W) != 0,
                     _z3_expr(node[2], env, params, W), _z3_expr(node[3], env, params, W))
    if k == "sel":
        # every value in this encoding is W bits wide; a single-bit select must
        # be zero-extended like a slice, or it meets W-bit constants at a
        # different sort and z3 rejects the expression
        v = _z3_expr(node[1], env, params, W)
        i = _z3_expr(node[2], env, params, W)
        return z3.ZeroExt(W - 1, z3.Extract(0, 0, z3.LShR(v, i)))
    if k == "part":
        v = _z3_expr(node[1], env, params, W)
        lo = node[3][1]
        hi = node[2][1]
        return z3.ZeroExt(W - (hi - lo + 1), z3.Extract(hi, lo, v))
    raise UnsupportedConstruct(f"unsupported node {k!r}")


def _sym_assigns(stmts: list, conds: list, env: dict, params: dict, W: int):
    """Symbolic non-blocking assignments: (conditions, target, value).

    The *target* is passed through whole. Unpacking it to a bare name — which
    this did — throws away the slice range, so `q[3:1] <= e` became `q <= e` and
    the transition relation was wrong. A wrong transition relation can prove a
    property that is false, which is the one thing this tool must never do.
    """
    out = []
    for s in stmts:
        if s[0] == "nb":
            out.append((conds, s[1], _z3_expr(s[2], env, params, W)))
        elif s[0] == "block":
            out += _sym_assigns(s[1], conds, env, params, W)
        elif s[0] == "if":
            c = _z3_expr(s[1], env, params, W)
            out += _sym_assigns(s[2][1], conds + [(c, True)], env, params, W)
            out += _sym_assigns(s[3][1], conds + [(c, False)], env, params, W)
    return out


def _cond_expr(conds, W: int):
    terms = []
    for c, positive in conds:
        terms.append(c != 0 if positive else c == 0)
    return z3.And(*terms) if terms else z3.BoolVal(True)


def z3_check(model: Model, props: list[Property], depth: int = 12,
             induction: bool = True) -> list[FormalResult]:
    if not _HAVE_Z3:
        return [FormalResult(p.name, FormalStatus.UNKNOWN, "z3",
                             detail="z3 is not installed") for p in props]
    if model.rtl is None:
        return [FormalResult(p.name, FormalStatus.UNKNOWN, "z3",
                             detail="no RTL attached to the model") for p in props]
    rtl = model.rtl
    try:
        W = _bv_width(model)
    except UnsupportedConstruct as e:
        return [FormalResult(p.name, FormalStatus.UNKNOWN, "z3", detail=str(e)) for p in props]

    assumes, asserts = _compile(props)
    regs = sorted(rtl.registered)
    ins = sorted(rtl.inputs)

    # state and input vectors per step
    s = [{r: z3.BitVec(f"{r}_{i}", W) for r in regs} for i in range(depth + 2)]
    inp = [{n: z3.BitVec(f"{n}_{i}", W) for n in ins} for i in range(depth + 2)]

    def env_at(i):
        env = dict(s[i])
        # constrain each input to its declared width so the solver cannot pick
        # values the hardware could never present
        for n in ins:
            w = min(model.widths.get(n, 1), W)
            env[n] = inp[i][n] & z3.BitVecVal((1 << w) - 1, W)
        for lhs, ast in rtl.assigns:
            env[lhs] = _z3_expr(ast, env, rtl.params, W)
        return env

    def next_from(i):
        env = env_at(i)
        assigns = []
        for _clk, stmts in rtl.always_ff:
            assigns += _sym_assigns(stmts, [], env, rtl.params, W)
        nxt = {}
        for conds, target, val in reversed(assigns):
            if isinstance(target, tuple) and target[0] == "slice":
                # a partial write: keep the bits outside the slice, and merge into
                # the value accumulated so far so two slices of one register under
                # different conditions both apply
                _, name, hi, lo = target
                width = hi - lo + 1
                mask = ((1 << width) - 1) << lo
                keep = z3.BitVecVal(~mask & ((1 << W) - 1), W)
                take = z3.BitVecVal((1 << width) - 1, W)
                prev = nxt.get(name, s[i].get(name, z3.BitVecVal(0, W)))
                merged = (prev & keep) | ((val & take) << lo)
                nxt[name] = z3.If(_cond_expr(conds, W), merged, prev)
                continue
            name = target[1] if isinstance(target, tuple) else target
            prev = nxt.get(name, s[i].get(name, z3.BitVecVal(0, W)))
            nxt[name] = z3.If(_cond_expr(conds, W), val, prev)
        return nxt

    try:
        transitions = [next_from(i) for i in range(depth + 1)]
        envs = [env_at(i) for i in range(depth + 2)]
        assume_terms = [_z3_expr(a, envs[i], rtl.params, W) != 0
                        for i in range(depth + 1) for a in assumes]
        init_terms = [s[0][r] == model.state0.get(r, 0) for r in regs]
    except UnsupportedConstruct as e:
        return [FormalResult(p.name, FormalStatus.UNKNOWN, "z3", detail=str(e)) for p in props]

    results: list[FormalResult] = []
    for p, ast in asserts:
        if p.kind is PropertyKind.SAFETY:
            results.append(_z3_safety(p, ast, s, envs, transitions, init_terms,
                                      assume_terms, depth, induction, rtl, regs, ins,
                                      W, model.widths))
        else:
            results.append(_z3_cover(p, ast, s, envs, transitions, init_terms,
                                     assume_terms, depth, rtl, ins, W))
    return results


def _z3_safety(p, ast, s, envs, transitions, init_terms, assume_terms, depth,
               induction, rtl, regs, ins, W, widths):
    for i in range(depth + 1):
        sol = z3.Solver()
        sol.add(*init_terms, *assume_terms)
        for j in range(i):
            sol.add(*[s[j + 1][r] == transitions[j][r] for r in regs])
        sol.add(_z3_expr(ast, envs[i], rtl.params, W) == 0)
        if sol.check() == z3.sat:
            m = sol.model()
            trace = [{"step": k,
                      "inputs": {n: _val(m, z3.BitVec(f"{n}_{k}", W))
                                 & ((1 << min(widths.get(n, 1), W)) - 1)
                                 for n in ins}}
                     for k in range(i + 1)]
            return FormalResult(p.name, FormalStatus.FAIL, "z3", depth=i, trace=trace,
                                detail=f"counterexample within {i} step(s)")
    if induction:
        k = depth
        sol = z3.Solver()
        sol.add(*assume_terms)
        for i in range(k):
            sol.add(*[s[i + 1][r] == transitions[i][r] for r in regs])
            sol.add(_z3_expr(ast, envs[i], rtl.params, W) != 0)
        sol.add(_z3_expr(ast, envs[k], rtl.params, W) == 0)
        if sol.check() == z3.unsat:
            return FormalResult(p.name, FormalStatus.PROOF, "z3", depth=k,
                                detail=f"k-induction closed at k={k}")
    return FormalResult(p.name, FormalStatus.BOUNDED, "z3", depth=depth,
                        detail=f"no counterexample within {depth} step(s)")


def _z3_cover(p, ast, s, envs, transitions, init_terms, assume_terms, depth, rtl, ins, W):
    for i in range(depth + 1):
        sol = z3.Solver()
        sol.add(*init_terms, *assume_terms)
        for j in range(i):
            sol.add(*[s[j + 1][r] == transitions[j][r] for r in rtl.registered])
        sol.add(_z3_expr(ast, envs[i], rtl.params, W) != 0)
        if sol.check() == z3.sat:
            return FormalResult(p.name, FormalStatus.PROOF, "z3", depth=i,
                                detail=f"cover reached at step {i}")
    return FormalResult(p.name, FormalStatus.FAIL, "z3", depth=depth,
                        detail=f"cover not reached within {depth} step(s)")


def _val(model, var):
    v = model.eval(var, model_completion=True)
    try:
        return v.as_long()
    except Exception:
        return 0


# ---------------------------------------------------------------- dispatch
def check(model: Model, props: list[Property], engine: str = "auto",
          depth: int = 12, max_states: int = 20000) -> list[FormalResult]:
    """Run the requested engine (or the best available)."""
    if engine == "z3":
        return z3_check(model, props, depth=depth)
    if engine == "explicit":
        return explicit_check(model, props, max_states=max_states)
    # auto: try z3 (it can prove unbounded), fall back to explicit
    if _HAVE_Z3 and model.rtl is not None:
        results = z3_check(model, props, depth=depth)
        if all(r.status is not FormalStatus.UNKNOWN for r in results):
            return results
    return explicit_check(model, props, max_states=max_states)
