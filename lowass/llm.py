# lowass/llm.py
"""One direct, stateless LiteLLM chat completion without tools."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx


class LlmError(RuntimeError):
    """The completion call failed (network, HTTP status or unexpected answer)."""


class Completer:
    """POST {base_url}/chat/completions (OpenAI format) and return the answer text."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0,
                 post: Callable[..., Any] | None = None):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._post = post or httpx.post

    def _redact(self, text: str) -> str:
        return text.replace(self.api_key, "***") if self.api_key else text

    def complete(self, system: str, user: str, max_tokens: int = 700) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            response = self._post(self.url, headers=headers, json=body, timeout=self.timeout)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            raise LlmError(f"LLM call failed: HTTP {exc.response.status_code} from {self.url}") from None
        except Exception as exc:  # noqa: BLE001 - any failure becomes a readable LlmError
            raise LlmError(self._redact(f"LLM call failed: {type(exc).__name__}: {exc}")) from None
        if not isinstance(content, str):
            raise LlmError("LLM call failed: the answer has no text content")
        return content.strip()
