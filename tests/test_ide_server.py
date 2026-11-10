"""The IDE server may write only existing source files inside the project root.

An HTTP endpoint that writes files is a remote-code-execution surface if it is
loose. These tests are the boundary: each one is an attack that must be refused,
and one valid edit that must work.
"""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from wengold.ide_server import (Refused, _handler, run_build, save_file,
                                SOURCE_SUFFIXES)


@pytest.fixture()
def proj(tmp_path):
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "a.sv").write_text("module a; endmodule\n")
    (tmp_path / "run.sh").write_text("not a source file\n")
    (tmp_path / "README.md").write_text("docs\n")
    return tmp_path


# -- the write boundary -----------------------------------------------------
def test_a_valid_edit_is_written(proj):
    r = save_file(proj, "rtl/a.sv", "module a; assign q = 1; endmodule\n")
    assert r["changed"] is True
    assert (proj / "rtl" / "a.sv").read_text().startswith("module a; assign")


def test_an_identical_write_says_nothing_was_written(proj):
    same = (proj / "rtl" / "a.sv").read_text()
    r = save_file(proj, "rtl/a.sv", same)
    assert r["changed"] is False


def test_traversal_is_refused(proj):
    with pytest.raises(Refused):
        save_file(proj, ".." + "/outside.sv", "x")


def test_an_absolute_path_is_refused(proj):
    with pytest.raises(Refused):
        save_file(proj, "/etc/passwd", "x")


def test_a_symlink_out_of_the_root_is_refused(proj, tmp_path_factory):
    outside = tmp_path_factory.mktemp("out") / "secret.sv"
    outside.write_text("secret\n")
    link = proj / "rtl" / "link.sv"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(Refused):
        save_file(proj, "rtl/link.sv", "x")


def test_a_non_source_file_is_refused(proj):
    for rel in ("run.sh", "README.md"):
        with pytest.raises(Refused):
            save_file(proj, rel, "x")


def test_creating_a_new_file_is_refused(proj):
    with pytest.raises(Refused):
        save_file(proj, "rtl/new.sv", "module new; endmodule\n")


# -- the HTTP surface -------------------------------------------------------
@pytest.fixture()
def server(proj):
    token = "t0ken"
    httpd = ThreadingHTTPServer(
        ("127.0.0.1", 0), _handler(proj, token, lambda: "<html>ok</html>"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", token
    httpd.shutdown()


def _post(base, path, body, token=None):
    req = urllib.request.Request(
        base + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"X-Wengold-Token": token} if token else {})},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_it_binds_loopback_only(server):
    base, _ = server
    assert base.startswith("http://127.0.0.1:")


def test_a_mutating_request_without_the_token_is_refused(server):
    base, _ = server
    code, body = _post(base, "/api/save", {"path": "rtl/a.sv", "content": "x"})
    assert code == 403
    assert body.get("refused") is True


def test_a_mutating_request_with_a_wrong_token_is_refused(server):
    base, _ = server
    code, _ = _post(base, "/api/save", {"path": "rtl/a.sv", "content": "x"},
                    token="wrong")
    assert code == 403


def test_save_with_the_token_works(server, proj):
    base, token = server
    code, body = _post(base, "/api/save",
                       {"path": "rtl/a.sv", "content": "module a; endmodule //e\n"},
                       token=token)
    assert code == 200, body
    assert body["changed"] is True


TRAVERSAL = ".." + "/.." + "/etc/passwd"


def test_traversal_is_refused_over_http(server):
    base, token = server
    code, body = _post(base, "/api/save",
                       {"path": TRAVERSAL, "content": "x"}, token=token)
    assert code == 400
    assert "outside the project root" in body["error"]


def test_build_reports_the_real_graph(server, proj):
    base, token = server
    code, body = _post(base, "/api/build", {}, token=token)
    assert code == 200, body
    assert body["ok"] is True
    assert body["files"] >= 1


def test_the_page_is_served(server):
    base, _ = server
    with urllib.request.urlopen(base + "/", timeout=10) as r:
        assert b"<html>" in r.read()


# -- the local model --------------------------------------------------------
def test_no_model_is_a_note_not_a_failure(proj, monkeypatch):
    """A missing model is not a defect in the file, and must not read as one."""
    monkeypatch.delenv("WENGOLD_LLM_MODEL", raising=False)
    from wengold.ide_server import suggest
    r = suggest(proj, "rtl/a.sv")
    assert r["ok"] is False
    assert r["kind"] == "note", r
    assert "facts" in r, "the facts must come back even with no model"
    assert "WENGOLD_LLM_MODEL" in r["hint"]


def test_the_suggestion_is_labelled_and_carries_the_facts(proj, monkeypatch):
    """A suggestion without its facts cannot be checked; without a label it
    reads as a result."""
    import json, threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            b = json.dumps({"data": [{"id": "m"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
            seen["prompt"] = body.get("messages", [{}])[-1].get("content", "")
            b = json.dumps({"choices": [{"message": {"content": "look at a.sv"},
                                         "finish_reason": "stop"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "m")
    # the mock speaks the OpenAI shape, so say so; an unknown model name defaults
    # to the ollama backend, which expects {"response": ...}
    monkeypatch.setenv("WENGOLD_LLM_BACKEND", "openai")
    monkeypatch.setenv("WENGOLD_LLM_URL",
                       f"http://127.0.0.1:{srv.server_address[1]}/v1")
    try:
        from wengold.ide_server import suggest
        r = suggest(proj, "rtl/a.sv")
    finally:
        srv.shutdown()

    assert r["ok"] is True, r
    assert "not a check" in r["note"]
    assert r["facts"], "the facts must be returned alongside the suggestion"
    # the model was given the facts and the source, not just the question
    assert "files" in seen["prompt"]
    assert "module a" in seen["prompt"]


def test_suggest_refuses_a_path_outside_the_root(proj, monkeypatch):
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "m")
    from wengold.ide_server import suggest
    r = suggest(proj, TRAVERSAL)
    assert r["ok"] is False
    assert r["kind"] == "error"
