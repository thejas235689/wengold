"""Register-map front-end: SystemRDL / IP-XACT -> graph nodes.

Each register/field becomes a REGMAP node; a write path from the interconnect is
a DRIVES edge, so a change to a field's access policy propagates to the tests
that exercise it.
"""
from __future__ import annotations

from .model import Node, NodeKind


def registers_from_rdl(text: str) -> list[str]:
    """Extract register names from a (subset of) SystemRDL."""
    names = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("reg "):
            names.append(line.split()[1].strip("{}").strip())
    return names


def add_regmap(graph, registers: list[str], driver: str) -> None:
    for r in registers:
        graph.add_node(Node(id=f"reg.{r}", kind=NodeKind.REGMAP))
        graph.add_edge(driver, f"reg.{r}")
