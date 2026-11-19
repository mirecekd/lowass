# lowass/session.py
"""One live agent session (project + model): the Strands agent and its mcphub connection."""
from __future__ import annotations

import logging

from .agent import Agent
from .build import build_agent
from .config import Config

log = logging.getLogger("lowass.session")


class Session:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.agent: Agent | None = None
        self.project = ""
        self.extra_tools: list = []  # local tools given to every agent (meeting search)
        self._mcp = None

    def open(self, project: str, model: str) -> None:
        """Connect the new project first, then swap. If it fails the previous session stays untouched."""
        agent, mcp = build_agent(self.cfg, project, model, self.extra_tools)
        old, self._mcp = self._mcp, mcp
        self.agent, self.project = agent, project
        self._stop(old)
        log.info("session open: project=%s model=%s", project, model)

    def close(self) -> None:
        old, self._mcp, self.agent = self._mcp, None, None
        self._stop(old)

    @staticmethod
    def _stop(mcp) -> None:
        if mcp is not None:
            try:
                mcp.stop(None, None, None)
            except Exception as exc:  # noqa: BLE001 - a broken old connection must not block the switch
                log.debug("mcp stop: %r", exc)
