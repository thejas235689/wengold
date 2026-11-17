"""Multi-RAG retrieval, evidence boundaries, and compiler-loop integration."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading

import pytest

from wengold import ai_workbench
from wengold.cli import main
from wengold.multi_rag import MultiRAG, compiler_probe, context_payload


def _write(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content if isinstance(content, str) else json.dumps(content),
                          encoding="utf-8")


def _manifest(root, sources, compile_files=()):
    _write(root, "multi-rag.json", {
        "sources": [{"kind": kind, "path": path} for kind, path in sources],
        "compile_files": list(compile_files),
    })


def test_declared_artifacts_and_competing_csr_values(tmp_path):
    cases = [("rtl", "rtl/bridge.sv"), ("sva", "dv/bridge.sv"),
             ("spec", "spec/protocol.md"), ("registers", "regs/a.json"),
             ("registers", "regs/b.json"), ("diagram", "spec/captions.json")]
    _write(tmp_path, cases[0][1], "module bridge(input logic clk, rst_n); endmodule\n")
    _write(tmp_path, cases[1][1],
           "module bridge_sva(input logic clk); assert property (@(posedge clk) 1); endmodule")
    _write(tmp_path, cases[2][1], "Bridge reset timing requires two clock edges.")
    for path, val in (("regs/a.json", "0x10"), ("regs/b.json", 20)):
        _write(tmp_path, path, {"name": "bridge", "registers": [
            {"name": "CTRL", "address": val, "fields": [{"name": "enable", "lsb": 0}]}]})
    _write(tmp_path, "spec/edges.svg", "<svg/>")
    _write(tmp_path, cases[-1][1], {"captions": [
        {"asset": "spec/edges.svg", "text": "Bridge waveform shows reset timing at the clock edge."}]})
    _write(tmp_path, "spec/secret.md", "must not be indexed")
    _manifest(tmp_path, cases)
    index = MultiRAG.load(tmp_path)
    query = "bridge CTRL register address assertion and reset timing waveform"
    result = index.retrieve(query)
    assert result == index.retrieve(query)
    assert {s["kind"] for s in result["sources"]} == {kind for kind, _ in cases}
    assert all(s["path"] != "spec/secret.md" and len(s["sha256"]) == 64
               for s in result["sources"])
    caption = next(s for s in result["sources"] if s["kind"] == "diagram")
    assert caption["asset_sha256"] == hashlib.sha256(b"<svg/>").hexdigest()
    assert {v["value"] for v in result["conflicts"]["bridge.ctrl.address"]} == {16, 20}
    assert "bridge.ctrl.address" in index.retrieve(query, symbols=("bridge.CTRL",), limit=1)["conflicts"]
    assert len(index.retrieve(query, limit=2)["sources"]) == 2


def test_slang_index_follows_instantiation_and_package_edges(tmp_path):
    pytest.importorskip("pyslang")
    _write(tmp_path, "top.sv", "// heading\nmodule x(input bit clk); import hw::*; z i(); endmodule")
    _write(tmp_path, "params.sv", "package hw; parameter int X=1; endpackage")
    _write(tmp_path, "blocks.sv", "module y; endmodule\nmodule z; endmodule")
    _manifest(tmp_path, [("rtl", n) for n in ("top.sv", "params.sv", "blocks.sv")])
    index = MultiRAG.load(tmp_path)
    assert index.notes == []
    result = index.retrieve("inspect x module", symbols=("x",), limit=4)
    assert result["sources"][0]["location"] == "L2-L2"
    assert {"x", "hw", "z"} <= {s["symbol"] for s in result["sources"]}
    assert "module y" not in next(s["text"] for s in result["sources"] if s["symbol"] == "z")


def test_bounded_fallback_records_scope(tmp_path, monkeypatch):
    from wengold import multi_rag

    def absent(*_):
        raise ImportError

    monkeypatch.setattr(multi_rag, "_tree", absent)
    _write(tmp_path, "blocks.sv", "// module ignored; endmodule\nmodule real_block; endmodule")
    _manifest(tmp_path, [("rtl", "blocks.sv")])
    index = MultiRAG.load(tmp_path)
    assert [e.symbol for e in index.entries] == ["real_block"]
    assert "bounded text" in index.notes[0]


def test_pdf_text_has_page_provenance(tmp_path):
    if not shutil.which("pdftotext"):
        pytest.skip("pdftotext unavailable")
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    pdf = canvas.Canvas(str(tmp_path / "timing.pdf"))
    pdf.drawString(80, 700, "Timing diagram notes: first page")
    pdf.showPage()
    pdf.drawString(80, 700, "unique_latency requires three cycles")
    pdf.save()
    _manifest(tmp_path, [("spec", "timing.pdf")])
    result = MultiRAG.load(tmp_path).retrieve("unique_latency requires three cycles", limit=1)
    assert result["sources"][0]["location"].startswith("page 2,")
    assert "no OCR" in result["notes"][0]


def test_scope_rejects_traversal_symlinks_and_unlisted_compile_file(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    _write(tmp_path, "external.sv", "module external; endmodule")
    (root / "link.sv").symlink_to(tmp_path / "external.sv")
    for src in ("../external.sv", str(tmp_path / "external.sv"), "link.sv"):
        _manifest(root, [("rtl", src)])
        with pytest.raises(ValueError, match="path"):
            MultiRAG.load(root)
    _write(root, "listed.sv", "module listed; endmodule")
    _manifest(root, [("rtl", "listed.sv")], ["unlisted.sv"])
    with pytest.raises(ValueError, match="compile_files"):
        MultiRAG.load(root)


def test_cli_works_without_model_and_reports_invalid_manifest(capsys):
    example = Path(__file__).parents[1] / "examples" / "dv_workflow"
    assert main(["multi-rag", str(example), "--query", "counter4 reset timing"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {"spec", "rtl"} <= {s["kind"] for s in data["sources"]}
    assert main(["multi-rag", str(example), "--query", "timing",
                 "--manifest", "missing.json"]) == 2
    assert "Multi-RAG" in capsys.readouterr().err


def test_compiler_resolves_declared_packages_but_does_not_read_includes(tmp_path):
    pytest.importorskip("pyslang")
    code = "module x; import hw::*; logic [W-1:0] a; endmodule\n"
    context = {"params.sv": "package hw; parameter int W=3; endpackage\n"}
    assert compiler_probe("/* explanation only */", {})["status"] == "not_run"
    assert compiler_probe(code, {})["symbols"] == ["hw"]
    assert compiler_probe(code, context)["status"] == "clean"
    _write(tmp_path, "hidden.svh", "`define VALUE 4\n")
    result = compiler_probe(f'`include "{tmp_path / "hidden.svh"}"\n' + code, context)
    assert result["status"] == "errors"
    assert any(s.endswith("/hidden.svh") for s in result["symbols"])


def test_prompt_payload_caps_excerpts_and_conflicts():
    full = {"sources": [{"text": "x"*2400, "path": f"{i}.sv"} for i in range(12)],
            "notes": [], "conflicts": {"map.ctrl.reset": [{"value": i} for i in range(40)]}}
    payload = context_payload(full)
    assert len(json.dumps(payload)) <= 16000
    assert payload["conflicts"]["map.ctrl.reset"]["status"].startswith("unresolved")
    assert payload["sources_omitted"] and len(payload["sources"]) < 12


@pytest.mark.parametrize("retry_result,expected", [
    ("module generated; support_pkg::value_t data; endmodule", True),
    ("module generated; broken_package::value_t data; endmodule", False),
])
def test_real_slang_feedback_and_http_model_transport(tmp_path, monkeypatch,
                                                      retry_result, expected):
    pytest.importorskip("pyslang")
    _write(tmp_path, "params.sv", "package support_pkg; typedef logic value_t; endpackage")
    _write(tmp_path, "guidance.md", "Counter counting specification: wrap the counter at max count.")
    requests = []
    initial = "module generated; support_pkg_typo::value_t data; endmodule"
    # First draft names an unavailable module symbol that is present in the RAG
    # corpus as an uncompiled example. Feedback grounds a corrected package usage.
    _write(tmp_path, "examples.sv", "package support_pkg_typo; typedef int value_t; endpackage")
    _manifest(tmp_path, [("rtl", "params.sv"), ("spec", "guidance.md"),
                         ("rtl", "examples.sv")], ["params.sv"])

    class Stub(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            response = json.dumps({"response": initial if len(requests) == 1 else retry_result})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(response.encode())

        def log_message(self, *_):
            pass

    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    with ThreadingHTTPServer(("127.0.0.1", 0), Stub) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            result = ai_workbench.generate(
                "Formal Verification", "Counter counting specification wrap the counter at max count",
                "ollama", f"http://127.0.0.1:{server.server_port}", "stub",
                project_root=tmp_path, rag_manifest="multi-rag.json")
        finally:
            server.shutdown()
            thread.join(timeout=5)
    assert len(requests) == 2
    assert "untrusted project data" in requests[0]["system"]
    assert "examples.sv" not in requests[0]["prompt"]
    assert "examples.sv" in requests[1]["prompt"] and "Compiler feedback" in requests[1]["prompt"]
    assert result["retrieval"]["rounds"][1]["selected"] is expected
    assert result["text"] == (retry_result if expected else initial)
    assert result["status"] == "draft" and result["validation"] == "not run"
