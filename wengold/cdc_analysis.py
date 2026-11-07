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

A signal whose only path into the destination domain is combinational
(`assign t = a_reg & en;` and then `q <= t` under the other clock) is a crossing
in its own right. It is reported against the combinational node, not only against
the flop that wrote `a_reg`, because that node is what the destination samples.

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
        return [c for c in self.crossings
                if c.verdict in ("unsynchronised", "synchronised_data_hazard")]

    @property
    def clean(self) -> bool:
        """True only when every crossing was classified as synchronised.

        Deliberately NOT true when there are no crossings *or* when some are
        unknown — "I saw nothing" is not "there is nothing".

        Also NOT true for a combinational path into the synchroniser. The 2-FF
        still resolves metastability, so the verdict stays `synchronised` — but
        Clause 4.3.10 separates `internal_sync` from `combo`/`glitch_free_combo`
        on the path, and a glitch on the input presents a transition the
        synchroniser then passes on faithfully. Saying "clean" there is an
        overclaim, and this tool does not overclaim. `graph/cdc.py` already
        reports this shape as `through_combinational` and never as safe; the two
        now agree that it is not clean.
        """
        return bool(self.crossings) and all(
            c.verdict == "synchronised" and "combinational" not in c.detail.lower()
            for c in self.crossings)

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
        writes: dict[str, set[str]] = {}                # signal -> clocks writing it
        reads: dict[str, set[str]] = {}                 # signal -> clocks reading it
        comb: dict[str, set[str]] = {}                  # comb target -> what it reads
        seq_pairs: list[tuple[str, str, str]] = []      # (clock, lhs, rhs)

        for blk in _walk(node):
            kind = str(getattr(blk, "kind", ""))
            if kind.endswith(("AlwaysCombBlock", "AlwaysLatchBlock", "AlwaysBlock")) \
                    and not _clock_of(blk):
                # A procedural block with no edge trigger is combinational. Its
                # targets are not clocked, but their value still comes from
                # somewhere: `assign comb = reg_a & 1'b1` carries a value out of
                # reg_a's domain, and until this was recorded the only crossings
                # this function could see were ones a flop wrote directly.
                body = getattr(blk, "statement", None)
                if body is None:
                    continue
                for a in _walk(body):
                    if not str(getattr(a, "kind", "")).endswith(
                            "AssignmentExpression"):
                        continue
                    lnames = _idents(getattr(a, "left", None))
                    rnames = _idents(getattr(a, "right", None))
                    for s in lnames:
                        comb.setdefault(s, set()).update(rnames - {s})
                continue
            if not kind.endswith("AlwaysFFBlock"):
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
                # Every nonblocking assignment, with the full set of names it
                # reads. Recording only `lhs <= rhs` with two bare identifiers
                # lost `y <= meta & en` entirely — which is exactly the shape of a
                # metastable first stage escaping its synchroniser.
                if len(lnames) == 1:
                    seq_pairs.append((clk, next(iter(lnames)), frozenset(rnames)))

        clocks = {c for cs in writes.values() for c in cs}
        # continuous assignments: `assign t = expr;` is combinational logic, and t
        # is what a later flop in another domain actually samples. Previously the
        # identifiers on the right were attributed to *every* clock as reads, which
        # reported the source signal but never the combinational node itself — so a
        # design whose only path into the destination domain went through
        # combinational logic produced no entry for it and `clean` came back True.
        for a in _walk(node):
            if not str(getattr(a, "kind", "")).endswith("ContinuousAssign"):
                continue
            for asg in (getattr(a, "assignments", None) or []):
                lnames = _idents(getattr(asg, "left", None))
                rnames = _idents(getattr(asg, "right", None))
                for s in lnames:
                    comb.setdefault(s, set()).update(rnames - {s})

        out.clocks[name] = clocks
        out.seq[name] = seq_pairs
        out.widths[name] = widths
        if len(clocks) < 2:
            continue

        def domains_of(sig: str, seen: frozenset = frozenset()) -> set[str]:
            """Clocks whose flops drive `sig`, directly or through comb logic."""
            if sig in seen:
                return set()
            seen = seen | {sig}
            found = set(writes.get(sig, ()))
            for r in comb.get(sig, ()):
                found |= domains_of(r, seen)
            return found

        # Walk from the destination side: every signal observed under clock b, and
        # every clock that drives it. A combinational node appears here for the
        # first time — it is read on b but written by no flop, so a walk over
        # `writes` never reached it.
        for b in sorted(clocks):
            for sig in sorted(s for s, cs in reads.items() if b in cs):
                for a in sorted(domains_of(sig) - {b}):
                    if sig in comb:
                        verdict, detail = _classify_combinational(
                            sig, a, b, seq_pairs, widths)
                    else:
                        verdict, detail = _classify(sig, a, b, seq_pairs, widths)
                    out.crossings.append(Crossing(
                        signal=sig, width=widths.get(sig, 1),
                        from_clock=a, to_clock=b, verdict=verdict,
                        detail=detail, module=name))
    return out


