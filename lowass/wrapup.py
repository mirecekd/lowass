# lowass/wrapup.py
"""End of a meeting: the summary (shown in the window), then the slow store and embedding part."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .meeting import Closed, meeting_text
from .summary import summarise, worth_summarising

log = logging.getLogger("lowass.wrapup")


def finish_meeting(cfg: Any, post: Callable[[str, str], None], meeting: Any, idle_status: Callable[[], str],
                   closed: Closed, agent: Any, show: bool = True) -> None:
    summary = ""
    try:
        if (cfg.section("memory").get("summary_on_end", True) and agent is not None
                and worth_summarising(closed.lines)):
            post("status", "summarising the meeting...")
            name = cfg.projects().get(closed.project, {}).get("name", closed.project)
            summary = summarise(agent, cfg.section("prompts")["summary"], name, meeting_text(closed.path))
            if summary and show:
                post("bot", f"[summary {closed.sid}]\n{summary}")
    except Exception:
        log.exception("summary failed")
        post("err", "Summary failed (see the log). The transcript and chat are saved.")
    try:
        meeting.finish(closed, summary)
    except Exception:
        log.exception("storing the meeting failed")
        post("err", "Storing the meeting in the memory failed (see the log). The files are saved.")
    post("status", idle_status())
