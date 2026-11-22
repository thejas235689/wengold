"""Tests for the local Kimi K3 C chat adapter; no checkpoint is downloaded."""
import os
from pathlib import Path
import pytest
from wengold.agent.llm import KimiK3CLIModel, LLMUnavailable, from_env, probe

def fake_k3(tmp_path: Path):
    binary = tmp_path / "fake-k3"
    binary.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
history = pathlib.Path(args[args.index("--history") + 1])
assert "--chat" in args and "--incremental" in args
assert "--thinking-effort" in args and "high" in args
if os.environ.get("FAKE_K3_EXIT"):
    sys.exit(int(os.environ["FAKE_K3_EXIT"]))
if os.environ.get("FAKE_K3_NO_ASSISTANT") != "1":
    records = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines() if line.strip()]
    prompt = " ".join(record["content"] for record in records)
    records.append({"role": "assistant", "content": "K3 response: " + prompt})
    history.write_text("\\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\\n", encoding="utf-8")
sys.stdin.read()
""")
    binary.chmod(0o755)
    model_dir, trunk_dir = tmp_path / "model", tmp_path / "trunk"
    model_dir.mkdir()
    trunk_dir.mkdir()
    return binary, model_dir, trunk_dir

def client_for(binary, model_dir, trunk_dir):
    return KimiK3CLIModel(str(binary), str(model_dir), str(trunk_dir),
                          tokenizer_dir=str(model_dir), max_tokens=64, timeout=5)

def test_kimi_k3_uses_official_chat_history_and_xtml_mode(tmp_path):
    binary, model_dir, trunk_dir = fake_k3(tmp_path)
    model = client_for(binary, model_dir, trunk_dir)
    answer = model.ask("Draft an AXI assertion", system="Use only supplied facts.")
    assert "Use only supplied facts." in answer
    assert "Draft an AXI assertion" in answer
    assert model.calls == 1

def test_kimi_k3_rejects_nonzero_exit(tmp_path, monkeypatch):
    binary, model_dir, trunk_dir = fake_k3(tmp_path)
    monkeypatch.setenv("FAKE_K3_EXIT", "5")
    with pytest.raises(LLMUnavailable, match="exited 5"):
        client_for(binary, model_dir, trunk_dir).ask("test")

def test_kimi_k3_rejects_missing_assistant_turn(tmp_path, monkeypatch):
    binary, model_dir, trunk_dir = fake_k3(tmp_path)
    monkeypatch.setenv("FAKE_K3_NO_ASSISTANT", "1")
    with pytest.raises(LLMUnavailable, match="did not complete an assistant turn"):
        client_for(binary, model_dir, trunk_dir).ask("test")

def test_kimi_k3_requires_model_and_trunk_paths():
    with pytest.raises(LLMUnavailable, match="WENGOLD_K3_MODEL_DIR"):
        KimiK3CLIModel().ask("test")

def test_from_env_routes_kimi_k3_backend(tmp_path, monkeypatch):
    binary, model_dir, trunk_dir = fake_k3(tmp_path)
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "kimi-k3-in-c")
    monkeypatch.setenv("WENGOLD_LLM_BACKEND", "kimi-k3-cli")
    monkeypatch.setenv("WENGOLD_K3_BIN", str(binary))
    monkeypatch.setenv("WENGOLD_K3_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("WENGOLD_K3_TRUNK_DIR", str(trunk_dir))
    model = from_env()
    assert isinstance(model, KimiK3CLIModel)
    assert model.ask("hello").startswith("K3 response:")

def test_probe_kimi_k3_checks_local_paths(tmp_path, monkeypatch):
    binary, model_dir, trunk_dir = fake_k3(tmp_path)
    monkeypatch.setenv("WENGOLD_K3_BIN", str(binary))
    monkeypatch.setenv("WENGOLD_K3_MODEL_DIR", str(model_dir))
    monkeypatch.setenv("WENGOLD_K3_TRUNK_DIR", str(trunk_dir))
    info = probe(backend="kimi-k3-cli")
    assert info.models == ["kimi-k3-in-c"]
    assert info.endpoint == "local executable"
