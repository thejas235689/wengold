"""The drafting step: a model may write RTL, and compiling is not verifying.

This is the one place the agentic loop lets a model act. The rules it must keep:

  * **opt-in** — without `--draft` the loop behaves exactly as before;
  * **the claim is narrow** — "it compiles" is the only fact reported about model
    output, and it is never called verification;
  * **three states, not two** — no compiler is `unchecked`, not `failed`, because
    collapsing them blames the model for the environment.

Every case here runs against a mock server. No real model is involved.
"""
import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from wengold.agent.coding import code

GOOD = "module fifo(input logic clk, input logic rst_n, output wire full);\n  assign full = 1'b0;\nendmodule\n"
BAD = "module fifo(input logic clk, output wire full);\n  assign full = ;\nendmodule\n"


class Mock:
    def __init__(self, rtl):
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                b = json.dumps({"response": outer.rtl}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.rtl = rtl
        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def empty(tmp_path):
    return tmp_path


def test_without_draft_the_loop_is_unchanged(empty, monkeypatch):
    """Opt-in: no --draft means no model call, whatever is configured."""
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
    run = code("a fifo", str(empty))
    assert run.steps == []
    assert "nothing left that can be justified" in run.reason


def test_no_model_says_so_and_does_not_blame_a_compile(empty, monkeypatch):
    monkeypatch.delenv("WENGOLD_LLM_MODEL", raising=False)
    run = code("a fifo", str(empty), draft=True)
    assert "no local model is configured" in run.reason
    assert "did NOT compile" not in run.reason


def test_a_model_that_does_not_answer_is_reported(empty, monkeypatch):
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
    monkeypatch.setenv("WENGOLD_LLM_URL", "http://127.0.0.1:9")
    run = code("a fifo", str(empty), draft=True)
    assert "did not answer" in run.reason


def test_without_a_compiler_the_draft_is_unchecked_not_failed(empty, monkeypatch):
    """Collapsing 'no iverilog' into 'did not compile' blames the model for the
    environment."""
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    with Mock(GOOD) as m:
        monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
        monkeypatch.setenv("WENGOLD_LLM_URL", m.url)
        run = code("a fifo", str(empty), draft=True, apply=True)
    assert "[unchecked]" in run.steps[0].outcome
    assert "did NOT compile" not in run.reason


@pytest.mark.skipif(not shutil.which("iverilog"), reason="iverilog not installed")
def test_good_rtl_compiles_and_is_still_not_called_verified(empty, monkeypatch):
    with Mock(GOOD) as m:
        monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
        monkeypatch.setenv("WENGOLD_LLM_URL", m.url)
        run = code("a fifo", str(empty), draft=True, apply=True)
    assert run.done is True
    assert "compiles" in run.steps[0].outcome
    assert "not verifying" in run.reason
    assert (empty / "fifo.sv").exists()


@pytest.mark.skipif(not shutil.which("iverilog"), reason="iverilog not installed")
def test_bad_rtl_is_reported_as_the_models_failure(empty, monkeypatch):
    with Mock(BAD) as m:
        monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
        monkeypatch.setenv("WENGOLD_LLM_URL", m.url)
        run = code("a fifo", str(empty), draft=True, apply=True)
    assert run.done is False
    assert "did NOT compile" in run.reason
    assert "the model's" in run.reason


def test_without_apply_nothing_is_written(empty, monkeypatch):
    with Mock(GOOD) as m:
        monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
        monkeypatch.setenv("WENGOLD_LLM_URL", m.url)
        run = code("a fifo", str(empty), draft=True, apply=False)
    assert not list(empty.glob("*.sv"))
    assert "not written" in run.steps[0].outcome
