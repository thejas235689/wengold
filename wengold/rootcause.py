"""Root-cause analysis: why is this unknown, unresolved, or invalidated?

WENGOLD already refuses to guess — an unresolved node makes everything downstream
UNKNOWN rather than VALID. That is the safe half. This is the useful half: when
something cannot be established, say *what* is in the way and *why*, precisely
enough to act on.

Three questions are answered here:

* **Why is this node unresolved?** — the instantiation or parse error at fault,
  the file and the line, and whether the missing module is provided by a
  dependency the project declares (so the answer is "vendor this") or is absent
  from the project entirely.
* **Why is this result invalidated?** — which of the changes actually reach it,
  ranked, with the dependency path that carries the effect, and an explicit
  statement when *no* change reaches it (the change cannot explain the failure).
* **Why is this result unknown?** — the unresolved nodes inside its dependency
  closure, i.e. the modelling gaps standing between the kernel and an answer.

Nothing here reports a cause it cannot support. Every cause carries a certainty
of `proven`, `probable` or `unknown`, and the analyzer says so when the evidence
does not single out one cause.
"""
from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .graph.model import EdgeKind

__all__ = ["Cause", "Diagnosis", "Culprit", "diagnose_node", "localize",
           "diagnose_verdict"]

# project files that name external dependencies
_MANIFESTS = ("Bender.yml", "*.core", "*.flist", "*.f", "*.vendor.hjson",
              "*.lock.hjson", "src_files.yml", "dependencies.json")


@dataclass
class Cause:
    kind: str
    subject: str
    detail: str
    file: str | None = None
    line: int | None = None
    construct: str | None = None
    action: str | None = None
    certainty: str = "proven"

    def render(self, indent: str = "  ") -> str:
        where = ""
        if self.file:
            where = f" at {self.file}" + (f":{self.line}" if self.line else "")
        out = [f"{indent}{self.kind}: {self.detail}{where}"]
        if self.construct:
            out.append(f"{indent}    construct: {self.construct}")
        if self.action:
            out.append(f"{indent}    action:    {self.action}")
        out.append(f"{indent}    certainty: {self.certainty}")
        return "\n".join(out)


@dataclass
class Culprit:
    node: str
    distance: int
    path: list[str]
    unresolved: bool
    evidence: list[str] = field(default_factory=list)

    def render(self, indent: str = "  ") -> str:
        chain = " -> ".join(self.path)
        out = [f"{indent}{self.node}  (distance {self.distance})",
               f"{indent}    path: {chain}"]
        for e in self.evidence:
            out.append(f"{indent}    {e}")
        return "\n".join(out)


@dataclass
class Diagnosis:
    subject: str
    status: str
    causes: list[Cause] = field(default_factory=list)
    culprits: list[Culprit] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.causes or self.culprits)

    def render(self) -> str:
        lines = [f"{self.subject}: {self.status}"]
        for c in self.causes:
            lines.append(c.render())
        for i, cu in enumerate(self.culprits, 1):
            lines.append(f"  cause {i}:")
            lines.append(cu.render("    "))
        for n in self.notes:
            lines.append(f"  note: {n}")
        return "\n".join(lines)


# ---- helpers ---------------------------------------------------------------
def _find_line(root: Path | None, file: str | None, subject: str) -> int | None:
    """The line in the ORIGINAL file where `subject` is instantiated."""
    if root is None or not file:
        return None
    p = Path(root) / file
    if not p.is_file():
        p = Path(file)
    if not p.is_file():
        return None
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return None
    pattern = re.compile(rf"\b{re.escape(subject)}\b\s*(#\s*\(|[A-Za-z_]\w*\s*\()")
    for i, line in enumerate(text.splitlines(), 1):
        if pattern.search(line) and not line.strip().startswith("//"):
            return i
    return None


