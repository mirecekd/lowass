# lowass/am_service.py
"""Builds the agentmemory link from lowass.toml and .env and gives the app ONE object to talk to."""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .am_client import AgentMemoryClient
from .am_sync import MemorySync
from .am_tool import make_memory_tool
from .am_tunnel import Tunnel
from .meeting_sink import Sink

log = logging.getLogger("lowass.am")
AM_ENV_VAR = "AGENTMEMORY_SECRET"  # the NAME of the variable in .env; the value is never in the code


class MemoryLink:
    """enabled -> a tunnel, a client, a background sender and a read tool. Not enabled (or no secret) -> a quiet no-op, so the
    rest of the app never has to ask 'is it on?'."""

    def __init__(self, cfg: Any, current_project: Callable[[], str]):
        a = cfg.section("agentmemory")
        self.cfg_enabled = bool(a.get("enabled", False))
        self.names = {str(k): str(v) for k, v in dict(a.get("projects", {})).items()}
        self.sync: MemorySync | None = None
        self.tunnel: Tunnel | None = None
        self.client: AgentMemoryClient | None = None
        self.sink: Sink | None = None
        self._current = current_project
        self._done = threading.Event()
        self._read = bool(a.get("read", True))
        self.problem = ""
        if not self.cfg_enabled:
            return
        secret = cfg.env(AM_ENV_VAR)
        if not secret:
            self.problem = f"agentmemory is on, but {AM_ENV_VAR} is not in .env"
            log.warning(self.problem)
            return
        try:
            port = int(a.get("local_port", 13111))
            self.client = AgentMemoryClient(f"http://127.0.0.1:{port}", secret)
            self.tunnel = Tunnel(str(a.get("host", "")), port, int(a.get("remote_port", 3111)), str(a.get("key_file", "")),
                                 str(a.get("user", "")), check=self.client.health)
            self.sync = MemorySync(self.client, self.names, True, tuple(a.get("exclude", ("private", "testing"))),
                                   int(a.get("outbox_limit", 2000)))
            self.sink = Sink(self.sync.add)
        except ValueError as exc:  # a bad host or port in the config: say it, do not crash the app
            self.problem = f"agentmemory is off: {exc}"
            log.warning(self.problem)
            self.sync = self.tunnel = self.client = self.sink = None

    @property
    def on(self) -> bool:
        return self.sync is not None

    def start(self) -> None:
        if self.tunnel is not None and self.sync is not None:
            self.tunnel.start()
            self.sync.start()
            threading.Thread(target=self._watch, daemon=True, name="am-status").start()

    def _watch(self) -> None:
        """Writes the state to lowass.log whenever it changes (the sent counter is left out, it changes all the time)."""
        last = ""
        while self.sync is not None and not self._done.is_set():
            waiting = "events waiting" if self.sync.status["waiting"] > 0 else "nothing waiting"
            now = f"tunnel {self.tunnel.state if self.tunnel else ''}, {waiting}"
            if now != last:
                log.info("agentmemory: %s", now)
                last = now
            self._done.wait(5)

    def stop(self) -> None:
        self._done.set()
        if self.sync is not None:
            self.sync.stop()
        if self.tunnel is not None:
            self.tunnel.stop()

    def set_private(self, on: bool) -> None:
        if self.sync is not None:
            self.sync.set_private(on)

    def end_meeting(self, session: str, project: str) -> None:
        if self.sync is not None:
            self.sync.end_meeting(session, project)

    def flush(self, timeout: float = 30.0) -> bool:
        """Send what waits, at most `timeout` s. True = all went out (or agentmemory is off); never raises."""
        if self.sync is None:
            return True
        return self.sync.flush(wait_on_failure=False, deadline=time.time() + timeout)

    def reset(self, session: str | None = None) -> None:
        if self.sync is not None:
            self.sync.reset(session)

    def status_text(self) -> str:
        if not self.cfg_enabled:
            return ""
        if self.sync is None or self.tunnel is None:
            return self.problem or "agentmemory is off"
        s = self.sync.status
        return f"agentmemory: tunnel {self.tunnel.state}, {s['waiting']} waiting, {s['sent']} sent"

    def tools(self) -> list:
        """The read tool for the agent; empty when reading is off or the link is not built."""
        if not (self.on and self._read and self.client is not None):
            return []
        return [make_memory_tool(self.client, self._current, self.names, lambda: self.tunnel.state if self.tunnel else "")]
