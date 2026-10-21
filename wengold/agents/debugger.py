"""Debugger: traces a failure to the relevant transaction across revisions."""
from __future__ import annotations


class Debugger:
    def __init__(self, llm=None) -> None:
        self.llm = llm

    def investigate(self, run_id: str) -> dict:
        raise NotImplementedError("waveform/log triage lands in v0.2")
