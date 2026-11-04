"""A local model, if you have one. The agent works without it.

**This module has never been run against a real model.** It was written in a sandbox
with 2 CPUs and 2 GB of RAM, where no useful model fits. What *is* verified here is
the client: it is tested against a mock server that speaks the same protocol, so the
request shape, the response parsing, the timeout and the failure paths are real. The
one thing not verified is the model's output quality — that needs your machine.

Run `wengold doctor --llm` to check it end to end on your hardware.

Why local
---------
The point is not to replace the kernel. Every decision the agent currently makes is
justified by a graph fact and costs microseconds; a 7B model on CPU costs seconds.
What a model adds is the thing the kernel cannot do at all: write RTL from a sentence
the spec grammar does not cover, and explain a failure in prose. So this is used for
those two jobs and nothing else, and it is **off unless you turn it on**.

What it will not do
-------------------
* It never decides what to check. That is the kernel's job and a model's guess there
  would be a regression, not an improvement.
* It never returns an answer when the server is down. `LLMUnavailable` is raised, so
  a caller cannot mistake "no model" for "no problem".
* It never marks its own output as verified. Anything a model writes is a suggestion
  and is labelled as one.
"""
from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

__all__ = ["LocalModel", "LLMUnavailable", "ModelInfo", "probe", "from_env"]


class LLMUnavailable(RuntimeError):
    """No model answered. Never swallowed into an empty string."""


@dataclass
class ModelInfo:
    name: str
    backend: str                 # "ollama" | "openai"
    endpoint: str
    models: list[str] = field(default_factory=list)

    def render(self) -> str:
        return (f"  {self.backend} at {self.endpoint} — "
                f"{len(self.models)} model(s): {', '.join(self.models[:4]) or 'none'}")


DEFAULT_OLLAMA = "http://127.0.0.1:11434"
DEFAULT_OPENAI = "http://127.0.0.1:8080/v1"


def from_env() -> LocalModel | None:
    """Build a client from the environment, or None if nothing is configured.

    WENGOLD_LLM_MODEL   model name, e.g. qwen2.5-coder:7b
    WENGOLD_LLM_URL     endpoint; defaults to Ollama's
    WENGOLD_LLM_BACKEND "ollama" (default) or "openai"
    """
    model = os.environ.get("WENGOLD_LLM_MODEL", "").strip()
    if not model:
        return None
    backend = os.environ.get("WENGOLD_LLM_BACKEND", "ollama").strip().lower()
    url = os.environ.get("WENGOLD_LLM_URL", "").strip() or (
        DEFAULT_OPENAI if backend == "openai" else DEFAULT_OLLAMA)
    return LocalModel(model=model, endpoint=url, backend=backend)


def probe(endpoint: str = DEFAULT_OLLAMA, backend: str = "ollama",
          timeout: float = 2.0) -> ModelInfo:
    """Ask the server what it has. Raises LLMUnavailable if nothing answers."""
    if backend == "openai":
        url = endpoint.rstrip("/") + "/models"
        data = _get_json(url, timeout)
        names = [m.get("id", "?") for m in (data.get("data") or [])]
    else:
        url = endpoint.rstrip("/") + "/api/tags"
        data = _get_json(url, timeout)
        names = [m.get("name", "?") for m in (data.get("models") or [])]
    return ModelInfo(name=names[0] if names else "", backend=backend,
                     endpoint=endpoint, models=names)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect.

    urllib follows a 302 by default, and for a POST it rewrites the method to GET
    — so a redirect silently drops the prompt and returns another server's body as
    the model's answer. For a tool that promises "nothing leaves the machine" that
    is both a wrong answer and a leak.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LLMUnavailable(
            f"{req.full_url} redirected to {newurl}; refusing to follow. Point "
            f"WENGOLD_LLM_URL at the final address.")


_OPENER = urllib.request.build_opener(_NoRedirect)


