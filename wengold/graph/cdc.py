"""Clock-domain-crossing detection -> CROSSES edges.

A CDC crossing is a first-class node. Because crossings are where verification
results are most fragile, the kernel marks results downstream of a *changed*
crossing as UNKNOWN rather than trusting a stale pass.
"""
from __future__ import annotations

from .model import EdgeKind, Node, NodeKind


def add_crossing(graph, name: str, from_clk: str, to_clk: str, signals: list[str]) -> None:
    cid = f"cdc.{name}"
    graph.add_node(Node(id=cid, kind=NodeKind.CDC, meta={"from": from_clk, "to": to_clk}))
    graph.add_edge(from_clk, cid, EdgeKind.CROSSES)
    graph.add_edge(to_clk, cid, EdgeKind.CROSSES)
    for s in signals:
        graph.add_edge(s, cid, EdgeKind.CROSSES)
