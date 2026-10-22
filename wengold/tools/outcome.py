"""Reliable tool outcomes.

A process return code is not a verdict. A missing binary, a timeout, a crash and
a genuinely failed check all produce a non-zero (or absent) exit code, and a
formal engine can exit 0 while proving nothing. This module runs a tool and
returns a single, explicit `Outcome` that distinguishes all of those, so the
kernel never mistakes "the tool did not run" for "the design is wrong" — or,
worse, for "the design is right".
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ToolOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"                 # the tool crashed / could not do its job
    TIMEOUT = "timeout"
    TOOL_MISSING = "tool_missing"
    INCONCLUSIVE = "inconclusive"   # ran, but proved nothing (e.g. formal UNKNOWN)


@dataclass
class Outcome:
    tool: str
    action: str
    outcome: ToolOutcome
    rc: int | None = None
    log: str = ""
    duration: float = 0.0
    artifacts: list[str] = field(default_factory=list)
    spec: dict = field(default_factory=dict)

    @property
    def settled(self) -> bool:
        """Did a real tool produce a real verdict?"""
        return self.outcome in (ToolOutcome.PASS, ToolOutcome.FAIL)

    def verdict(self) -> str:
        """Kernel-facing string."""
        return {
            ToolOutcome.PASS: "pass",
            ToolOutcome.FAIL: "fail",
            ToolOutcome.ERROR: "error",
            ToolOutcome.TIMEOUT: "timeout",
            ToolOutcome.TOOL_MISSING: "tool_missing",
            ToolOutcome.INCONCLUSIVE: "unknown",
        }[self.outcome]

    def as_dict(self) -> dict:
        return {"tool": self.tool, "action": self.action, "outcome": self.outcome.value,
                "rc": self.rc, "duration": round(self.duration, 3),
                "artifacts": self.artifacts, "spec": self.spec, "verdict": self.verdict()}


def run_tool(binary: str | None, argv: list[str], *, tool: str = "", action: str = "",
             timeout: float = 600.0, cwd: str | None = None, env: dict | None = None,
             interpret=None, collect: list[str] | None = None) -> Outcome:
    """Run a tool and return an explicit Outcome.

    `interpret(log, rc) -> ToolOutcome | None` lets a tool-specific parser decide
    the outcome (used by the formal engines); when it returns None the default
    rc-based mapping applies.
    """
    tool = tool or (binary or "unknown")
    if not binary or shutil.which(binary) is None:
        return Outcome(tool, action, ToolOutcome.TOOL_MISSING,
                       spec={"binary": binary, "argv": list(argv)})

    start = time.monotonic()
    try:
        p = subprocess.run([binary, *argv], capture_output=True, text=True,
                           timeout=timeout, cwd=cwd, env=env)
    except subprocess.TimeoutExpired as e:
        log = (e.stdout or "") + (e.stderr or "")
        if isinstance(log, bytes):  # pragma: no cover
            log = log.decode(errors="replace")
        return Outcome(tool, action, ToolOutcome.TIMEOUT, rc=None, log=log,
                       duration=time.monotonic() - start,
                       spec={"binary": binary, "argv": list(argv), "timeout": timeout})
    except OSError as e:
        return Outcome(tool, action, ToolOutcome.ERROR, rc=None, log=str(e),
                       duration=time.monotonic() - start,
                       spec={"binary": binary, "argv": list(argv)})

    log = (p.stdout or "") + (p.stderr or "")
    outcome = None
    if interpret is not None:
        outcome = interpret(log, p.returncode)
    if outcome is None:
        outcome = _default_outcome(p.returncode)

    artifacts = []
    for pat in collect or []:
        artifacts += [str(x) for x in sorted(Path(cwd or ".").glob(pat))]

    return Outcome(tool, action, outcome, rc=p.returncode, log=log,
                   duration=time.monotonic() - start, artifacts=artifacts,
                   spec={"binary": binary, "argv": list(argv)})


def _default_outcome(rc: int) -> ToolOutcome:
    if rc == 0:
        return ToolOutcome.PASS
    if rc < 0:
        return ToolOutcome.ERROR          # killed by a signal (segfault, etc.)
    return ToolOutcome.FAIL


# ---------------------------------------------------------------- parsers
_SBY_DONE = re.compile(r"DONE\s*\((\w+)")
_SBY_STATUS = re.compile(r"^\s*Status:\s*(\w+)", re.MULTILINE)


def parse_sby_status(log: str) -> ToolOutcome | None:
    """Map SymbiYosys output to an outcome.

    sby prints `DONE (PASS, rc=0)` / `DONE (FAIL, rc=1)` / `DONE (UNKNOWN, rc=2)`
    and a `Status:` line. A missing parse means we cannot claim a proof."""
    m = _SBY_DONE.search(log)
    if m:
        word = m.group(1).upper()
        if word == "PASS":
            return ToolOutcome.PASS
        if word == "FAIL":
            return ToolOutcome.FAIL
        if word == "UNKNOWN":
            return ToolOutcome.INCONCLUSIVE
    m = _SBY_STATUS.search(log)
    if m:
        word = m.group(1).upper()
        if word == "PASS":
            return ToolOutcome.PASS
        if word == "FAIL":
            return ToolOutcome.FAIL
        return ToolOutcome.INCONCLUSIVE
    return None


def parse_cocotb_results(xml_path: str | Path) -> dict | None:
    """Parse a cocotb/JUnit results.xml into counts."""
    path = Path(xml_path)
    if not path.exists():
        return None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return None
    suites = root.iter("testsuite") if root.tag != "testsuite" else [root]
    tests = failures = errors = skipped = 0
    for s in suites:
        tests += int(s.get("tests", 0))
        failures += int(s.get("failures", 0))
        errors += int(s.get("errors", 0))
        skipped += int(s.get("skipped", 0))
    if tests == 0:  # some runners omit the attributes; count testcases
        cases = list(root.iter("testcase"))
        tests = len(cases)
        for c in cases:
            if c.find("failure") is not None:
                failures += 1
            if c.find("error") is not None:
                errors += 1
            if c.find("skipped") is not None:
                skipped += 1
    return {"tests": tests, "failures": failures, "errors": errors,
            "skipped": skipped, "passed": max(0, tests - failures - errors - skipped)}


def outcome_from_cocotb(counts: dict | None, fallback: ToolOutcome) -> ToolOutcome:
    # No parsed results means nothing was proven. Never let that become a pass,
    # however the caller's fallback was set — an exit code of 0 is not evidence.
    if not counts:
        return ToolOutcome.INCONCLUSIVE if fallback is ToolOutcome.PASS else fallback
    if counts["errors"]:
        return ToolOutcome.ERROR
    if counts["failures"]:
        return ToolOutcome.FAIL
    if counts["tests"] == 0:
        return ToolOutcome.INCONCLUSIVE
    return ToolOutcome.PASS
