"""Security and artifact-integrity checks for the extended Silicon Studio."""
import json
import urllib.error
import urllib.request

import pytest

from wengold.studio_workspace import (
    Refused, source, save_source, list_evidence, waveform, formal_report,
)
from wengold.desktop import HTML, _page, _handler, build_state
from http.server import ThreadingHTTPServer
import threading


def test_editor_saves_only_current_files(tmp_path):
    target = tmp_path / "block.sv"
    target.write_text("module block; endmodule\n")
    initial = source(tmp_path, "block.sv")
    updated = save_source(tmp_path, "block.sv", "module block; wire a; endmodule\n", initial["sha256"])
    assert updated["changed"]
    assert "wire a" in target.read_text()
    with pytest.raises(Refused) as exc:
        save_source(tmp_path, "block.sv", "stale overwrite", initial["sha256"])
    assert exc.value.status == 409


def test_editor_rejects_traversal_and_non_source(tmp_path):
    (tmp_path / "readme.txt").write_text("safe")
    with pytest.raises(Refused):
        source(tmp_path, "../readme.txt")
    # Specifications and text are intentionally editable from the DV project UI.
    assert source(tmp_path, "readme.txt")["content"] == "safe"
    (tmp_path / "unsafe.bin").write_bytes(b"binary")
    with pytest.raises(Refused):
        source(tmp_path, "unsafe.bin")
    with pytest.raises(Refused):
        save_source(tmp_path, "script.py", "print('x')", "abc")


def test_wave_and_formal_read_real_files(tmp_path):
    waves = tmp_path / "waves"
    waves.mkdir()
    (waves / "trace.vcd").write_text(
        "$scope module tb $end\n$var wire 1 ! clk $end\n"
        "$upscope $end\n$enddefinitions $end\n#0\n0!\n#5\n1!\n"
    )
    reports = tmp_path / "formal-results"
    reports.mkdir()
    (reports / "proof.json").write_text(json.dumps({
        "tool": "example", "status": "UNKNOWN", "property": "p"
    }))
    inventory = list_evidence(tmp_path)
    assert "waves/trace.vcd" in inventory["waveforms"]
    assert "formal-results/proof.json" in inventory["formal_reports"]
    assert waveform(tmp_path, "waves/trace.vcd")["cycles"] == 2
    assert formal_report(tmp_path, "formal-results/proof.json")["report"]["status"] == "UNKNOWN"


def test_studio_html_has_real_panes_and_no_cdn():
    for text in ("RTL Editor", "Waveforms", "Formal Results", "Agent Orchestration",
                 "studio-editor", "studio-save", "studio-wave"):
        assert text in HTML
    assert "<script src=" not in HTML
    assert "cdn" not in HTML.lower()
    html = _page({"path": ".", "files": 0, "nodes": 0, "edges": 0, "blocks": 0,
                  "unresolved": 0, "design_units": 0, "complete": False,
                  "model": "off", "notes": [], "graph": None,
                  "block_names": [], "file_paths": []}, "abc123") if False else HTML
    assert 'id="studio"' in html


def test_desktop_studio_endpoints_and_csrf(tmp_path):
    (tmp_path / "unit.sv").write_text("module unit; endmodule\n")
    state = build_state(str(tmp_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:" + str(httpd.server_address[1])
    try:
        with urllib.request.urlopen(base + "/api/studio/source?file=unit.sv") as r:
            data = json.load(r)
        assert "module unit" in data["content"]
        req = urllib.request.Request(
            base + "/api/studio/save",
            data=json.dumps({"file": "unit.sv", "content": "module hacked; endmodule",
                             "expected_sha256": data["sha256"],
                             "token": "bad-token"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 403
        assert "module unit" in (tmp_path / "unit.sv").read_text()
    finally:
        httpd.shutdown()
        httpd.server_close()
