import io
import json
from urllib.error import HTTPError

import pytest

from wengold.agent import llm
from wengold import sv_agents
from wengold.ai_workbench import model_client, test_connection as check_connection
from wengold.qwen_cloud import DEFAULT_QWEN, QWEN_BACKEND, QWEN_MODEL


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("WENGOLD_ALLOW_QWEN_CLOUD", "1")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-test-key")


def test_cloud_requires_explicit_opt_in_and_key(monkeypatch):
    monkeypatch.delenv("WENGOLD_ALLOW_QWEN_CLOUD", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="WENGOLD_ALLOW_QWEN_CLOUD"):
        model_client(QWEN_BACKEND, DEFAULT_QWEN, QWEN_MODEL)
    monkeypatch.setenv("WENGOLD_ALLOW_QWEN_CLOUD", "1")
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        model_client(QWEN_BACKEND, DEFAULT_QWEN, QWEN_MODEL)
    for backend in ("ollama", "openai"):
        with pytest.raises(ValueError, match="loopback"):
            model_client(backend, DEFAULT_QWEN, QWEN_MODEL)


@pytest.mark.parametrize("url", [
    "http://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-intl.aliyuncs.com.example.com/compatible-mode/v1",
    "https://user@dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-intl.aliyuncs.com:6000/compatible-mode/v1",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1?redirect=elsewhere",
    "https://dashscope-intl.aliyuncs.com/",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1\n",
    "http://127.0.0.1:11434",
])
def test_cloud_rejects_other_endpoints(enabled, url):
    with pytest.raises(ValueError, match="official Alibaba"):
        model_client(QWEN_BACKEND, url, QWEN_MODEL)


def test_authenticated_chat_and_local_credential_isolation(enabled, monkeypatch):
    requests = []

    def send(request, timeout):
        requests.append(request)
        if request.full_url.endswith("/api/generate"):
            return io.BytesIO(b'{"response":"local answer"}')
        return io.BytesIO(b'{"choices":[{"finish_reason":"stop","message":'
                          b'{"reasoning_content":"not returned","content":"ready"}}]}')

    monkeypatch.setattr(llm._OPENER, "open", send)
    endpoint = "https://abc-42.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
    result = check_connection(QWEN_BACKEND, endpoint, QWEN_MODEL)
    assert result["sample"] == "ready" and result["backend"] == QWEN_BACKEND
    assert requests[0].get_header("Authorization") == "Bearer fake-test-key"
    assert requests[0].full_url == endpoint + "/chat/completions"
    request = json.loads(requests[0].data)
    assert request["model"] == QWEN_MODEL
    assert request["reasoning_effort"] == "low" and request["stream"] is False
    assert 0 < request["max_completion_tokens"] <= 8192
    assert [m["role"] for m in request["messages"]] == ["system", "user"]
    assert model_client("ollama", llm.DEFAULT_OLLAMA, "gemma4:e4b").ask("test") == "local answer"
    assert requests[1].get_header("Authorization") is None


def test_cloud_errors_do_not_echo_request_or_fall_back(enabled, monkeypatch):
    requests = []

    def unavailable(request, timeout):
        requests.append(request)
        raise HTTPError(request.full_url, 429, "quota", None, io.BytesIO(b"private RTL"))

    monkeypatch.setattr(llm._OPENER, "open", unavailable)
    cloud = model_client(QWEN_BACKEND, DEFAULT_QWEN, QWEN_MODEL)
    with pytest.raises(llm.LLMUnavailable, match="429: check rate limits") as error:
        cloud.ask("private RTL")
    assert "private RTL" not in str(error.value)
    assert len(requests) == 1


def test_qwen_agent_output_cannot_grant_signoff(enabled, monkeypatch, tmp_path):
    (tmp_path / "fifo.sv").write_text("module fifo; endmodule\n")
    (tmp_path / "run.log").write_text("FAIL: output mismatch\n")

    def send(request, timeout):
        system, user = json.loads(request.data)["messages"]
        assert "Signoff Review" in system["content"]
        assert json.loads(user["content"])["inputs"]["evidence"]["excerpt"].startswith("FAIL")
        return io.BytesIO(b'{"choices":[{"message":{"content":"Signoff approved."}}]}')

    monkeypatch.setattr(llm._OPENER, "open", send)
    result = sv_agents.run(tmp_path, "signoff", "fifo.sv", "", "run.log", "",
                           QWEN_BACKEND, DEFAULT_QWEN, QWEN_MODEL)
    assert result["backend"] == QWEN_BACKEND
    assert result["status"] == "draft_not_verified"
    assert result["tool_status"] == "not_run"
    assert result["signoff"] == "not_granted"


def test_cloud_model_id_is_exact(enabled):
    with pytest.raises(ValueError, match="only qwen4-max"):
        model_client(QWEN_BACKEND, DEFAULT_QWEN, "qwen4-max-preview")
