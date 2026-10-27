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
    """The MCP server.

    `root` is the project to serve. Without it the server answers every query with
    an empty graph, which is worse than refusing to start — a client sees
    `count: 0` and concludes the design has no blocks.
    """

    MAX_LINE = 4 * 1024 * 1024
    MAX_PAYLOAD = 1024 * 1024

    def __init__(self, graph: DesignGraph | None = None,
                 ledger: Ledger | None = None,
                 root: str | None = None,
                 ledger_path: str | None = None) -> None:
        if graph is not None:
            self.graph = graph
        elif root is not None:
            self.graph = self._load(root)
        else:
            self.graph = DesignGraph()
        if ledger is not None:
            self.ledger = ledger
        else:
            # Keep the ledger next to the project when we have one, and remove the
            # temporary directory on exit otherwise. Every server used to leave one
            # behind: 31 had accumulated in TMPDIR before this was noticed.
            if ledger_path is not None:
                Path(ledger_path).parent.mkdir(parents=True, exist_ok=True)
                self.ledger = Ledger(Path(ledger_path))
            elif root is not None:
                tof = Path(root) / ".tof"
                tof.mkdir(parents=True, exist_ok=True)
                self.ledger = Ledger(tof / "ledger.tof")
            else:
                import atexit
                import shutil
                tmpdir = tempfile.mkdtemp(prefix="wengold-mcp-")
                atexit.register(shutil.rmtree, tmpdir, True)
                self.ledger = Ledger(Path(tmpdir) / "ledger.tof")

    @staticmethod
    def _load(root: str) -> DesignGraph:
        from ..cli import _collect
        from ..graph.builder import GraphBuilder
        files = _collect(root)
        if not files:
            raise SystemExit(f"wengold mcp: no HDL files under {root}")
        return GraphBuilder().build_from_files(files, backend="auto")

    # ---- tools --------------------------------------------------------
    def call(self, name: str, args: dict) -> dict:
        if name == "wengold_graph_query":
            return self._graph_query(args)
        if name == "wengold_classify":
            return self._classify(args)
        if name == "wengold_min_new_evidence":
            return self._min_new_evidence(args)
        if name == "wengold_ledger_append":
            kind = args["kind"]
            if not isinstance(kind, str) or not kind or len(kind) > 64:
                raise ValueError("kind must be a non-empty string of at most 64 chars")
            payload = args.get("payload", {})
            size = len(json.dumps(payload))
            if size > self.MAX_PAYLOAD:
                raise ValueError(f"payload too large: {size} bytes, "
                                 f"limit {self.MAX_PAYLOAD}")
            rec = self.ledger.append(kind, payload)
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
        # JSON-RPC says a batch is an array and a notification has no id, but a
        # *request* is an object. Anything else used to reach `.get` and raise
        # AttributeError, which `serve()` did not catch — one `[1,2,3]` line took
        # the whole session down.
        if not isinstance(request, dict):
            return {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32600,
                              "message": "invalid request: expected a JSON object, "
                                         f"got {type(request).__name__}"}}
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

    MAX_LINE = 4 * 1024 * 1024        # one request may not exceed 4 MiB
    MAX_PAYLOAD = 1024 * 1024         # one ledger payload may not exceed 1 MiB

    def serve(self, instream, outstream) -> None:
        for line in instream:
            if len(line) > self.MAX_LINE:
                # a single unbounded line is a memory-exhaustion vector; refuse it
                # rather than buffering whatever the peer sends
                outstream.write(json.dumps({
                    "jsonrpc": "2.0", "id": None,
                    "error": {"code": -32600,
                              "message": f"request too large: {len(line)} bytes, "
                                         f"limit {self.MAX_LINE}"}}) + "\n")
                outstream.flush()
                continue
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


def main(argv: list | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="wengold serve",
        description="MCP server over stdio. Serves one project.")
    ap.add_argument("path", nargs="?", default=None,
                    help="the project to serve; without it every query is empty")
    ap.add_argument("--ledger", default=None, help="ledger file (default .tof/ledger.tof)")
    args = ap.parse_args(argv)
    if not args.path:
        # Refuse rather than serve an empty graph: `count: 0` reads as "the design
        # has no blocks", which is a wrong answer, not an absent one.
        print("wengold mcp: pass a project path, e.g. `wengold serve ./rtl`",
              file=sys.stderr)
        raise SystemExit(2)
    WengoldServer(root=args.path, ledger_path=args.ledger).serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
