# lowass/embed.py
"""Cohere Embed v4 through a LiteLLM proxy (/embeddings). Plain httpx, no extra SDK."""
from __future__ import annotations

import logging
from typing import Any

import httpx
import numpy as np

log = logging.getLogger("lowass.embed")

MAX_BATCH = 96  # measured: 96 inputs work, 97 are rejected


class EmbedError(RuntimeError):
    pass


class Embedder:
    def __init__(self, base_url: str, api_key: str, model: str, dimensions: int = 1536, timeout: float = 60.0):
        self.url = base_url.rstrip("/") + "/embeddings"
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.model, self.dimensions, self.timeout = model, dimensions, timeout

    def _post(self, texts: list[str], input_type: str) -> list[list[float]]:
        body: dict[str, Any] = {"model": self.model, "input": texts, "input_type": input_type}
        if self.dimensions != 1536:  # 1536 is the native size; smaller sizes are accepted (256/512/1024 verified)
            body["dimensions"] = self.dimensions
        try:
            r = httpx.post(self.url, headers=self.headers, json=body, timeout=self.timeout)
            r.raise_for_status()
            return [d["embedding"] for d in r.json()["data"]]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise EmbedError(f"embedding failed: {exc}") from exc

    def embed(self, texts: list[str], kind: str = "search_document") -> np.ndarray:
        """kind: search_document for stored text, search_query for the question."""
        out: list[list[float]] = []
        for i in range(0, len(texts), MAX_BATCH):
            out += self._post(texts[i:i + MAX_BATCH], kind)
        return np.asarray(out, dtype=np.float32).reshape(len(texts), -1)
