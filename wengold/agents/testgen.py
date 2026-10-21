"""Test generator: writes tests and assertions for the open coverage/requirements."""
from __future__ import annotations


class TestGen:
    def __init__(self, llm=None) -> None:
        self.llm = llm

    def generate(self, target: str, kind: str = "cocotb") -> str:
        raise NotImplementedError("LLM-backed generation lands in v0.2")
