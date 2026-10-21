"""Debugger: turns a raw tool outcome into a root cause.

It reads the tool's own log — never a waveform by eye — and classifies the
failure, pulling out the file and line where it can. The output is deliberately
modest: a category, the evidence it used, and a hint for the next action. It
does not claim to know the fix.
"""
from __future__ import annotations

import re

from ..tools.outcome import Outcome

_LOC = re.compile(r"([\w./\-]+\.(?:sv|svh|v|vh|py|cpp|sdc|f|rdl)):(\d+)")
_ERROR = re.compile(r"^\s*(?:%?Error|ERROR|error:|\*\* Error|Fatal)[^\n]*", re.MULTILINE)
_MISMATCH = re.compile(r"\b(mismatch|expected .* got|does not match|!==)\b", re.IGNORECASE)
_ASSERT = re.compile(r"\b(assert(?:ion)?\s+failed|AssertionError|SVA|property .* failed)\b",
                     re.IGNORECASE)
_CEX = re.compile(r"\b(counterexample|BMC failed|assert failed in|FAIL)\b", re.IGNORECASE)


class Debugger:
    def __init__(self, llm=None) -> None:
        self.llm = llm

    def investigate(self, run, log: str | None = None) -> dict:
        if isinstance(run, Outcome):
            d = run.as_dict()
            d["log"] = run.log            # as_dict() omits the (potentially large) log
        else:
            d = dict(run)
        text = log if log is not None else d.get("log", "") or ""
        outcome = d.get("outcome") or d.get("verdict") or "unknown"

        category, hint = self._classify(outcome, text)
        loc = _LOC.search(text)
        evidence = []
        if loc:
            evidence.append(f"{loc.group(1)}:{loc.group(2)}")
        err = _ERROR.search(text)
        if err:
            evidence.append(err.group(0).strip()[:160])

        return {
            "category": category,
            "tool": d.get("tool"),
            "outcome": outcome,
            "file": loc.group(1) if loc else None,
            "line": int(loc.group(2)) if loc else None,
            "root_cause": self._root_cause(category, text, loc),
            "evidence": evidence,
            "hint": hint,
        }

    @staticmethod
    def _classify(outcome: str, text: str) -> tuple[str, str]:
        if outcome == "tool_missing":
            return "tool_missing", "install the tool or point WENGOLD at a different one"
        if outcome == "timeout":
            return "timeout", "raise the budget or narrow the check; do not treat as a pass"
        if re.search(r"\b(syntax error|parse error|cannot find|unresolved include|"
                     r"elaborat|undeclared)\b", text, re.IGNORECASE):
            return "elaboration_error", "fix the source so the design elaborates, then rerun"
        if _ASSERT.search(text):
            return "assertion_failure", "trace the failing property to the signal it checks"
        if _CEX.search(text):
            return "formal_counterexample", "read the counterexample trace; the property is false"
        if _MISMATCH.search(text):
            return "mismatch", "compare the DUT and reference model at the first divergence"
        if outcome == "unknown":
            return "inconclusive", "the check proved nothing; strengthen the property or budget"
        if outcome == "fail":
            return "check_failed", "the check genuinely failed; investigate the design"
        if outcome == "error":
            return "tool_error", "the tool crashed; capture the log and rerun"
        return "unknown", "insufficient evidence"

    @staticmethod
    def _root_cause(category: str, text: str, loc) -> str:
        where = f" at {loc.group(1)}:{loc.group(2)}" if loc else ""
        return {
            "tool_missing": "the tool is not installed",
            "timeout": "the run exceeded its time budget",
            "elaboration_error": f"the design did not elaborate{where}",
            "assertion_failure": f"a property was violated{where}",
            "formal_counterexample": f"a proof found a counterexample{where}",
            "mismatch": f"the design and the reference disagree{where}",
            "inconclusive": "the check was inconclusive",
            "check_failed": f"the check failed{where}",
            "tool_error": "the tool exited abnormally",
        }.get(category, "unclassified failure")
