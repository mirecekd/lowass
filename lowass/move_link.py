# lowass/move_link.py
"""Opens the SSH tunnel and the REST client for the move CLI, from [agentmemory] and AGENTMEMORY_SECRET (like the app does)."""
from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Self

from .am_client import AgentMemoryClient
from .am_service import AM_ENV_VAR
from .am_tunnel import Tunnel

TUNNEL_WAIT_SEC = 45.0


def am_problem(cfg: Any) -> str:
    """'' when agentmemory can be used, else why not (shown to the user; the move then stays local)."""
    if not cfg.section("agentmemory").get("enabled", False):
        return "[agentmemory] is disabled in lowass.toml"
    if not cfg.env(AM_ENV_VAR):
        return f"{AM_ENV_VAR} is not in .env"
    return ""


class AmLink(AbstractContextManager["AmLink"]):
    """`with AmLink(cfg) as link:` -> link.client is ready (tunnel up, health ok) or link.error says why not."""

    def __init__(self, cfg: Any, sleep: Callable[[float], object] = time.sleep) -> None:
        a = cfg.section("agentmemory")
        self.client: AgentMemoryClient | None = None
        self.error = ""
        self.names = {str(k): str(v) for k, v in dict(a.get("projects", {})).items()}
        self._tunnel: Tunnel | None = None
        self._sleep = sleep
        port = int(a.get("local_port", 13111))
        try:
            self.client = AgentMemoryClient(f"http://127.0.0.1:{port}", cfg.env(AM_ENV_VAR))
            self._tunnel = Tunnel(str(a.get("host", "")), port, int(a.get("remote_port", 3111)), str(a.get("key_file", "")),
                                  str(a.get("user", "")), check=self.client.health)
        except ValueError as exc:
            self.client, self.error = None, f"agentmemory tunnel settings are wrong: {exc}"

    def __enter__(self) -> Self:
        if self._tunnel is not None and self.client is not None:
            self._tunnel.start()
            deadline = time.monotonic() + TUNNEL_WAIT_SEC
            while not self.client.health():
                if time.monotonic() > deadline:
                    self.error = f"agentmemory did not answer in {TUNNEL_WAIT_SEC:.0f} s: {self._tunnel.last_error}"
                    self.client = None
                    break
                self._sleep(1.0)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._tunnel is not None:
            self._tunnel.stop()
