"""Sarvam presets, and the rule that a base model is not asked to follow instructions.

Two Sarvam models are open-weight and they are not interchangeable:

  * **Sarvam-M** — 24B, instruction-tuned, Apache-2.0, served by vLLM.
  * **Sarvam-1** — 2B, a *text-completion* model. Its own card says it "cannot be
    used directly as a chat or an instruction-following model", and its licence is
    non-commercial.

Asking Sarvam-1 to draft RTL returns plausible continuation. This project's whole
rule is that it does not present a guess as a result, so `draft_rtl` and
`explain_failure` refuse on a completion-only model and name the one to use.
"""
import pytest

from wengold.agent.llm import (LLMUnavailable, LocalModel, PRESETS, from_env,
                               preset)


def test_both_sarvam_presets_are_known():
    assert "sarvam-m" in PRESETS and "sarvam-1" in PRESETS


def test_sarvam_m_is_instruction_tuned_and_apache():
    p = PRESETS["sarvam-m"]
    assert p.instruction_tuned is True
    assert p.licence == "Apache-2.0"
    assert p.hf == "sarvamai/sarvam-m"


def test_sarvam_1_is_completion_only_and_non_commercial():
    """Both facts come from the model card, and both change what it can be used
    for, so neither may be quietly dropped."""
    p = PRESETS["sarvam-1"]
    assert p.instruction_tuned is False
    assert "non-commercial" in p.licence.lower()


def test_a_preset_is_found_by_name_or_huggingface_id():
    assert preset("sarvam-m").name == "sarvam-m"
    assert preset("Sarvam_M").name == "sarvam-m"
    assert preset("sarvamai/sarvam-1").name == "sarvam-1"
    assert preset("qwen2.5-coder:7b") is None


# ---- the refusal ------------------------------------------------------
def test_a_completion_model_refuses_to_draft_rtl():
    m = LocalModel("sarvam-1")
    with pytest.raises(LLMUnavailable) as e:
        m.draft_rtl("a fifo")
    msg = str(e.value)
    assert "text-completion" in msg
    assert "sarvam-m" in msg, "it must name the model that can do the job"


def test_a_completion_model_refuses_to_explain_a_failure():
    with pytest.raises(LLMUnavailable):
        LocalModel("sarvam-1").explain_failure("timer: INVALIDATED")


def test_an_instruction_tuned_model_is_not_refused():
    """The guard must not block the model that can actually do the job. No server
    is running, so it fails at the network — which proves it got past the guard."""
    with pytest.raises(LLMUnavailable) as e:
        LocalModel("sarvam-m", "http://127.0.0.1:9", timeout=1.0).draft_rtl("a fifo")
    assert "text-completion" not in str(e.value)


def test_an_unknown_model_is_not_refused():
    """A preset is a convenience, not a whitelist. A model this project has never
    heard of is asked normally."""
    with pytest.raises(LLMUnavailable) as e:
        LocalModel("some-other-model", "http://127.0.0.1:9", timeout=1.0).draft_rtl("x")
    assert "text-completion" not in str(e.value)


# ---- routing ----------------------------------------------------------
def test_from_env_routes_each_preset_to_its_own_backend(monkeypatch):
    """Sarvam-M is published for vLLM (OpenAI-compatible); Sarvam-1 for
    llama.cpp/Ollama. Picking the wrong one means the tool talks to nothing."""
    monkeypatch.delenv("WENGOLD_LLM_BACKEND", raising=False)
    monkeypatch.delenv("WENGOLD_LLM_URL", raising=False)
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "sarvam-m")
    assert from_env().backend == "openai"
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "sarvam-1")
    assert from_env().backend == "ollama"


def test_an_explicit_backend_still_wins(monkeypatch):
    monkeypatch.setenv("WENGOLD_LLM_MODEL", "sarvam-m")
    monkeypatch.setenv("WENGOLD_LLM_BACKEND", "ollama")
    assert from_env().backend == "ollama"


def test_render_says_what_the_model_can_do():
    out = LocalModel("sarvam-1").render()
    assert "completion only" in out
    assert "instruction-tuned" in LocalModel("sarvam-m").render()
