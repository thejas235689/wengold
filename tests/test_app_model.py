"""The model inside the app: two commands, and a clean fallback.

The app is where a local model is actually useful — you type a question and read the
answer in the same pane as the design. What these tests pin is the wiring and the
**fallback**: with no model configured, `ask` must say so and point at the fix, and
`explain` must still give the kernel's facts. A command that silently does nothing
when a model is absent is worse than one that is not there.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from wengold.desktop import CLI_COMMANDS, _exec, build_state


@pytest.fixture
def design(tmp_path):
    (tmp_path / "m.sv").write_text(
        "module m(input logic c, output logic q);\n  assign q = c;\nendmodule\n")
    return build_state(str(tmp_path))


class Mock:
    def __init__(self, answer="a 4-bit counter"):
        self.answer = answer
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                self.rfile.read(n)
                body = json.dumps({"response": outer.answer}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()


def test_the_commands_exist(design):
    assert "ask" in CLI_COMMANDS and "explain" in CLI_COMMANDS


def test_ask_without_a_model_says_how_to_get_one(design, monkeypatch):
    monkeypatch.delenv("WENGOLD_LLM_MODEL", raising=False)
    r = _exec(design, "ask what does this do?")
    assert r["ok"] is False
    assert "WENGOLD_LLM_MODEL" in r["output"]
    assert "doctor --llm" in r["output"]
    # and it must not pretend the rest of the app is broken
    assert "works without one" in r["output"]


def test_explain_without_a_model_still_gives_the_facts(design, monkeypatch):
    """The verdicts are the kernel's; they do not need a model to be worth
    printing."""
    monkeypatch.delenv("WENGOLD_LLM_MODEL", raising=False)
    r = _exec(design, "explain")
    # The contract changed with the state model: `explain` now reports success,
    # because the facts ARE the answer, and says what is missing (the prose)
    # rather than that the command failed.
    assert r["ok"] is True, r
    assert r.get("kind") == "note", r
    assert "the prose does" in r["output"], r
    assert "the kernel's verdicts" in r["output"], r
    assert r["output"].strip() != "no local model configured"


def test_ask_routes_to_the_model(design, monkeypatch):
    with Mock(answer="a 4-bit counter") as m:
        monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
        monkeypatch.setenv("WENGOLD_LLM_URL", m.url)
        r = _exec(design, "ask write a counter")
        assert r["ok"] is True
        assert "a 4-bit counter" in r["output"]
        # and it must not let the reader think this was checked
        assert "Not checked" in r["output"]


def test_ask_with_no_question_asks_for_one(design, monkeypatch):
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
    r = _exec(design, "ask")
    assert r["ok"] is False and "needs a question" in r["output"]


def test_a_dead_server_is_reported_not_hidden(design, monkeypatch):
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
    monkeypatch.setenv("WENGOLD_LLM_URL", "http://127.0.0.1:9")
    r = _exec(design, "ask anything")
    assert r["ok"] is False and "unavailable" in r["output"]


def test_the_strip_shows_whether_a_model_is_there(design, monkeypatch):
    monkeypatch.delenv("WENGOLD_LLM_MODEL", raising=False)
    assert build_state(design["path"])["model"] == "off"
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
    assert build_state(design["path"])["model"] == "mock:7b"


# ---- defects found by the parallel verification ------------------------
def test_the_pane_routes_every_command_the_app_handles():
    """The JS hardcoded five verbs, so `ask`, `explain`, `review`, `vibe` and
    `agentic` typed into the app were sent to the generic planner and silently
    did something else — the exact failure this pane exists to avoid."""
    import re
    from wengold.desktop import _page
    html = _page(build_state("."))
    m = re.search(r"const BARE_VERBS = (\[[^]]*\]);", html)
    assert m, "the verb list must be injected"
    for cmd in CLI_COMMANDS:
        assert f'"{cmd}"' in m.group(1), f"{cmd} is not routable from the pane"


def test_explain_always_shows_the_kernel_verdicts(design, monkeypatch):
    """A model saying "this is correct" over an INVALIDATED verdict must not be
    the answer. The facts come first and are never replaced by prose."""
    with Mock(answer="Everything checks out. This design is correct and fully "
                     "verified.") as m:
        monkeypatch.setenv("WENGOLD_LLM_MODEL", "mock:7b")
        monkeypatch.setenv("WENGOLD_LLM_URL", m.url)
        out = _exec(design, "explain")["output"]
    assert "the kernel's verdicts" in out, "the facts must be printed"
    assert out.index("the kernel's verdicts") < out.index("Everything checks out")
    assert "UNCHECKED" in out, "the prose must be labelled"


def test_agentic_forwards_draft_rather_than_absorbing_it(design, monkeypatch):
    """`agentic --draft` used to pass '--draft' as part of the goal string and
    run in non-draft mode, so the command silently did something else."""
    import wengold.agent.coding as C
    from wengold.desktop import _exec
    seen = {}

    def fake_code(goal, root, **kw):
        seen["goal"], seen["draft"] = goal, kw.get("draft", False)
        return C.CodingRun(goal=goal, root=root)

    # `_exec` imports `code` inside the branch, so patch it at the source
    monkeypatch.setattr(C, "code", fake_code)
    _exec(design, "agentic --draft make a fifo")
    assert seen.get("draft") is True, "the flag must reach the loop"
    assert "--draft" not in seen.get("goal", ""), "and must not become the goal"
