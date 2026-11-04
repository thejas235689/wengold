"""The local-model client, tested against a mock server.

**No real model is involved.** This sandbox has 2 CPUs and 2 GB of RAM, so the one
thing not tested here is a model's output quality. What is tested is the client:
the request shape each backend expects, the response parsing, the timeout, and the
failure paths — which is where a client actually goes wrong.

The rule these tests exist to protect: **a missing model must raise, not return an
empty string.** An empty answer reads as "nothing to say", which is a different and
much worse claim than "there is no model".
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from wengold.agent.llm import (LLMUnavailable, LocalModel, from_env, probe)


class Mock:
    """A server that speaks enough of Ollama's and OpenAI's protocol to answer."""

    def __init__(self, mode="ollama", answer="logic q;", fail=None):
        self.mode, self.answer, self.fail = mode, answer, fail
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.endswith("/api/tags"):
                    self._send(200, {"models": [{"name": "mock:7b"}]})
                elif self.path.endswith("/models"):
                    self._send(200, {"data": [{"id": "mock-7b"}]})
                else:
                    self._send(404, {})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                outer.requests.append(json.loads(self.rfile.read(n) or b"{}"))
                if outer.fail:
                    self._send(outer.fail, {"error": "boom"})
                elif self.path.endswith("/api/generate"):
                    self._send(200, {"response": outer.answer})
                else:
                    self._send(200, {"choices": [{"message":
                                                  {"content": outer.answer}}]})

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


# ---- probe -------------------------------------------------------------
def test_probe_lists_ollama_models():
    with Mock() as m:
        info = probe(m.url, "ollama")
        assert info.models == ["mock:7b"]
        assert info.backend == "ollama"


def test_probe_lists_openai_models():
    with Mock("openai") as m:
        info = probe(m.url, "openai")
        assert info.models == ["mock-7b"]


def test_probe_raises_when_nothing_is_listening():
    """The failure a user actually hits: the server is not started."""
    with pytest.raises(LLMUnavailable) as e:
        probe("http://127.0.0.1:9", timeout=1.0)
    assert "ollama serve" in str(e.value)


# ---- ask ---------------------------------------------------------------
def test_ollama_request_shape():
    with Mock() as m:
        out = LocalModel("mock:7b", m.url, "ollama").ask("hi", system="be terse")
        assert out == "logic q;"
        body = m.requests[0]
        assert body["model"] == "mock:7b"
        assert body["system"] == "be terse"
        assert body["stream"] is False


def test_openai_request_shape():
    with Mock("openai") as m:
        out = LocalModel("mock-7b", m.url, "openai").ask("hi", system="be terse")
        assert out == "logic q;"
        msgs = m.requests[0]["messages"]
        assert msgs[0] == {"role": "system", "content": "be terse"}
        assert msgs[1] == {"role": "user", "content": "hi"}


def test_an_empty_answer_raises_rather_than_returning_nothing():
    """`""` would read as 'the model had nothing to say' — a worse claim than
    'there is no model'."""
    with Mock(answer="") as m:
        with pytest.raises(LLMUnavailable):
            LocalModel("mock:7b", m.url).ask("hi")


def test_an_http_error_raises_with_the_status():
    with Mock(fail=500) as m:
        with pytest.raises(LLMUnavailable) as e:
            LocalModel("mock:7b", m.url).ask("hi")
        assert "500" in str(e.value)


def test_a_dead_server_raises_rather_than_hanging():
    with pytest.raises(LLMUnavailable):
        LocalModel("mock:7b", "http://127.0.0.1:9", timeout=1.0).ask("hi")


# ---- configuration -----------------------------------------------------
def test_no_model_configured_means_no_client(monkeypatch):
    monkeypatch.delenv("WENGOLD_LLM_MODEL", raising=False)
    assert from_env() is None


def test_the_environment_configures_a_client(monkeypatch):
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "qwen2.5-coder:7b")
    monkeypatch.setenv("WENGOLD_LLM_URL", "http://127.0.0.1:11434")
    c = from_env()
    assert c is not None and c.model == "qwen2.5-coder:7b"


# ---- the jobs it exists for -------------------------------------------
def test_draft_rtl_asks_for_code_and_claims_nothing():
    with Mock(answer="module m; endmodule") as m:
        model = LocalModel("mock:7b", m.url)
        out = model.draft_rtl("a 4-bit counter")
        assert "module" in out
        assert "iverilog" in m.requests[0]["prompt"]
        assert "You do not claim it is verified" in m.requests[0]["system"]


def test_explain_failure_is_told_not_to_invent():
    with Mock(answer="The flop was never reset.") as m:
        model = LocalModel("mock:7b", m.url)
        model.explain_failure("timer: INVALIDATED")
        assert "never invent facts" in m.requests[0]["system"]
