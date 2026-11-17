"""Explicit, authenticated Qwen4-Max transport for supported engineering views."""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from .agent.llm import LocalModel

QWEN_BACKEND = "qwencloud"
QWEN_MODEL = "qwen4-max"
DEFAULT_QWEN = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
_SHARED = {"dashscope-intl.aliyuncs.com", "dashscope.aliyuncs.com",
           "dashscope-us.aliyuncs.com", "cn-hongkong.dashscope.aliyuncs.com"}
_WORKSPACE = re.compile(
    r"[a-z0-9][a-z0-9-]*\.(?:ap-southeast-1|cn-beijing|ap-northeast-1|"
    r"eu-central-1|us-east-1|cn-hongkong)\.maas\.aliyuncs\.com"
)


def qwen_endpoint() -> str:
    return os.environ.get("WENGOLD_QWEN_URL", "").strip() or DEFAULT_QWEN


class QwenCloudModel(LocalModel):
    """One cloud model and first-party HTTPS endpoints. Never a local fallback."""

    def __init__(self, model: str, endpoint: str, timeout: float = 120.0):
        if model != QWEN_MODEL:
            raise ValueError("Qwen Cloud supports only qwen4-max")
        if os.environ.get("WENGOLD_ALLOW_QWEN_CLOUD") != "1":
            raise ValueError("Qwen4-Max sends selected inputs to Alibaba Cloud. "
                             "Set WENGOLD_ALLOW_QWEN_CLOUD=1 to enable it.")
        parsed = urlsplit(endpoint)
        host = parsed.hostname or ""
        if (any(c.isspace() for c in endpoint) or parsed.scheme != "https"
                or parsed.netloc.lower() != host
                or parsed.path.rstrip("/") != "/compatible-mode/v1"
                or "?" in endpoint or "#" in endpoint
                or not (host in _SHARED or _WORKSPACE.fullmatch(host))):
            raise ValueError("Qwen4-Max requires an official Alibaba Model Studio "
                             "HTTPS base URL ending in /compatible-mode/v1")
        self._api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not self._api_key or any(not 33 <= ord(c) <= 126 for c in self._api_key):
            raise ValueError("set DASHSCOPE_API_KEY to a valid Model Studio API key")
        super().__init__(model=model, endpoint=endpoint, backend="openai",
                         timeout=timeout, temperature=0.1)

    def _request_headers(self) -> dict:
        return {**super()._request_headers(), "Authorization": f"Bearer {self._api_key}"}

    def _chat_options(self) -> dict:
        return {**super()._chat_options(), "reasoning_effort": "low",
                "max_completion_tokens": 8192}

    def _http_error_detail(self, error) -> str:
        # A provider error body may echo sensitive input. Do not surface it.
        return {
            401: "check the API key and its region",
            403: "check workspace access to qwen4-max",
            404: "check the workspace endpoint and model availability",
            429: "check rate limits and quota",
        }.get(error.code, "request failed")
