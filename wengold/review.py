"""Suggest better code — from checks that actually ran.

"Suggest better code" is a phrase that usually means a model with opinions. This
module means something narrower and more useful: **every suggestion is a diff whose
justification is a check that ran and a result it produced.** If nothing ran, there
is no suggestion.

Three sources, in the order of how much they can be trusted:

| suggestion | what justifies it |
| --- | --- |
| add a 2-FF synchroniser to a crossing | the CDC analysis classified it `unsynchronised` |
| reset a flop that is X after reset | the simulation reported `output X is X after reset` |
| drop or wire a field nothing writes | the conformance check reported it holds its reset value forever |

The middle one is the strongest, because it is the only one proved by execution
rather than by reading syntax: the simulator said the signal was X, so a flop is
not reset, and the diff adds it to the reset branch.

**What this will not do.** It will not rewrite your logic, choose an architecture,
or improve anything it cannot point at a failing check for. A suggestion you cannot
verify is a suggestion you have to trust, and this tool exists so you do not have to.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Suggestion", "review", "render"]


@dataclass
class Suggestion:
    id: str
    title: str
    why: str                  # the check that ran and what it said
    path: str
    diff: str
    severity: str = "warning"  # "error" | "warning" | "note"
    new_text: str = ""

    def render(self) -> str:
        lines = [f"  [{self.severity}] {self.title}",
                 f"    why: {self.why}",
                 f"    file: {self.path}"]
        body = [l for l in self.diff.splitlines() if l[:1] in "+-" and l[:3] not in
                ("+++", "---")]
        for l in body[:20]:
            lines.append(f"      {l}")
        if len(body) > 20:
            lines.append(f"      … {len(body) - 20} more line(s)")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "why": self.why,
                "path": self.path, "severity": self.severity}


def _diff(path: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}"))


# ---- source 1: a flop that is X after reset -----------------------------
# Two shapes, and missing the second one is a false positive — the worst kind of
# error here, because it tells you to "fix" code that is already correct:
#   if (!rst_n) begin ... end        (block)
#   if (!rst_n) q <= 1'b0;           (single statement, no begin)
_RESET_BLOCK = re.compile(
    r"(if\s*\(\s*!?\w*rst\w*\s*(?:==\s*1'?b?0\s*)?\)\s*begin)(.*?)(end)",
    re.S)
_RESET_STMT = re.compile(
    r"(if\s*\(\s*!?\w*rst\w*\s*(?:==\s*1'?b?0\s*)?\)\s*)([^;]*;)")


def _reset_body(body: str) -> str:
    """The assignments inside a reset branch, block or single-statement."""
    m = _RESET_BLOCK.search(body)
    if m:
        return m.group(2)
    m = _RESET_STMT.search(body)
    return m.group(2) if m else ""


def _clocked_blocks(text: str) -> list[str]:
    """The body of each `always_ff @(...) begin ... end`, matched by nesting.

    A non-greedy regex to the first `end` stops inside the reset branch — which is
    exactly the part we need to see past, so it found no flops at all.
    """
    blocks = []
    for m in re.finditer(r"always_ff\s*@\s*\([^)]*\)\s*begin", text):
        i = m.end()
        depth = 1
        while i < len(text) and depth:
            for word in re.finditer(r"\b(begin|end)\b", text[i:]):
                if word.group(1) == "begin":
                    depth += 1
                else:
                    depth -= 1
                if depth == 0:
                    blocks.append(text[m.end():i + word.start()])
                    i = len(text)
                    break
                i += word.end()
            else:
                break
    return blocks


def _unreset_flops(text: str) -> list[tuple[str, str]]:
    """Flops assigned in a clocked block but absent from its reset branch.

    Reads the shape the generator emits and the shape most hand-written RTL uses:
    one `always_ff`, a reset branch at the top, non-blocking assignments.
    """
    out = []
    for body in _clocked_blocks(text):
        reset_lhs = set(re.findall(r"(\w+)\s*<=", _reset_body(body)))
        all_lhs = set(re.findall(r"(\w+)\s*<=", body))
        for sig in sorted(all_lhs - reset_lhs):
            out.append((sig, body))
    return out


def _suggest_reset(text: str, path: str, signals: list[str]) -> list[Suggestion]:
    """Add the missing signals to the reset branch, with their reset value."""
    m = _RESET_BLOCK.search(text)
    if not m:
        return []           # a single-statement reset cannot take an insertion
    header, body, tail = m.group(1), m.group(2), m.group(3)

    # width from any declaration or port, `[3:0] q` with or without a trailing ';'
    width_of = {}
    for d in re.finditer(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*(\w+)", text):
        hi, lo, name = int(d.group(1)), int(d.group(2)), d.group(3)
        width_of[name] = abs(hi - lo) + 1

    added = []
    for sig in signals:
        w = width_of.get(sig, 1)
        val = "1'b0" if w == 1 else f"{w}'d0"
        added.append(f"{sig} <= {val};")
    if not added:
        return []

    # keep whatever whitespace sat between the last statement and `end`, so the
    # closing keyword stays on its own line — dropping it produced a diff that
    # pasted the assignment onto the `end` line and would not compile
    trailing = body[len(body.rstrip()):] or "\n    "
    indent = " " * 8
    extra = "".join(f"\n{indent}{a}" for a in added)
    new_body = body.rstrip() + extra + trailing
    new = text[:m.start()] + header + new_body + tail + text[m.end():]
    return [Suggestion(
        id=f"reset-{signals[0]}", path=path,
        title=f"reset {', '.join(signals)} in the reset branch",
        why=("the simulation reported this signal as X after reset, so its flop "
             "is not reset. An unreset flop holds X until it happens to be written, "
             "and X propagates into anything it feeds."),
        severity="error", diff=_diff(path, text, new), new_text=new)]


# ---- source 2: an unsynchronised crossing -------------------------------
def _suggest_sync(text: str, path: str, crossing) -> list[Suggestion]:
    sig, dst = crossing.signal, crossing.to_clock
    width = getattr(crossing, "width", 1)
    if width > 1:
        return [Suggestion(
            id=f"cdc-{sig}", path=path, severity="error",
            title=f"do not send {sig} ({width} bits) through 2-FF flops",
            why=("the CDC analysis found a multi-bit crossing from "
                 f"{crossing.from_clock} to {dst}. A 2-FF synchroniser settles each "
                 "bit independently, so the value read can mix old and new. Use a "
                 "gray-coded pointer, a handshake, or an async FIFO."),
            diff="")]

    q1, q2 = f"{sig}_meta", f"{sig}_sync"
    decl = (f"  logic {q1}, {q2};   // {sig} synchronised into {dst}\n")
    flops = (f"  always_ff @(posedge {dst}) begin\n"
             f"    {q1} <= {sig};\n"
             f"    {q2} <= {q1};\n"
             f"  end\n\n")
    # insert the declarations before the first always_ff, the flops just after it
    m = re.search(r"\n(\s*)always_ff", text)
    if not m:
        return []
    new = text[:m.start()] + "\n" + decl + flops + text[m.start():]
    return [Suggestion(
        id=f"cdc-{sig}", path=path, severity="error",
        title=f"synchronise {sig} into {dst}",
        why=(f"the CDC analysis classified the {crossing.from_clock} -> {dst} "
             f"crossing of {sig} as unsynchronised: it reaches the destination with "
             f"no second flop, so a transition can be sampled while metastable."),
        diff=_diff(path, text, new), new_text=new)]


# ---- the entry point ----------------------------------------------------
def review(root: str, tools: str | None = None, max_files: int = 40) -> dict:
    """Run the checks that can justify a suggestion, and return them."""
    rootp = Path(root)
    out: dict = {"root": str(rootp), "suggestions": [], "ran": [], "skipped": []}

    files = []
    for ext in ("*.sv", "*.v", "*.vhd"):
        files.extend(sorted(rootp.rglob(ext)))
    files = [f for f in files if "vibe-out" not in str(f)][:max_files]
    if not files:
        out["skipped"].append("no HDL files to review")
        return out

    # ---- CDC: a check that reads syntax
    try:
        from .cdc_analysis import analyse_text, classify
        from .graph.cdc import analyse as detect
        out["ran"].append("cdc")
        for f in files:
            if f.suffix.lower() not in (".sv", ".v"):
                continue
            src = f.read_text(errors="replace")
            rel = str(f.relative_to(rootp))
            a = analyse_text(src, rel)
            # the detector labels crossings with the module name it is given; the
            # analysis keys by the name in the source. Passing the file stem made
            # every lookup miss, so widths fell back to 1 bit.
            label = a.modules[0] if a.modules else f.stem
            rep = detect(src, label)
            for c in classify(rep, a):
                if c.verdict == "unsynchronised":
                    out["suggestions"] += _suggest_sync(src, rel, c)
    except Exception as exc:                              # never fail the review
        out["skipped"].append(f"cdc: {exc}")

    # ---- simulation: the strongest evidence, because it ran
    try:
        from .agent.runners import ToolRunner, Toolchain
        from .graph.builder import GraphBuilder
        from .kernel.validity import Result
        from .cli import _collect

        g = GraphBuilder().build_from_files(_collect(str(rootp)), backend="auto")
        blocks = sorted(n for n, d in g.nodes.items()
                        if getattr(d, "kind", None) is not None
                        and not n.startswith(("file:", "param.")))
        if blocks:
            res = {f"{b}_sim": Result(f"{b}_sim", "sim", depends_on={b})
                   for b in blocks}
            tr = ToolRunner(g, res, str(rootp), toolchain=Toolchain(tools))
            rec = tr(f"{blocks[0]}_sim", "sim")
            out["sim"] = {"outcome": rec["outcome"], "note": rec["note"]}
            if rec["outcome"] in ("pass", "fail"):
                out["ran"].append("simulation")
            xs = re.findall(r"output (\w+) is X after reset", rec.get("log", ""))
            if xs:
                for f in files:
                    if f.suffix.lower() not in (".sv", ".v"):
                        continue
                    src = f.read_text(errors="replace")
                    rel = str(f.relative_to(rootp))
                    missing = [s for s, _ in _unreset_flops(src)]
                    if not missing:
                        continue
                    out["suggestions"] += _suggest_reset(src, rel, missing[:6])
                    break
    except Exception as exc:
        out["skipped"].append(f"simulation: {exc}")

    return out


def render(rep: dict) -> str:
    lines = []
    if rep.get("ran"):
        lines.append(f"  checks that ran: {', '.join(rep['ran'])}")
    for s in rep.get("skipped", []):
        lines.append(f"  ! skipped {s}")
    sug = rep.get("suggestions", [])
    if not sug:
        lines.append("  no suggestions — no check produced a failing result")
        lines.append("  (that is not the same as 'the code is good')")
        return "\n".join(lines)
    lines.append("")
    for s in sug:
        lines.append(s.render() if isinstance(s, Suggestion) else str(s))
        lines.append("")
    lines.append(f"  {len(sug)} suggestion(s). Nothing is applied: read the diff,")
    lines.append("  then apply it yourself or with `wengold review --apply <id>`.")
    return "\n".join(lines).rstrip()
