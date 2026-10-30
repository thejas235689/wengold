"""Static clock-domain-crossing analysis.

This is the part the CDC work has been missing. Everything up to v0.49.0 read and
wrote the Accellera format and checked the collateral for internal consistency — it
never looked at whether a crossing was synchronised. That was stated honestly every
time, and this closes it.

What it does
------------
For each module it finds, from the syntax tree:

  * which signals are **written** under which clock edge
  * which signals are **read** under which clock edge
  * a signal written under clock A and read under clock B is a **crossing**

Then it classifies each crossing:

  ``synchronised``   the crossing signal feeds a flop whose output feeds a second
                     flop on the same destination clock — the 2-FF pattern
  ``unsynchronised`` it reaches combinational logic or a single flop directly
  ``unknown``        the source module is outside the subset we can read

What it does **not** do
-----------------------
It is not a sign-off CDC tool and it does not claim to be:

  * a 2-FF synchroniser reduces metastability; it does not make multi-bit data
    coherent. A multi-bit bus crossing through 2-FF flops is reported as
    ``synchronised`` with a width warning, because each bit settles independently
    and the value read can be a mixture of old and new.
  * it reads syntax, not elaboration. A generate block or a macro that changes the
    connectivity is invisible to it.
  * a ``unknown`` result is not a pass.

The distinction matters more here than anywhere else in this project: a CDC tool
that says "clean" when it means "I saw nothing" is how CDC bugs reach silicon.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Crossing", "Analysis", "analyse_text", "analyse_files"]


@dataclass
class Crossing:
    signal: str
    width: int
    from_clock: str
    to_clock: str
    verdict: str                 # synchronised | unsynchronised | unknown
    detail: str = ""
    module: str = ""

    @property
    def multi_bit(self) -> bool:
        return self.width > 1

    def as_dict(self) -> dict:
        return {"signal": self.signal, "width": self.width,
                "from": self.from_clock, "to": self.to_clock,
                "verdict": self.verdict, "detail": self.detail,
                "module": self.module}


@dataclass
class Analysis:
    modules: list[str] = field(default_factory=list)
    crossings: list[Crossing] = field(default_factory=list)
    clocks: dict = field(default_factory=dict)          # module -> set of clocks
    notes: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    # per-module, for classifying crossings another detector found:
    # (clock, lhs, rhs) flop pairs and declared widths
    seq: dict = field(default_factory=dict)
    widths: dict = field(default_factory=dict)

    @property
    def unsynchronised(self) -> list[Crossing]:
        return [c for c in self.crossings if c.verdict == "unsynchronised"]

    @property
    def clean(self) -> bool:
        """True only when every crossing was classified as synchronised.

        Deliberately NOT true when there are no crossings *or* when some are
        unknown — "I saw nothing" is not "there is nothing".
        """
        return bool(self.crossings) and all(
            c.verdict == "synchronised" for c in self.crossings)

    def render(self) -> str:
        lines = []
        if not self.modules:
            return "  no modules read"
        for m in self.modules:
            cs = [c for c in self.crossings if c.module == m]
            cl = sorted(self.clocks.get(m, ()))
            lines.append(f"  {m}: {len(cl)} clock(s) {', '.join(cl) or '-'}, "
                         f"{len(cs)} crossing(s)")
            for c in cs:
                tag = c.verdict
                warn = "  [multi-bit: 2FF does not make a bus coherent]" \
                    if (c.verdict == "synchronised" and c.multi_bit) else ""
                lines.append(f"    {c.signal} [{c.width}]  {c.from_clock} -> "
                             f"{c.to_clock}   {tag}{warn}")
                if c.detail:
                    lines.append(f"      {c.detail}")
        for n in self.notes:
            lines.append(f"  ! {n}")
        if self.unreadable:
            lines.append(f"  ! {len(self.unreadable)} file(s) outside the readable "
                         f"subset: {', '.join(Path(p).name for p in self.unreadable[:4])}")
        if not self.crossings and self.modules:
            lines.append("  no crossings found — that is not the same as clean")
        return "\n".join(lines)


def _walk(node):
    yield node
    try:
        kids = list(node)
    except TypeError:
        return
    for c in kids:
        yield from _walk(c)


def _text(n) -> str:
    """The source text of a node.

    `IdentifierName` has no `valueText` — only some node kinds do — so `str(n)`
    is the general fallback. Reading only `valueText` silently produced empty
    names, and every signal came back as `''`.
    """
    if n is None:
        return ""
    try:
        v = n.valueText
        if v:
            return v
    except Exception:
        pass
    return str(n).strip()


def _idents(n) -> set[str]:
    """Every identifier name under a node."""
    return {_text(x) for x in _walk(n)
            if str(getattr(x, "kind", "")).endswith("IdentifierName")}


def _clock_of(block) -> str | None:
    """The clock a timed block is sensitive to.

    `SignalEventExpression` exposes `.edge` and `.expr` directly — walking its
    children for a PosEdgeKeyword token found the edge but not the name, so every
    block came back with no clock.
    """
    for n in _walk(block):
        if str(getattr(n, "kind", "")).endswith("SignalEventExpression"):
            name = _text(getattr(n, "expr", None))
            if name:
                return name
    return None


def analyse_text(src: str, path: str = "<text>") -> Analysis:
    """Crossings in one SystemVerilog source."""
    out = Analysis()
    try:
        import pyslang
    except ImportError:
        out.notes.append("pyslang is not installed, so no analysis was possible")
        return out

    tree = pyslang.syntax.SyntaxTree.fromText(src, name=path)
    if any(d.isError() for d in tree.diagnostics):
        out.unreadable.append(path)
        out.notes.append(f"{Path(path).name} has parse errors and was not analysed")
        return out

    for node in _walk(tree.root):
        if not str(getattr(node, "kind", "")).endswith("ModuleDeclaration"):
            continue
        name = _text(getattr(getattr(node, "header", None), "name", None))
        if not name:
            continue
        out.modules.append(name)
        widths = _signal_widths(node)
        writes: dict[str, set[str]] = {}
        reads: dict[str, set[str]] = {}
        seq_pairs: list[tuple[str, str, str]] = []      # (clock, lhs, rhs)

        for blk in _walk(node):
            if not str(getattr(blk, "kind", "")).endswith("AlwaysFFBlock"):
                continue
            clk = _clock_of(blk)
            if not clk:
                continue
            for a in _walk(blk):
                if not str(getattr(a, "kind", "")).endswith(
                        "NonblockingAssignmentExpression"):
                    continue
                lhs = getattr(a, "left", None)
                rhs = getattr(a, "right", None)
                lnames = _idents(lhs) if lhs is not None else set()
                rnames = _idents(rhs) if rhs is not None else set()
                for s in lnames:
                    writes.setdefault(s, set()).add(clk)
                for s in rnames:
                    reads.setdefault(s, set()).add(clk)
                if len(lnames) == 1 and len(rnames) == 1:
                    seq_pairs.append((clk, next(iter(lnames)), next(iter(rnames))))

        # combinational reads count as reads on every clock the module uses
        clocks = {c for cs in writes.values() for c in cs}
        for a in _walk(node):
            if not str(getattr(a, "kind", "")).endswith("ContinuousAssign"):
                continue
            for s in _idents(getattr(a, "expr", None) or a):
                for c in clocks:
                    reads.setdefault(s, set()).add(c)

        out.clocks[name] = clocks
        out.seq[name] = seq_pairs
        out.widths[name] = widths
        if len(clocks) < 2:
            continue

        for sig, wclocks in sorted(writes.items()):
            rclocks = reads.get(sig, set())
            for a in sorted(wclocks):
                for b in sorted(rclocks):
                    if a == b:
                        continue
                    verdict, detail = _classify(sig, a, b, seq_pairs, widths)
                    out.crossings.append(Crossing(
                        signal=sig, width=widths.get(sig, 1),
                        from_clock=a, to_clock=b, verdict=verdict,
                        detail=detail, module=name))
    return out


def _classify(sig: str, a: str, b: str, pairs, widths) -> tuple[str, str]:
    """Is the crossing signal synchronised into clock b?

    The 2-FF pattern: `m <= sig` on clock b, and `s <= m` on clock b as well. If
    only one flop follows the crossing, a single event can still be metastable.
    """
    first = [lhs for (clk, lhs, rhs) in pairs if clk == b and rhs == sig]
    if not first:
        return ("unsynchronised",
                f"read on {b} with no flop in between")
    for mid in first:
        second = [lhs for (clk, lhs, rhs) in pairs if clk == b and rhs == mid]
        if second:
            w = widths.get(sig, 1)
            if w > 1:
                return ("synchronised",
                        f"{mid} -> {second[0]} on {b}, but {sig} is {w} bits: each "
                        f"bit settles independently, so the value read can mix old "
                        f"and new")
            return ("synchronised", f"{mid} -> {second[0]} on {b} (2-FF)")
    return ("unsynchronised",
            f"{sig} reaches {first[0]} on {b} but no second flop follows")


def _signal_widths(node) -> dict[str, int]:
    """Declared widths, so a multi-bit crossing can be called out."""
    out: dict[str, int] = {}
    for n in _walk(node):
        k = str(getattr(n, "kind", ""))
        if not k.endswith("DataDeclaration"):
            continue
        # the packed range lives in a VariableDimension (`logic [7:0] x`), not an
        # ElementSelect — looking for the wrong kind silently reported every
        # signal as one bit wide, which hides the multi-bit 2-FF hazard entirely
        width = 1
        for d in _walk(n):
            if str(getattr(d, "kind", "")).endswith("VariableDimension"):
                m = re.search(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", _text(d))
                if m:
                    hi, lo = int(m.group(1)), int(m.group(2))
                    width = abs(hi - lo) + 1
        for d in _walk(n):
            if str(getattr(d, "kind", "")).endswith("Declarator"):
                nm = _text(getattr(d, "name", None))
                if nm:
                    out.setdefault(nm, width)
    return out


def classify(report, analysis: "Analysis") -> list:
    """Annotate the crossings a detector found with synchronisation and width.

    `graph.cdc.analyse` already finds crossings — including ones that reach the
    destination through combinational logic, which a flop-to-flop walk misses. So
    this does not re-detect them; it says whether each one is synchronised, which
    is the question the existing report could not answer.
    """
    out = []
    for c in getattr(report, "crossings", []):
        mod = getattr(c, "module", "")
        pairs = analysis.seq.get(mod, [])
        widths = analysis.widths.get(mod, {})
        src = getattr(c, "from_domain", "")
        dst = getattr(c, "to_domain", "")
        verdict, detail = _classify(c.signal, src, dst, pairs, widths)
        if getattr(c, "kind", "") == "through_combinational":
            detail = (f"reaches {dst} through combinational logic, so a 2-FF "
                      f"synchroniser cannot be present")
            verdict = "unsynchronised"
        out.append(Crossing(signal=c.signal, width=widths.get(c.signal, 1),
                            from_clock=src, to_clock=dst, verdict=verdict,
                            detail=detail, module=mod))
    return out


def analyse_files(paths, root: str = ".") -> Analysis:
    merged = Analysis()
    for p in paths:
        try:
            src = Path(p).read_text(errors="replace")
        except OSError:
            merged.unreadable.append(str(p))
            continue
        a = analyse_text(src, str(p))
        merged.modules += a.modules
        merged.crossings += a.crossings
        merged.notes += a.notes
        merged.unreadable += a.unreadable
        for m, c in a.clocks.items():
            merged.clocks.setdefault(m, set()).update(c)
        merged.seq.update(a.seq)
        merged.widths.update(a.widths)
    return merged
