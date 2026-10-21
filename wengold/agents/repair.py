"""Repairer: proposes the smallest change that would fix a failure.

It proposes; it does not decide. Every proposal carries a confidence and a
rationale, and a concrete `find`/`replace` only when the failure gives it enough
to name the edit. A proposal is never trusted until the tools re-verify it — the
orchestrator re-runs the check after a repair, and the kernel decides.
"""
from __future__ import annotations

import re

_UNDECL_QUOTED = re.compile(
    r"(?:undeclared|not declared|unknown identifier|not found)[^\n]*?[`'\"]([A-Za-z_]\w*)[`'\"]",
    re.IGNORECASE)
_UNDECL_PLAIN = re.compile(
    r"(?:undeclared|not declared)\s+(?:identifier\s+)?([A-Za-z_]\w*)", re.IGNORECASE)
_MISSING_INC = re.compile(r"unresolved include\s*`?\"?([\w./\-]+)\"?`?")
_INVERT = re.compile(r"([\w.]+)\s*=\s*(~?)\s*([\w\[\]:]+)")


class Repairer:
    def __init__(self, llm=None) -> None:
        self.llm = llm

    def propose(self, failure: dict) -> dict:
        category = failure.get("category", "unknown")
        log = failure.get("log", "") or failure.get("evidence", "")
        if isinstance(log, list):
            log = " ".join(str(x) for x in log)
        file = failure.get("file")
        line = failure.get("line")

        if category == "tool_missing":
            return self._proposal("tool_missing", file, line, None, None, 0.9,
                                  "install the missing tool; no design change is warranted")

        if category == "elaboration_error":
            m = _MISSING_INC.search(log)
            if m:
                return self._proposal("add_include", file, line, None, None, 0.6,
                                      f"include `{m.group(1)}` could not be found; add its "
                                      f"directory to the search path or add the file")
            m = _UNDECL_QUOTED.search(log) or _UNDECL_PLAIN.search(log)
            if m:
                return self._proposal("declare_signal", file, line, None,
                                      f"logic {m.group(1)};", 0.5,
                                      f"`{m.group(1)}` is used before it is declared")

        if category in ("assertion_failure", "mismatch", "formal_counterexample"):
            m = _INVERT.search(log)
            if m:
                find = m.group(0)
                replace = f"{m.group(1)} = {'~' if not m.group(2) else ''}{m.group(3)}"
                return self._proposal("invert_condition", file, line, find, replace, 0.35,
                                      "the condition may be inverted; verify against the spec "
                                      "before applying")

        return self._proposal("inspect", file, line, None, None, 0.1,
                              "not enough evidence for a concrete edit; inspect the evidence")

    @staticmethod
    def _proposal(kind: str, file, line, find, replace, confidence, rationale) -> dict:
        return {
            "kind": kind,
            "file": file,
            "line": line,
            "find": find,
            "replace": replace,
            "confidence": confidence,
            "rationale": rationale,
            "applied": False,
        }

    def apply(self, text: str, proposal: dict) -> str:
        """Apply a literal find/replace proposal to source text (in memory only)."""
        find, replace = proposal.get("find"), proposal.get("replace")
        if not find or replace is None or find not in text:
            return text
        proposal["applied"] = True
        return text.replace(find, replace, 1)
