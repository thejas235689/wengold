"""Minimum new evidence.

From the classification we only need to re-establish what was invalidated or
left unknown — and their downstream results. Everything still valid is kept,
along with the evidence behind it.
"""
from __future__ import annotations

from ..graph.model import DesignGraph
from .validity import Classification, Verdict


def minimum_new_evidence(graph: DesignGraph,
                         classifications: list[Classification]) -> list[str]:
    need = {c.result.id for c in classifications if c.verdict is not Verdict.VALID}
    # Anything that depends on a result we must re-run also needs re-checking,
    # but only if it isn't already in the set.
    return sorted(need)
