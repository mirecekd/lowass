# lowass/review.py
"""`/load`: look at an OLDER meeting, READ-ONLY. Nothing is written, nothing is sent to agentmemory, the live meeting and the
agent's memory stay untouched. While a meeting is loaded the shortcut buttons and typed questions work over ITS text."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import view
from .memory import data_dir
from .summary import build_prompt

log = logging.getLogger("lowass.review")
HELP = "/load = list the meetings of this project, /load all = every project, /load 3 or /load <id> = open one, /unload = back."
RULE = ("This is an OLDER, finished meeting, loaded only for review. Answer from its text; do not mix it with the meeting that "
        "is running now. Nothing you say is stored.")


class Review:
    def __init__(self, cfg: Any, post: Callable[[str, str], None], flow: Any):
        self.cfg, self.post, self.flow = cfg, post, flow
        self.viewer = view.Viewer()

    @property
    def active(self) -> bool:
        return self.viewer.loaded is not None

    def _root(self) -> Path:
        return data_dir(self.cfg)

    def command(self, text: str) -> bool:
        """True when `text` was a /load or /unload command (and has been handled)."""
        words = text.strip().split()
        if not words or words[0].lower() not in ("/load", "/unload"):
            return False
        if words[0].lower() == "/unload":
            self.viewer.unload()
            self.post("status", self.flow.idle_status())
            self.post("bot", "Back to the running meeting.")
            return True
        arg = " ".join(words[1:])
        if not arg or arg.lower() == "all":
            self._list(None if arg else self.flow.session.project)
        else:
            self._open(arg)
        return True

    def _list(self, project: str | None) -> None:
        items = view.recent(self._root(), project)
        self.viewer.listing = items
        if not items:
            self.post("err", "No stored meeting found" + (f" for project '{project}'." if project else "."))
            return
        self.post("bot", "Older meetings (newest first):\n" + "\n".join(view.describe(m, i) for i, m in enumerate(items, 1))
                  + f"\n\n{HELP}")

    def _open(self, ref: str) -> None:
        if not self.viewer.listing:
            self.viewer.listing = view.recent(self._root(), None, 200)  # /load <id> without a list: look in all of them
        m = view.resolve(self.viewer.listing, ref)
        if m is None:
            self.post("err", f"No unique meeting for '{ref}'. {HELP}")
            return
        self.viewer.load(m)
        self.post("status", f"VIEWING {m.sid} (read-only): buttons and questions use THAT meeting, /unload to leave")
        self.post("bot", f"Loaded {m.project} {m.sid}, {m.lines} lines. Press Summary or ask. Nothing is written or sent.")

    def run(self, prompt: str, label: str) -> None:
        """A request over the loaded meeting: one stateless agent call, shown in the log, stored nowhere."""
        m = self.viewer.loaded
        if m is None:
            return
        body = view.text(m)
        if not body.strip():
            self.post("err", f"[{label}] this meeting has no text.")
            return
        name = self.cfg.projects().get(m.project, {}).get("name", m.project)
        full = f"{RULE}\n\n{build_prompt(prompt, name, body)}"
        threading.Thread(target=self._call, args=(full, label), daemon=True, name="review").start()

    def _call(self, prompt: str, label: str) -> None:
        flow = self.flow
        if not flow.busy.acquire(timeout=float(self.cfg.section("agent").get("queue_wait_sec", 60))):
            self.post("err", "Still working on the previous request.")
            return
        try:
            agent = flow.session.agent
            if agent is None:
                self.post("err", "Not connected to mcphub. Pick the project again or check the log.")
                return
            self.post("you", f"[{label}] (loaded)")
            self.post("status", "working on the loaded meeting...")
            self.post("bot", agent.run(prompt, "", remember=False))  # remember=False: the agent's history is not touched
        except Exception as exc:  # shown, never raised into the UI thread
            log.exception("review failed")
            self.post("err", f"{type(exc).__name__}: {exc}")
        finally:
            flow.busy.release()
            loaded = self.viewer.loaded
            self.post("status", f"VIEWING {loaded.sid} (read-only)" if loaded else flow.idle_status())
