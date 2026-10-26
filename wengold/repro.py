"""Failure reproduction: capture what determined a result, replay it, verify.

A verification result is only useful if it can be re-created. This module records
the smallest set of facts that determines a result's outcome, and replays them.

What a bundle pins:

| field | why it is needed |
| --- | --- |
| `files` | a per-file content hash of the design file set — if the RTL moved, the result is about different code |
| `result_id` / `kind` | which check produced the result |
| `status` | what it concluded (pass / fail) |
| `verdict` | the kernel's currency at capture time |
| `tool` / `tool_version` | a different simulator is a different experiment |
| `detail` | the human-readable reason, so a replay can be compared not just on status |

**The honesty constraint.** A reproducer that reproduces everything reproduces
nothing. `replay` therefore refuses to report success when the file set has
drifted: it reports exactly which files changed, appeared or vanished, and
returns `reproduced=False`. Silently re-running against different RTL and
reporting "still fails" is the single most damaging bug a tool like this can
have, and it is the one this module is built to avoid.

Note on scope: WENGOLD does not run simulators itself. It records what a tool
reported. So a replay here re-establishes the *inputs* and re-checks the recorded
outcome against the current tree — it does not re-invoke VCS or Verilator. That
would be a larger change and is not claimed here.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Bundle", "ReplayReport", "capture", "save", "load", "replay",
           "file_hashes", "drift"]


def _sha(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except OSError:
        return "unreadable"


def file_hashes(root: str | Path, rel_paths=None) -> dict[str, str]:
    """Content hash per file. `rel_paths` limits it to a known file set."""
    root = Path(root)
    out: dict[str, str] = {}
    if rel_paths is not None:
        for rel in sorted(rel_paths):
            p = root / rel
            out[rel] = _sha(str(p)) if p.exists() else "missing"
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".v", ".sv", ".vhd", ".vhdl",
                                                ".vh", ".svh"):
            out[str(p.relative_to(root))] = _sha(str(p))
    return out


@dataclass
class Bundle:
    """Everything that determined one result."""

    result_id: str
    kind: str
    status: str
    design: str
    files: dict[str, str] = field(default_factory=dict)
    verdict: str = ""
    tool: str = ""
    tool_version: str = ""
    detail: str = ""
    notes: list = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "wengold_repro": 1,
            "result_id": self.result_id,
            "kind": self.kind,
            "status": self.status,
            "design": self.design,
            "files": self.files,
            "verdict": self.verdict,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "detail": self.detail,
            "notes": self.notes,
        }, indent=1, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Bundle":
        d = json.loads(text)
        if d.get("wengold_repro") != 1:
            raise ValueError("not a WENGOLD repro bundle (missing wengold_repro: 1)")
        return cls(
            result_id=d["result_id"], kind=d["kind"], status=d["status"],
            design=d["design"], files=d.get("files", {}), verdict=d.get("verdict", ""),
            tool=d.get("tool", ""), tool_version=d.get("tool_version", ""),
            detail=d.get("detail", ""), notes=d.get("notes", []))


def capture(root: str | Path, result, verdict="", detail: str = "",
            tool: str = "", tool_version: str = "",
            rel_paths=None) -> Bundle:
    """Record everything that determined `result` on the tree at `root`."""
    files = file_hashes(root, rel_paths)
    return Bundle(
        result_id=result.id, kind=result.kind, status=getattr(result, "status", ""),
        design=str(root), files=files,
        verdict=str(getattr(verdict, "value", verdict)),
        tool=tool, tool_version=tool_version, detail=detail)


def save(bundle: Bundle, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(bundle.to_json())
    return p


def load(path: str | Path) -> Bundle:
    return Bundle.from_json(Path(path).read_text())


def drift(bundle: Bundle, root: str | Path) -> dict[str, list[str]]:
    """Which files changed, appeared or vanished since capture.

    This is the check that stops a replay from claiming a reproduction it did not
    achieve. Three separate categories, because they mean different things:
    a *changed* file means the result is about different code; a *missing* file
    means the design no longer elaborates as it did; an *added* file may introduce
    new definitions that shadow old ones.
    """
    now = file_hashes(root, bundle.files.keys())
    changed, missing = [], []
    for rel, was in bundle.files.items():
        cur = now.get(rel, "missing")
        if cur == "missing":
            missing.append(rel)
        elif cur != was:
            changed.append(rel)
    known = set(bundle.files)
    added = sorted(r for r in file_hashes(root) if r not in known)
    return {"changed": sorted(changed), "missing": sorted(missing), "added": added}


@dataclass
class ReplayReport:
    bundle: Bundle
    reproduced: bool
    drift: dict[str, list[str]]
    notes: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not any(self.drift.values())

    def render(self) -> str:
        lines = [f"  result   {self.bundle.result_id} ({self.bundle.kind})",
                 f"  status   {self.bundle.status}   verdict {self.bundle.verdict or '-'}"]
        if self.bundle.tool:
            lines.append(f"  tool     {self.bundle.tool} {self.bundle.tool_version}".rstrip())
        if self.bundle.detail:
            lines.append(f"  detail   {self.bundle.detail}")
        lines.append(f"  files    {len(self.bundle.files)} pinned")
        if self.clean:
            lines.append("  drift    none — the file set is identical to capture")
        else:
            for cat in ("changed", "missing", "added"):
                if self.drift[cat]:
                    lines.append(f"  drift    {cat}: {', '.join(self.drift[cat][:5])}"
                                 + (" ..." if len(self.drift[cat]) > 5 else ""))
        verdict = ("REPRODUCED" if self.reproduced else
                   "NOT REPRODUCED — the inputs differ from the capture")
        lines.append(f"  => {verdict}")
        for n in self.notes:
            lines.append(f"     {n}")
        return "\n".join(lines)


def replay(bundle: Bundle, root: str | Path) -> ReplayReport:
    """Check the bundle still describes the tree at `root`.

    Returns `reproduced=True` only when the file set is byte-identical to the
    capture. Any drift is reported with the specific files and `reproduced` is
    False — a replay against different RTL is a different experiment, and saying
    otherwise is the worst failure mode this tool could have.
    """
    d = drift(bundle, root)
    notes = []
    if d["changed"]:
        notes.append(f"{len(d['changed'])} file(s) changed since capture: the result "
                     f"is about different code")
    if d["missing"]:
        notes.append(f"{len(d['missing'])} file(s) gone: the design no longer "
                     f"elaborates as it did")
    if d["added"]:
        notes.append(f"{len(d['added'])} file(s) added: a new definition may shadow "
                     f"an old one")
    return ReplayReport(bundle=bundle, reproduced=not any(d.values()), drift=d,
                        notes=notes)