def _classify_combinational(sig: str, a: str, b: str, pairs,
                            widths) -> tuple[str, str]:
    """A signal whose value reaches clock b through combinational logic.

    It is classified like any other crossing — a combinational path into a real
    2-FF chain is a synchronised path, and Clause 4.3.10 recognises it as
    `glitch_free_combo`/`combo` — but the detail always says the path is
    combinational, because a reader of the report needs to know that the value was
    not settled by a flop in the source domain.
    """
    verdict, detail = _classify(sig, a, b, pairs, widths)
    path = (f"{sig} reaches {b} through combinational logic from {a}")
    if verdict.startswith("synchronised"):
        return verdict, f"{path}; {detail}"
    return "unsynchronised", f"{path} and {detail}"


def _classify(sig: str, a: str, b: str, pairs, widths) -> tuple[str, str]:
    """Is the crossing signal synchronised into clock b?

    The 2-FF pattern: `m <= sig` on clock b, and `s <= m` on clock b as well. If
    only one flop follows the crossing, a single event can still be metastable.
    """
    def reads(rhs, name: str) -> bool:
        """`rhs` is the set of names an assignment reads (older callers: a str)."""
        return rhs == name if isinstance(rhs, str) else name in rhs

    first = [lhs for (clk, lhs, rhs) in pairs if clk == b and reads(rhs, sig)]
    if not first:
        return ("unsynchronised",
                f"read on {b} with no flop in between")

    # Every reader of the crossing signal must be a chain start with its own
    # second flop. `y <= s_r` alongside a correct chain is a direct metastable
    # read, and the earlier version missed it because it treated `y` as a first
    # stage and then found a chain for the *other* reader.
    unprotected = [mid for mid in first
                   if not [lhs for (clk, lhs, rhs) in pairs
                           if clk == b and reads(rhs, mid)]]
    if unprotected:
        return ("unsynchronised",
                f"{sig} is read on {b} by {unprotected[0]} with no second flop "
                f"after it — a direct metastable read alongside the synchroniser")

    # (b) the metastable first stage must feed nothing but its second flop.
    #     `sync <= meta` is a chain flop; `y <= meta & en` is an escape — the
    #     chain looks right and the value that escapes it was never settled.
    for mid in first:
        escapes = sorted({lhs for (clk, lhs, rhs) in pairs
                          if clk == b and reads(rhs, mid)
                          and isinstance(rhs, frozenset) and len(rhs) > 1})
        if escapes:
            return ("unsynchronised",
                    f"the first synchroniser stage {mid} is also read by "
                    f"{escapes[0]} on {b} together with other signals — that path "
                    f"is metastable and unprotected")

    for mid in first:
        second = [lhs for (clk, lhs, rhs) in pairs if clk == b and reads(rhs, mid)]
        if second:
            w = widths.get(sig, 1)
            if w > 1:
                # A 2-FF per bit does not make a bus coherent: each bit settles on
                # its own edge, so the destination can latch a mix of old and new.
                # Reporting "synchronised" and then clean was the worst finding of
                # the CDC audit — the hazard lived only in prose while the
                # machine-readable verdict said safe.
                return ("synchronised_data_hazard",
                        f"{mid} -> {second[0]} on {b}, but {sig} is {w} bits: each "
                        f"bit settles independently, so the value read can mix old "
                        f"and new. A per-bit synchroniser is not a bus "
                        f"synchroniser; use a handshake, gray code or an async FIFO")
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
