"""Clock-domain-crossing detection.

A crossing is where a change is most likely to invalidate a result, so it is a
first-class node. This front-end finds the clock domains in a module, works out
which signals belong to each, and reports every signal that is read in one domain
but written in another — directly, or through combinational logic.

Where it cannot tell (a signal read in a clocked block whose domain is not defined
in the module), it says so and marks the module unresolved rather than assuming
the signal is safe. The kernel then refuses to call anything downstream VALID.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import EdgeKind, Node, NodeKind

_ALWAYS = re.compile(r"\balways(?:_ff|_comb|_latch)?\s*@\s*\(([^)]*)\)")
# `always_comb` / `always_latch` carry no sensitivity list
_ALWAYS_PLAIN = re.compile(r"\balways(?:_comb|_latch)\b(?!\s*@)")
_ASSIGN = re.compile(r"\bassign\s+(\w+)\s*=\s*([^;]+);")
_WRITE = re.compile(r"(\w+)\s*<=")
# a blocking assignment in a combinational block: `=` but not `==`, `<=`, `>=`
_WRITE_BLOCKING = re.compile(r"(\w+)\s*=(?!=)")
_IDENT = re.compile(r"[A-Za-z_]\w*")
_PARAM = re.compile(r"\b(?:parameter|localparam)\b[^=;]*?\b(\w+)\s*=")
_GENVAR = re.compile(r"\bgenvar\b\s+([\w,\s]+);")
_MEMORY = re.compile(r"\b(\w+)\s*\[[^\]]*\]\s*\[")
_ENUM_LITERAL = re.compile(r"^[A-Z][A-Z0-9_]*$")
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_COMMENT_LINE = re.compile(r"//[^\n]*")
# a sized literal (1'b1, 8'hFF, 4'd9) is a value, not a signal name
_SIZED_LITERAL = re.compile(r"\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_]+")


def _non_signals(text: str) -> set[str]:
    """Names that are not signals and must not be reported as domain-less.

    On real RTL a naive scan flags parameters, genvars, memory arrays and enum
    literals, which floods the unresolved list and makes every module look
    unresolved.
    """
    names: set[str] = set(_PARAM.findall(text))
    for group in _GENVAR.findall(text):
        names.update(n.strip() for n in group.split(","))
    names.update(_MEMORY.findall(text))
    return names

_KEYWORDS = {
    "begin", "end", "if", "else", "case", "casez", "casex", "endcase", "default",
    "always", "always_ff", "always_comb", "always_latch", "assign", "posedge",
    "negedge", "logic", "wire", "reg", "bit", "input", "output", "inout",
    "module", "endmodule", "parameter", "localparam", "generate", "endgenerate",
    "for", "while", "return", "signed", "unsigned", "int", "integer",
}


@dataclass
class Crossing:
    signal: str
    from_domain: str
    to_domain: str
    module: str
    kind: str = "direct"          # direct | through_combinational
    def as_dict(self) -> dict:
        return {"signal": self.signal, "from": self.from_domain, "to": self.to_domain,
                "module": self.module, "kind": self.kind}


@dataclass
class CdcReport:
    module: str
    domains: dict[str, list[str]] = field(default_factory=dict)
    crossings: list[Crossing] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"module": self.module, "domains": self.domains,
                "crossings": [c.as_dict() for c in self.crossings],
                "unresolved": self.unresolved}


def _block_body(text: str, start: int) -> str:
    """Text of the statement beginning at `start` (a begin/end block or one statement)."""
    rest = text[start:]
    stripped = rest.lstrip()
    if stripped.startswith("begin"):
        i = rest.index("begin")
        depth, j = 1, i + len("begin")
        while j < len(rest) and depth:
            word = _IDENT.match(rest, j)
            if word and word.group(0) in ("begin", "end"):
                depth += 1 if word.group(0) == "begin" else -1
                j = word.end()
                continue
            j += 1
        return rest[i:j]
    semi = rest.find(";")
    return rest[:semi + 1] if semi >= 0 else rest


def _clock_of(sens: str) -> str | None:
    for m in re.finditer(r"\b(posedge|negedge)\s+(\w+)", sens):
        return m.group(2)
    m = re.search(r"(\w+)", sens)
    return m.group(1) if m else None


def analyse(text: str, module: str) -> CdcReport:
    # Comments are prose: they contain ordinary words that look like signals, so
    # scanning them floods the unresolved list. Strip them first.
    text = _COMMENT_BLOCK.sub(" ", text)
    text = _COMMENT_LINE.sub(" ", text)
    text = _SIZED_LITERAL.sub(" ", text)
    report = CdcReport(module=module)
    not_signals = _non_signals(text)

    written_by: dict[str, set[str]] = {}          # clock -> written signals
    read_by: dict[str, set[str]] = {}             # clock -> read signals
    comb: dict[str, set[str]] = {}                # combinational target -> its reads
    for m in _ALWAYS.finditer(text):
        clock = _clock_of(m.group(1))
        body = _block_body(text, m.end())
        idents = {i for i in _IDENT.findall(body)
                  if i not in _KEYWORDS and i not in not_signals}
        if clock is None:
            # a combinational block: its targets are not clocked, but their value
            # still comes from somewhere — record it so a signal driven here is
            # not mistaken for one with no determinable domain
            for target in set(_WRITE_BLOCKING.findall(body)) | set(_WRITE.findall(body)):
                comb[target] = idents - {target}
            continue
        written = set(_WRITE.findall(body))
        written_by.setdefault(clock, set()).update(written)
        read_by.setdefault(clock, set()).update(idents - written - {clock})

    for m in _ALWAYS_PLAIN.finditer(text):
        body = _block_body(text, m.end())
        idents = {i for i in _IDENT.findall(body)
                  if i not in _KEYWORDS and i not in not_signals}
        for target in set(_WRITE_BLOCKING.findall(body)) | set(_WRITE.findall(body)):
            comb[target] = idents - {target}
    for m in _ASSIGN.finditer(text):
        target = m.group(1)
        reads = {i for i in _IDENT.findall(m.group(2)) if i not in _KEYWORDS}
        comb[target] = reads

    report.domains = {c: sorted(v) for c, v in sorted(written_by.items())}

    # resolve which domains a signal's value comes from (fixpoint over comb logic)
    def domains_of(name: str, seen: set[str] | None = None) -> set[str]:
        seen = seen or set()
        if name in seen:
            return set()
        seen.add(name)
        out = {c for c, sigs in written_by.items() if name in sigs}
        if name in comb:
            for r in comb[name]:
                out |= domains_of(r, seen)
        return out

    unresolved: set[str] = set()
    for clock, reads in read_by.items():
        for sig in sorted(reads):
            if sig in not_signals or _ENUM_LITERAL.match(sig):
                continue
            src = domains_of(sig)
            if not src:
                unresolved.add(sig)               # cannot tell where it comes from
                continue
            if clock in src:
                continue
            kind = "through_combinational" if sig in comb else "direct"
            for other in sorted(src):
                report.crossings.append(Crossing(sig, other, clock, module, kind))
    report.unresolved = sorted(unresolved)
    return report


def add_cdc_to_graph(graph, report: CdcReport) -> CdcReport:
    """Add CDC nodes and CROSSES edges; mark the module unresolved where it cannot tell."""
    for c in report.crossings:
        cid = f"cdc.{report.module}.{c.signal}"
        graph.add_node(Node(id=cid, kind=NodeKind.CDC,
                            meta={"from": c.from_domain, "to": c.to_domain,
                                  "kind": c.kind}))
        for clk in (c.from_domain, c.to_domain):
            graph.add_node(Node(id=clk, kind=NodeKind.CLOCK))
            graph.add_edge(clk, cid, EdgeKind.CROSSES)
        if c.signal in graph.nodes:
            graph.add_edge(c.signal, cid, EdgeKind.CROSSES)
    for sig in report.unresolved:
        if report.module in graph.nodes:
            graph.mark_unresolved(
                report.module, f"cdc: clock domain of `{sig}` could not be determined")
    return report


def add_crossing(graph, name: str, from_clk: str, to_clk: str, signals: list[str]) -> None:
    """Manual helper (kept for callers that know the crossing already)."""
    cid = f"cdc.{name}"
    graph.add_node(Node(id=cid, kind=NodeKind.CDC, meta={"from": from_clk, "to": to_clk}))
    graph.add_edge(from_clk, cid, EdgeKind.CROSSES)
    graph.add_edge(to_clk, cid, EdgeKind.CROSSES)
    for s in signals:
        graph.add_edge(s, cid, EdgeKind.CROSSES)
