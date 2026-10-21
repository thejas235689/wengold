"""Repairer: proposes the smallest RTL/register-map change to fix a failure.

Agents propose; every repair is re-verified by the tools before it is trusted.
"""
from __future__ import annotations


class Repairer:
    def __init__(self, llm=None) -> None:
        self.llm = llm

    def propose(self, failure: dict) -> dict:
        raise NotImplementedError("repair proposals land in v0.2")
