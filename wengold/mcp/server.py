"""WENGOLD MCP server.

Exposes the graph, kernel and ledger as tools so any MCP-capable coding agent
(Claude Code, opencode, Copilot, ...) can ask what changed, what still holds, and
what to run next.

It speaks JSON-RPC 2.0 over stdio and implements the MCP `initialize`,
`tools/list` and `tools/call` methods. `handle()` is pure and testable; `main()`
runs the stdio loop.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from ..graph.model import DesignGraph, NodeKind
from ..kernel.minimize import minimum_new_evidence
from ..kernel.validity import Result, classify_all
from ..ledger.store import Ledger

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "wengold", "version": "0.2.0"}

TOOLS = [
    {"name": "wengold_graph_query",
     "description": "Query the design dependency graph (nodes, edges, completeness).",
     "inputSchema": {"type": "object", "properties": {
         "kind": {"type": "string"}, "id": {"type": "string"}}}},
    {"name": "wengold_classify",
     "description": "Classify prior verification results against a set of changed nodes.",
     "inputSchema": {"type": "object", "required": ["changed", "results"], "properties": {
         "changed": {"type": "array", "items": {"type": "string"}},
         "results": {"type": "array", "items": {"type": "object"}}}}},
    {"name": "wengold_min_new_evidence",
     "description": "Return the minimum set of results to re-establish after a change.",
     "inputSchema": {"type": "object", "required": ["changed", "results"], "properties": {
         "changed": {"type": "array", "items": {"type": "string"}},
         "results": {"type": "array", "items": {"type": "object"}}}}},
    {"name": "wengold_ledger_append",
     "description": "Append a record to the verification ledger.",
     "inputSchema": {"type": "object", "required": ["kind", "payload"], "properties": {
         "kind": {"type": "string"}, "payload": {"type": "object"}}}},
]


def _results(payload: list[dict]) -> list[Result]:
    out = []
    for r in payload:
        out.append(Result(id=r["id"], kind=r.get("kind", "sim"),
                          depends_on=set(r.get("depends_on", [])),
                          depends_on_results=set(r.get("depends_on_results", []))))
    return out


class WengoldServer:
    def __init__(self, graph: DesignGraph | None = None, ledger: Ledger | None = None) -> None:
        self.graph = graph if graph is not None else DesignGraph()
        if ledger is not None:
            self.ledger = ledger
        else:
            tmp = Path(tempfile.mkdtemp(prefix="wengold-mcp-")) / "ledger.tof"
            self.ledger = Ledger(tmp)

    # ---- tools --------------------------------------------------------
    def call(self, name: str, args: dict) -> dict:
        if name == "wengold_graph_query":
            return self._graph_query(args)
        if name == "wengold_classify":
            return self._classify(args)
        if name == "wengold_min_new_evidence":
            return self._min_new_evidence(args)
        if name == "wengold_ledger_append":
            rec = self.ledger.append(args["kind"], args.get("payload", {}))
            return {"seq": rec["seq"], "hash": rec["hash"]}
        raise KeyError(name)

    def _graph_query(self, args: dict) -> dict:
        kind = args.get("kind")
        node_id = args.get("id")
        if node_id:
            node = self.graph.nodes.get(node_id)
            if node is None:
                return {"found": False, "id": node_id}
            return {"found": True, "node": {"id": node.id, "kind": node.kind.value,
                                            "resolved": node.resolved,
                                            "depends_on": sorted(self.graph.ancestors(node_id))}}
        nodes = [{"id": n.id, "kind": n.kind.value, "resolved": n.resolved}
                 for n in self.graph.nodes.values()
                 if kind is None or n.kind.value == kind]
        return {"count": len(nodes), "nodes": nodes, "completeness": self.graph.completeness()}

    def _classify(self, args: dict) -> dict:
        changed = set(args.get("changed", []))
        results = _results(args.get("results", []))
        classes = classify_all(self.graph, results, changed)
        return {"classification": {c.result.id: {"verdict": c.verdict.value,
                                                 "reason": c.reason} for c in classes}}

    def _min_new_evidence(self, args: dict) -> dict:
        changed = set(args.get("changed", []))
        results = _results(args.get("results", []))
        classes = classify_all(self.graph, results, changed)
        deps = args.get("result_deps")
        return {"reverify": minimum_new_evidence(self.graph, classes, deps)}

    # ---- JSON-RPC -----------------------------------------------------
    def handle(self, request: dict) -> dict | None:
        method = request.get("method")
        rid = request.get("id")
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            result = {"protocolVersion": PROTOCOL_VERSION,
                      "capabilities": {"tools": {}},
                      "serverInfo": SERVER_INFO}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = request.get("params", {})
            name = params.get("name")
            try:
                payload = self.call(name, params.get("arguments", {}) or {})
                result = {"content": [{"type": "text", "text": json.dumps(payload)}]}
            except Exception as e:  # a tool error is a result, not a crash
                result = {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                          "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def serve(self, instream, outstream) -> None:
        for line in instream:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                outstream.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                            "error": {"code": -32700,
                                                      "message": "parse error"}}) + "\n")
                outstream.flush()
                continue
            response = self.handle(request)
            if response is not None:
                outstream.write(json.dumps(response) + "\n")
                outstream.flush()


def main() -> None:
    WengoldServer().serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