def _find_dependency(root: Path | None, subject: str) -> tuple[str, str] | None:
    """Which declared dependency mentions `subject`? Returns (file, line)."""
    if root is None:
        return None
    root = Path(root)
    for pattern in _MANIFESTS:
        for path in list(root.glob(pattern)) + list(root.glob(f"*/{pattern}")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if re.search(rf"\b{re.escape(subject)}\b", line):
                    return str(path.relative_to(root)), i
    return None


def _vendored_dirs(root: Path | None) -> list[str]:
    if root is None:
        return []
    root = Path(root)
    out = []
    for pat in ("vendor", "*/vendor", "*/vendor/*", "third_party", "deps"):
        for d in root.glob(pat):
            if d.is_dir():
                out.append(str(d.relative_to(root)))
    return sorted(set(out))


def _declared_deps(root: Path | None) -> list[str]:
    """Dependency names the project declares (Bender.yml / Bender.lock)."""
    if root is None:
        return []
    root = Path(root)
    for name in ("Bender.yml", "Bender.yaml", "Bender.lock"):
        p = root / name
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        deps, in_deps = [], False
        for line in text.splitlines():
            if re.match(r"^dependencies:\s*$", line):
                in_deps = True
                continue
            if in_deps:
                if re.match(r"^\S", line):        # a new top-level key ends it
                    in_deps = False
                    continue
                m = re.match(r"^\s+([A-Za-z_][\w-]*):", line)
                if m:
                    deps.append(m.group(1))
        if deps:
            return sorted(set(deps))
    return []


def _unvendored_deps(root: Path | None) -> list[str]:
    """Declared dependencies with no directory under a vendor tree."""
    vendored = " ".join(_vendored_dirs(root)).lower()
    return [d for d in _declared_deps(root) if d.lower() not in vendored]


def _closure(graph, deps) -> set[str]:
    out = set(deps)
    for d in deps:
        out |= graph.ancestors(d)
    return out


def _direct_consumers(graph, node: str) -> list[str]:
    """The modules that instantiate `node` directly.

    Not `descendants`, which is the transitive set — walking that reports a
    two-hop path as one hop and hides the stage the signal actually passes
    through.
    """
    return [e.dst for e in graph.out_edges(node)
            if e.kind is EdgeKind.INSTANTIATES]


def _path_between(graph, src: str, dst: str) -> list[str] | None:
    """The shortest dependency path carrying an effect from `src` to `dst`."""
    if src == dst:
        return [src]
    seen = {src}
    q = deque([[src]])
    while q:
        path = q.popleft()
        for nxt in _direct_consumers(graph, path[-1]):
            if nxt in seen:
                continue
            if nxt == dst:
                return path + [nxt]
            seen.add(nxt)
            q.append(path + [nxt])
    return None


# ---- 1. why is this node unresolved ---------------------------------------
def diagnose_node(graph, node: str, root: str | Path | None = None) -> Diagnosis:
    """Explain a node's status: resolved, or unresolved and why."""
    root = Path(root) if root is not None else None
    if node not in graph.nodes:
        return Diagnosis(node, "not in the graph",
                         notes=["the node is neither defined nor referenced here"])
    n = graph.nodes[node]
    reasons = list(n.meta.get("unresolved", []))
    if not reasons:
        deps = sorted(graph.ancestors(node))
        users = sorted(graph.descendants(node))
        return Diagnosis(
            node, "resolved",
            notes=[f"depends on {len(deps)} node(s)"
                   + (f": {', '.join(deps[:6])}" if deps else ""),
                   f"used by {len(users)} node(s)"
                   + (f": {', '.join(users[:6])}" if users else "")])

    diag = Diagnosis(node, "unresolved")
    for r in reasons:
        kind = r.get("kind") or "unresolved"
        subject = r.get("subject") or ""
        file = r.get("file")
        if kind == "missing_definition":
            line = _find_line(root, file, subject)
            dep = _find_dependency(root, subject)
            action, certainty = None, "proven"
            detail = (f"instantiates `{subject}`, which no file in the file set "
                      f"defines")
            if dep is not None:
                dep_file, dep_line = dep
                detail += (f"; it is named by {dep_file}:{dep_line}, so it comes "
                           f"from an external dependency")
                action = f"add the sources of {dep_file} to the file set"
            else:
                missing = _unvendored_deps(root)
                if missing:
                    detail += (
                        f"; the project declares {len(missing)} dependency(ies) it "
                        f"does not vendor here ({', '.join(missing)}), and this "
                        f"module is not in the vendored tree")
                    action = (f"likely provided by {', '.join(missing)} — vendor it "
                              f"(e.g. `bender checkout`) or add its src directory "
                              f"to the file set")
                    certainty = "probable"
                else:
                    action = ("vendor it, add its directory to the file set, or "
                              "confirm the module was renamed")
                    certainty = "probable"
            diag.causes.append(Cause(
                kind="missing definition", subject=subject, detail=detail,
                file=file, line=line, construct=r.get("construct"),
                action=action, certainty=certainty))
        elif kind == "parse_error":
            diag.causes.append(Cause(
                kind="parse error", subject=node,
                detail="the file did not parse cleanly, so its instantiations "
                       "cannot be trusted",
                file=file, construct=r.get("construct"),
                action="fix the parse error (or the construct the front-end "
                       "refused) and re-index", certainty="proven"))
        else:
            diag.causes.append(Cause(kind=kind, subject=subject or node,
                                     detail=r.get("reason", ""), file=file,
                                     construct=r.get("construct"),
                                     certainty="probable"))
    return diag


# ---- 2. why is this result invalidated ------------------------------------
def localize(graph, depends_on, changed, result_id: str = "result") -> Diagnosis:
    """Rank the changes that actually reach a result.

    A change can only explain a failure if it lies in the result's dependency
    closure. When none does, that is the finding — and it is reported as such
    rather than as a low-confidence guess.
    """
    changed = set(changed)
    closure = _closure(graph, set(depends_on))
    unknown = sorted(c for c in changed if c not in graph.nodes)
    reaching = sorted(changed & closure)
    diag = Diagnosis(result_id, "invalidated" if reaching else "not explained")
    if unknown:
        diag.notes.append(f"not in the graph, so nothing can be said about it: "
                          f"{', '.join(unknown)}")
    if not reaching:
        outside = sorted((changed - closure) - set(unknown))
        if outside:
            diag.notes.append(
                f"no change reaches this result: {', '.join(outside)} is not in "
                f"its dependency closure ({len(closure)} node(s))")
        elif not unknown:
            diag.notes.append("no change reaches this result: no changes given")
        return diag
    for node in reaching:
        best: list[str] | None = None
        for target in sorted(depends_on):
            path = _path_between(graph, node, target)
            if path and (best is None or len(path) < len(best)):
                best = path
        unresolved = node in graph.unresolved_nodes()
        ev = []
        if unresolved:
            ev.append("this node is itself unresolved — a modelling gap, not "
                      "necessarily a defect")
        ev.append("change lies on a dependency path into the result"
                  if best else "change is in the dependency closure")
        diag.culprits.append(Culprit(node, max(len(best or []) - 1, 0),
                                     best or [node], unresolved, ev))
    diag.culprits.sort(key=lambda c: (c.unresolved, c.distance))
    return diag


# ---- 3. why is this result unknown ----------------------------------------
def diagnose_verdict(graph, result_id: str, depends_on, changed=()) -> Diagnosis:
    """Explain a kernel verdict from the graph alone."""
    deps = set(depends_on)
    changed = set(changed)
    if not deps:
        return Diagnosis(result_id, "unknown",
                         notes=["the result declares no dependency, so nothing "
                                "can be established about it"])
    closure = _closure(graph, deps)
    gaps = sorted(closure & graph.unresolved_nodes())
    reaching = sorted(changed & closure)
    if gaps:
        diag = Diagnosis(result_id, "unknown",
                         notes=[f"{len(gaps)} unresolved node(s) in its "
                                f"dependency closure: {', '.join(gaps[:6])}"])
        for g in gaps[:3]:
            diag.causes.append(Cause(
                kind="modelling gap", subject=g,
                detail="unresolved, so every result downstream of it is unknown",
                certainty="proven"))
        return diag
    if changed:
        # route through localize so a change that does not reach the result, or a
        # name that is not in the graph, is reported rather than dropped
        return localize(graph, deps, changed, result_id)
    return Diagnosis(result_id, "valid",
                     notes=[f"{len(closure)} node(s) in its closure, all resolved, "
                            f"and no change reaches it"])
