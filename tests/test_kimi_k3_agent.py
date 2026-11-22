"""Tests for the local Kimi K3 C CLI agent adapter.

These tests use a tiny fake executable. They validate invocation, input handling,
JSON evidence checks and failure paths; they do not download or run Kimi weights.
"""
import json
import os
from pathlib import Path

import pytest

from wengold.agent.llm import (
    KimiK3CLIModel, LLMUnavailable, from_env, probe,
)


def fake_k3(tmp_path: Path, *, layers_done=93, expert_drops=0, interrupted=False):
    binary = tmp_path / "fake-k3"
    binary.write_text("""#!/usr/bin/env python3
import json, pathlib, sys
args = sys.argv[1:]
out = pathlib.Path(args[args.index('--out') + 1])
prompt = pathlib.Path(args[args.index('--prompt-file') + 1]).read_text(encoding='utf-8')
json.dump({
  'layers_requested': 93,
  'layers_completed': int(__import__('os').environ.get('FAKE_K3_LAYERS', '93')),
  'expert_drops': int(__import__('os').environ.get('FAKE_K3_DROPS', '0')),
  'interrupted': __import__('os').environ.get('FAKE_K3_INTERRUPTED', '0') == '1',
  'generated_text': 'K3 response: ' + prompt
}, out.open('w', encoding='utf-8'))
""")
    binary.chmod(0o755)
    model_dir, trunk_dir = tmp_path / "model", tmp_path / "trunk"
    model_dir.mkdir()
    trunk_dir.mkdir()
    return binary, model_dir, trunk_dir


def test_kimi_k3_cli_uses_prompt_file_and_validates_json(tmp_path):
    binary, model_dir, trunk_dir = fake_k3(tmp_path)
    model = KimiK3CLIModel(
        str(binary), str(model_dir), str(trunk_dir),
        tokenizer_dir=str(model_dir), max_tokens=64, timeout=5,
    )
    answer = model.ask("Draft an AXI assertion", system="Use only supplied facts.")
    assert "Use only supplied facts." in answer
    assert "Draft an AXI assertion" in answer
    assert model.calls == 1


def test_kimi_k3_cli_rejects_partial_layer_execution(tmp_path, monkeypatch):
    binary, model_dir, trunk_dir = fake_k3(tmp_path)
    monkeypatch.setenv("FAKE_K3_LAYERS", "92")
    model = KimiK3CLIModel(str(binary), str(model_dir), str(trunk_dir), timeout=5)
    with pytest.raises(LLMUnavailable, match="partial output rejected"):
        model.ask("test")


def test_kimi_k3_cli_rejects_expert_drops(tmp_path, monkeypatch):
    binary, model_dir, trunk_dir = fake_k3(tmp_path)
    monkeypatch.setenv("FAKE_K3_DROPS", "1")
    model = KimiK3CLIModel(str(binary), str(model_dir), str(trunk_dir), timeout=5)
    with pytest.raises(LLMUnavailable, match="expert load drops"):
        model.ask("test")


def test_kimi_k3_cli_requires_model_and_trunk_paths():
    model = KimiK3CLIModel()
    with pytest.raises(LLMUnavailable, match="WENGOLD_K3_MODEL_DIR"):
        model.ask("test")


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
