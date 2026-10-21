"""WENGOLD MCP server.

Exposes the graph, kernel and ledger as tools so any MCP-capable coding agent
can query what changed, what still holds, and what to run next.
"""
from __future__ import annotations

TOOLS = [
    {"name": "wengold_graph_query", "description": "Query the design dependency graph."},
    {"name": "wengold_classify", "description": "Classify prior results against a change set."},
    {"name": "wengold_min_new_evidence", "description": "Return the minimum re-verification set."},
    {"name": "wengold_ledger_append", "description": "Append an evidence record to the ledger."},
]


def main() -> None:
    raise NotImplementedError("wire to the `mcp` package; see pyproject [mcp] extra")
