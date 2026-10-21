"""An evidence record: a claim plus the witness that backs it.

A verdict cannot exist without a witness — a real artifact (log, waveform,
counterexample, report) produced by a real tool, re-checkable later.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Evidence:
    claim: str
    tool: str
    artifact: str
    digest: str
    meta: dict = field(default_factory=dict)
