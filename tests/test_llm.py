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
        self.done_reason = "stop"
        self.raw = None
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
                    if outer.raw is not None:
                        self._send(200, outer.raw)
                    else:
                        self._send(200, {"response": outer.answer,
                                         "done_reason": outer.done_reason})
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


# ---- defects found by the four parallel verifications -------------------
def test_a_redirect_is_refused_not_followed():
    """urllib follows a 302 by default and rewrites a POST to GET, dropping the
    prompt — so another server's body came back as the model's answer. For a tool
    that promises nothing leaves the machine, that is a leak as well as a wrong
    answer."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            self.rfile.read(n)
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/evil")
            self.send_header("Content-Length", "0")
            self.end_headers()

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(LLMUnavailable) as e:
            LocalModel("m", f"http://127.0.0.1:{srv.server_address[1]}").ask("x")
        assert "refusing to follow" in str(e.value)
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_truncated_answer_is_not_returned_as_complete():
    """`done_reason: length` means the model hit its limit mid-answer. Returning
    that as a complete response is a wrong answer, not a short one."""
    with Mock(answer="half an answer") as m:
        m.done_reason = "length"
        with pytest.raises(LLMUnavailable) as e:
            LocalModel("m", m.url).ask("x")
        assert "truncated" in str(e.value)


def test_a_non_string_response_raises_rather_than_crashing():
    """`{'response': 12345}` used to escape as AttributeError, which a caller
    catching LLMUnavailable would not catch."""
    with Mock(answer=12345) as m:
        with pytest.raises(LLMUnavailable):
            LocalModel("m", m.url).ask("x")


def test_non_object_json_raises_rather_than_crashing():
    with Mock(answer="x") as m:
        m.raw = [1, 2, 3]
        with pytest.raises(LLMUnavailable):
            LocalModel("m", m.url).ask("x")


def test_a_truncated_http_body_raises_llm_unavailable():
    """http.client.IncompleteRead is an HTTPException, not an OSError, so the
    original `except (URLError, OSError)` missed it."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            self.rfile.read(n)
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b'{"response": "partial"')
            self.close_connection = True

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(LLMUnavailable):
            LocalModel("m", f"http://127.0.0.1:{srv.server_address[1]}").ask("x")
    finally:
        srv.shutdown()
        srv.server_close()


# ---- found by running a real model, not a mock -------------------------
def test_draft_rtl_unfences_whatever_shape_the_model_used():
    """A real model returned ```\\n#include ...\\n``` on the first run. The fence
    stripping lived only in the agentic loop, so every other caller of `draft_rtl`
    got raw markdown — and the loop was the only thing that happened to be safe.
    """
    from wengold.agent.llm import LocalModel
    shapes = {
        "```\nmodule a; endmodule\n```": "module a; endmodule",
        "```systemverilog\nmodule b; endmodule\n```": "module b; endmodule",
        "~~~\nmodule c; endmodule\n~~~": "module c; endmodule",
        "```\nmodule d; endmodule\n```\nHope this helps!": "module d; endmodule",
        "```\nmodule e; endmodule": "module e; endmodule",
        "module f; endmodule": "module f; endmodule",
    }
    for raw, want in shapes.items():
        assert LocalModel.unfence(raw) == want, raw


def test_draft_rtl_strips_the_fence_before_returning():
    """Through the real client, not the helper: a fenced answer must come back as
    code."""
    with Mock(answer="```\nmodule m; endmodule\n```") as srv:
        out = LocalModel("m", srv.url).draft_rtl("a module")
    assert out == "module m; endmodule"
    assert not out.startswith("```")
