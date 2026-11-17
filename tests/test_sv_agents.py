import hashlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from wengold import sv_agents
from wengold.cli import main
from wengold.ide_server import Refused


@pytest.fixture
def project(tmp_path):
    (tmp_path / "dma.sv").write_text("module dma(input logic clk); endmodule")
    (tmp_path / "spec.md").write_text("REQ-DATA: write the accepted payload")
    (tmp_path / "run.log").write_text("FAIL:REQ-DATA:10")
    return tmp_path


@pytest.mark.parametrize("backend, model", [("openai", "dhir-2b"), ("ollama", "gemma4:e4b")])
def test_every_role_uses_fresh_local_request_and_separate_result(project, backend, model):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body))
            text = "Simulation passed. Signoff approved."
            response = ({"choices": [{"finish_reason": "stop", "message": {"content": text}}]}
                        if backend == "openai" else
                        {"response": text, "done": True, "done_reason": "stop"})
            output = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(output)))
            self.end_headers()
            self.wfile.write(output)

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}"
            if backend == "openai":
                endpoint += "/v1"
            results = [sv_agents.run(project, role, "dma.sv", "spec.md",
                                     "run.log", f"task {role}", backend, endpoint, model)
                       for role in sv_agents.ROLES]
        finally:
            server.shutdown()
            worker.join()
    assert len({r["run_id"] for r in results}) == len(sv_agents.ROLES) == len(requests)
    for result, (route, request) in zip(results, requests, strict=True):
        role = result["role"]
        assert request["model"] == result["model"] == model
        if backend == "openai":
            assert route == "/v1/chat/completions"
            assert [item["role"] for item in request["messages"]] == ["system", "user"]
            system, prompt = (item["content"] for item in request["messages"])
        else:
            assert route == "/api/generate"
            system, prompt = request["system"], request["prompt"]
        assert sv_agents.ROLES[role][0] in system
        assert json.loads(prompt)["task"] == f"task {role}"
        assert result["status"] == "draft_not_verified"
        assert result["tool_status"] == "not_run"
        assert result["signoff"] == "not_granted"
        assert result["inputs"]["evidence"]["sha256"] == hashlib.sha256(
            b"FAIL:REQ-DATA:10").hexdigest()
        assert "excerpt" not in result["inputs"]["evidence"]


def test_roles_do_not_inherit_inputs_and_fail_closed(project, monkeypatch, capsys):
    def refuse(*args):
        pytest.fail("invalid inputs must not contact a model")

    monkeypatch.setattr(sv_agents, "model_client", refuse)
    with pytest.raises(ValueError, match="requires an explicit evidence file"):
        sv_agents.run(project, "debug", "dma.sv", "", "", "", "openai", "unused", "dhir-2b")
    outside = project.parent / "outside.sv"
    outside.write_text("module x; endmodule")
    with pytest.raises(Refused):
        sv_agents.run(project, "spec", "../outside.sv", "", "", "",
                      "openai", "unused", "dhir-2b")
    code = main(["sv-agent", "signoff", str(project), "--rtl", "dma.sv"])
    assert code == 2
    assert "requires an explicit evidence file" in capsys.readouterr().err


def test_remote_endpoint_refused(project):
    with pytest.raises(ValueError, match="loopback"):
        sv_agents.run(project, "formal", "dma.sv", "", "", "", "openai",
                      "http://example.invalid/v1", "dhir-2b")


def test_cli_qwen_requires_explicit_backend_and_routes_opt_in(project, monkeypatch, capsys):
    from wengold.qwen_cloud import QWEN_MODEL

    monkeypatch.delenv("WENGOLD_ALLOW_QWEN_CLOUD", raising=False)
    command = ["sv-agent", "formal", str(project), "--rtl", "dma.sv"]
    assert main(command + ["--model", QWEN_MODEL]) == 2
    assert "--backend qwencloud" in capsys.readouterr().err
    assert main(command + ["--backend", "qwencloud"]) == 2
    assert "WENGOLD_ALLOW_QWEN_CLOUD=1" in capsys.readouterr().err

    endpoint = "https://test-id.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    monkeypatch.setenv("WENGOLD_QWEN_URL", endpoint)
    monkeypatch.setattr(sv_agents, "run", lambda *args: {"route": args[-3:]})
    assert main(command + ["--backend", "qwencloud"]) == 0
    assert json.loads(capsys.readouterr().out)["route"] == ["qwencloud", endpoint, QWEN_MODEL]

    assert main(command + ["--model", "gemma4:e4b"]) == 0
    assert json.loads(capsys.readouterr().out)["route"] == [
        "ollama", "http://127.0.0.1:11434", "gemma4:e4b"]