def _get_json(url: str, timeout: float) -> dict:
    try:
        with _OPENER.open(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except (urllib.error.URLError, OSError, ValueError, RecursionError) as e:
        raise LLMUnavailable(
            f"no model server at {url} ({type(e).__name__}). Start one with "
            f"`ollama serve`, or set WENGOLD_LLM_URL.") from e
    except http.client.HTTPException as e:
        raise LLMUnavailable(f"{url} sent a malformed response ({type(e).__name__})") from e
    if not isinstance(data, dict):
        raise LLMUnavailable(f"{url} returned {type(data).__name__}, not a JSON object")
    return data





class LocalModel:
    """A chat/generate client for a local server. Nothing leaves the machine."""

    def __init__(self, model: str, endpoint: str = DEFAULT_OLLAMA,
                 backend: str = "ollama", timeout: float = 120.0,
                 temperature: float = 0.2):
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.backend = backend
        self.timeout = timeout
        self.temperature = temperature
        self.calls = 0

    # ---- the one method that matters -----------------------------------
    def ask(self, prompt: str, system: str = "") -> str:
        """One completion. Raises LLMUnavailable rather than returning "".

        An empty string would read as "the model had nothing to say", which is a
        different and much worse claim than "there is no model".
        """
        self.calls += 1
        if self.backend == "openai":
            return self._openai(prompt, system)
        return self._ollama(prompt, system)

    def _ollama(self, prompt: str, system: str) -> str:
        body = {"model": self.model, "prompt": prompt, "stream": False,
                "options": {"temperature": self.temperature}}
        if system:
            body["system"] = system
        data = self._post("/api/generate", body)
        raw = data.get("response")
        if raw is not None and not isinstance(raw, str):
            raise LLMUnavailable(
                f"{self.model} returned a {type(raw).__name__} where text was "
                f"expected")
        text = (raw or "").strip()
        if not text:
            raise LLMUnavailable(f"{self.model} returned an empty response")
        # A truncated answer must not read as a complete one. `done_reason` is
        # `length` when the model hit its limit mid-answer.
        if str(data.get("done_reason") or "") == "length":
            raise LLMUnavailable(
                f"{self.model} stopped at its context limit; the answer is "
                f"truncated. Raise num_ctx or shorten the prompt.")
        return text

    def _openai(self, prompt: str, system: str) -> str:
        messages = ([{"role": "system", "content": system}] if system else [])
        messages.append({"role": "user", "content": prompt})
        data = self._post("/chat/completions",
                          {"model": self.model, "messages": messages,
                           "temperature": self.temperature, "stream": False})
        try:
            raw = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise LLMUnavailable(f"unexpected response from {self.model}") from e
        if raw is not None and not isinstance(raw, str):
            raise LLMUnavailable(
                f"{self.model} returned a {type(raw).__name__} where text was "
                f"expected")
        text = (raw or "").strip()
        if not text:
            raise LLMUnavailable(f"{self.model} returned an empty response")
        if data["choices"][0].get("finish_reason") == "length":
            raise LLMUnavailable(
                f"{self.model} stopped at its token limit; the answer is truncated.")
        return text

    def _post(self, path: str, body: dict) -> dict:
        url = self.endpoint + path
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with _OPENER.open(req, timeout=self.timeout) as r:
                data = json.loads(r.read().decode("utf-8", "replace") or "{}")
        except urllib.error.HTTPError as e:
            # the error path must not itself raise: a short body here used to
            # escape as http.client.IncompleteRead
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:                                    # noqa: BLE001
                detail = ""
            raise LLMUnavailable(
                f"{url} returned HTTP {e.code}: {detail}") from e
        except LLMUnavailable:
            raise
        except (urllib.error.URLError, OSError) as e:
            raise LLMUnavailable(
                f"could not reach {url} ({type(e).__name__}). Is the server "
                f"running, and is the model pulled?") from e
        except http.client.HTTPException as e:
            # IncompleteRead and friends are HTTPException, not OSError
            raise LLMUnavailable(
                f"{url} sent a malformed or truncated response "
                f"({type(e).__name__})") from e
        except RecursionError as e:
            raise LLMUnavailable(f"{url} returned deeply nested JSON") from e
        except ValueError as e:
            raise LLMUnavailable(f"{url} did not return JSON") from e
        if not isinstance(data, dict):
            raise LLMUnavailable(
                f"{url} returned {type(data).__name__}, not a JSON object")
        return data

    # ---- the jobs the kernel cannot do ---------------------------------
    def explain_failure(self, verdict_text: str) -> str:
        """Prose explanation of a failure the kernel already established."""
        return self.ask(
            "Explain this silicon-verification result to an engineer, in at most "
            "four sentences. Do not speculate about causes you cannot see in the "
            "text, and do not claim the design is correct.\n\n" + verdict_text,
            system="You explain verification results. You never invent facts.")

    def draft_rtl(self, spec: str, language: str = "SystemVerilog") -> str:
        """RTL from a description the spec grammar does not cover.

        The output is a *suggestion*: nothing here has been simulated, elaborated
        or checked, and the caller must say so.
        """
        return self.ask(
            f"Write synthesizable {language} for the following. Return code only, "
            f"no prose. It will be compiled by iverilog and must have no vendor "
            f"primitives.\n\n{spec}",
            system="You write RTL. You do not claim it is verified.")

    def render(self) -> str:
        return f"  {self.backend}/{self.model} at {self.endpoint} ({self.calls} call(s))"
