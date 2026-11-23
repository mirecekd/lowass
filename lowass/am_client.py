# lowass/am_client.py
"""REST client for agentmemory (implements memlink.MemoryClient). No public method raises."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx

log = logging.getLogger(__name__)

_PREFIX = "/agentmemory"
SEARCH_TIMEOUT = 45.0  # the real server needs 5 to 9 s per search (measured), far more than a write


class AgentMemoryClient:
    """Talks to agentmemory at {host}/agentmemory/<endpoint> with a Bearer secret. Failures are logged and returned."""

    def __init__(self, base_url: str, secret: str, timeout: float = 10.0,
                 post: Callable[..., Any] | None = None, get: Callable[..., Any] | None = None):
        host = base_url.strip().rstrip("/")
        if host.endswith(_PREFIX):
            host = host[: -len(_PREFIX)].rstrip("/")
        self.base = host + _PREFIX
        self.secret = secret
        self.timeout = timeout
        self._post = post or httpx.post
        self._get = get or httpx.get

    def _redact(self, text: str) -> str:
        return text.replace(self.secret, "***") if self.secret else text

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"}

    def _warn(self, what: str, detail: str) -> None:
        log.warning("%s", self._redact(f"agentmemory {what} failed: {detail}"))

    def _call(self, what: str, endpoint: str, body: dict | None = None, timeout: float | None = None) -> tuple[int, Any] | None:
        """One HTTP call. Returns (status, parsed JSON or None) or None when the server was not reached."""
        url = f"{self.base}/{endpoint}"
        wait = self.timeout if timeout is None else timeout
        try:
            if body is None:
                response = self._get(url, headers=self._headers(), timeout=wait)
            else:
                response = self._post(url, headers=self._headers(), json=body, timeout=wait)
            status = int(response.status_code)
        except Exception as exc:  # noqa: BLE001 - any transport failure is a failed call
            self._warn(what, f"{type(exc).__name__}: {exc}")
            return None
        try:
            data = response.json()
        except Exception:  # noqa: BLE001 - a non-JSON body is not fatal here
            data = None
        return status, data

    def _ok(self, what: str, endpoint: str, body: dict, timeout: float | None = None) -> tuple[bool, Any]:
        """POST and report whether the status was 2xx, with the parsed body. Non-2xx is logged with the server's error text."""
        result = self._call(what, endpoint, body, timeout)
        if result is None:
            return False, None
        status, data = result
        if not 200 <= status < 300:
            error = data.get("error") if isinstance(data, dict) else None
            self._warn(what, f"HTTP {status}" + (f": {error}" if isinstance(error, str) else ""))
            return False, data
        return True, data

    def health(self) -> bool:
        result = self._call("health", "livez")
        return result is not None and result[0] == 200

    def start_session(self, session: str, project: str, cwd: str = "/lowass") -> bool:
        ok, _ = self._ok("start_session", "session/start", {"sessionId": session, "project": project, "cwd": cwd})
        return ok

    def end_session(self, session: str) -> bool:
        ok, data = self._ok("end_session", "session/end", {"sessionId": session})
        return ok and isinstance(data, dict) and data.get("success") is True

    def observe(self, payload: dict) -> bool:
        ok, data = self._ok("observe", "observe", payload)
        if not ok:
            return False
        status = data.get("status") if isinstance(data, dict) else None
        if status in ("accepted", "duplicate"):
            return True
        self._warn("observe", f"unexpected answer status {status!r}")
        return False

    def remember(self, payload: dict) -> bool:
        ok, _ = self._ok("remember", "remember", payload)
        return ok

    def search(self, query: str, project: str | None = None, limit: int = 5) -> list[dict] | None:
        body: dict[str, Any] = {"query": query, "limit": max(1, min(10, int(limit)))}
        if project is not None:
            body["project"] = project
        ok, data = self._ok("search", "search", body, SEARCH_TIMEOUT)
        if not ok:
            return None
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            self._warn("search", "the answer has no results list")
            return None
        hits: list[dict] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            obs = item.get("observation")
            obs = obs if isinstance(obs, dict) else {}
            title = _text(obs.get("title")) or _text(item.get("title"))
            text = _text(obs.get("narrative")) or _text(obs.get("content")) or _text(item.get("content")) or title
            score = item.get("score")
            hits.append({
                "layer": _text(item.get("layer")),
                "title": title,
                "text": text,
                "project": project or "",
                "ts": _text(obs.get("timestamp")) or _text(item.get("timestamp")),
                "score": float(score) if isinstance(score, int | float) and not isinstance(score, bool) else 0.0,
            })
        return hits


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
