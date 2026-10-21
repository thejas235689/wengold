"""The MCP server speaks JSON-RPC and exposes the kernel as tools."""
import io
import json

from wengold.demo import build_graph
from wengold.mcp.server import WengoldServer


def _server():
    return WengoldServer(graph=build_graph())


def test_initialize():
    r = _server().handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert r["result"]["serverInfo"]["name"] == "wengold"
    assert r["result"]["protocolVersion"]


def test_tools_list():
    r = _server().handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"wengold_graph_query", "wengold_classify",
            "wengold_min_new_evidence", "wengold_ledger_append"} <= names


def test_tools_call_classify():
    req = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
           "params": {"name": "wengold_classify",
                      "arguments": {"changed": ["sec_firewall"],
                                    "results": [{"id": "sec_acl_test", "kind": "sim",
                                                 "depends_on": ["sec_firewall"]}]}}}
    r = _server().handle(req)
    payload = json.loads(r["result"]["content"][0]["text"])
    assert payload["classification"]["sec_acl_test"]["verdict"] == "invalidated"


def test_tools_call_graph_query():
    req = {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
           "params": {"name": "wengold_graph_query", "arguments": {}}}
    r = _server().handle(req)
    payload = json.loads(r["result"]["content"][0]["text"])
    assert payload["count"] > 0
    assert "completeness" in payload


def test_tools_call_ledger_append():
    s = _server()
    req = {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
           "params": {"name": "wengold_ledger_append",
                      "arguments": {"kind": "note", "payload": {"x": 1}}}}
    r = s.handle(req)
    payload = json.loads(r["result"]["content"][0]["text"])
    assert payload["seq"] == 1


def test_unknown_method_and_bad_tool():
    s = _server()
    assert s.handle({"jsonrpc": "2.0", "id": 6, "method": "nope"})["error"]["code"] == -32601
    r = s.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                  "params": {"name": "no_such_tool", "arguments": {}}})
    assert r["result"]["isError"] is True


def test_notification_has_no_response():
    assert _server().handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_serve_stdio_roundtrip():
    s = _server()
    out = io.StringIO()
    s.serve(io.StringIO('{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n'), out)
    assert "wengold_graph_query" in out.getvalue()
