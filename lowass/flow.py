# lowass/flow.py
"""Everything that talks to the agent: chat, fact-check, auto mode, screenshot, meeting summary.

App wires the pieces together; Flow does the work and writes every turn into the meeting memory.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from .agent import NOTHING
from .config import Config
from .debug import Stats
from .freeze import make_gate
from .meeting import Closed, Meeting, meeting_text
from .screen import grab_primary
from .session import Session
from .summary import build_prompt, summarise, worth_summarising
from .transcript import Transcript

log = logging.getLogger("lowass.flow")
Post = Callable[[str, str], None]
QUIET = ("auto", "hint")  # started by the assistant itself: silenced in Private mode, never reports "busy"


class Flow:
    def __init__(self, cfg: Config, post: Post, session: Session, transcript: Transcript, meeting: Meeting,
                 stats: Stats, busy: threading.Lock, idle_status: Callable[[], str]):
        self.cfg, self.post, self.session = cfg, post, session
        self.transcript, self.meeting, self.stats, self.busy = transcript, meeting, stats, busy
        self.idle_status = idle_status
        self.auto = bool(cfg.section("agent")["auto"])
        self.stop = threading.Event()
        self.private = make_gate(cfg)  # set = Private (a freeze): nothing new is listened to, sent or stored; running work finishes
        self.dbg = cfg.section("debug")
        self.extra_context: Callable[[], str] = lambda: ""  # e.g. the facts sheet, put before the recent transcript

    def _heard(self, text: str) -> None:
        if self.dbg.get("enabled") and self.dbg.get("show_transcript"):
            self.post("heard", text)

    def work(self, prompt: str, shown: str | None, tag: str, remember: bool = True, image: bytes | None = None,
             deliver: Callable[[str], None] | None = None) -> None:
        """One agent request. tag: bot (chat, fact-check, screenshot) | auto | hint. Private mode silences `auto` and
        `hint` only: a request you type or click yourself is an explicit act and still runs. `deliver` gets the answer
        instead of the log (the hint card)."""
        if tag in QUIET and self.private.is_set():
            return
        if not self.busy.acquire(blocking=False):
            if tag not in QUIET:
                self.post("err", "Still working on the previous request.")
            return
        try:
            agent = self.session.agent
            if agent is None:
                self.post("err", "Not connected to mcphub. Pick the project again or check the log.")
                return
            if shown:
                self.post("you", shown)
            self.post("status", "working...")
            shot = None
            if image is not None:
                shot = self.meeting.screen_path()
                shot.write_bytes(image)  # saved first: the screenshot belongs to the meeting even if the agent fails
            facts = self.extra_context()
            context = (f"FACTS SO FAR:\n{facts}\n\n" if facts else "") + self.transcript.window_text()
            answer = agent.run(prompt, context, lambda s: self.post("status", s), remember, image)
            quiet = answer.strip() in ("", NOTHING)
            self.stats.agent_result("quiet" if quiet else "answer")
            if not quiet:
                if deliver is not None:
                    deliver(answer.strip())
                else:
                    self.post("auto" if tag == "auto" else "bot", answer)
            elif tag == "auto":
                self._heard("[auto] checked, nothing to report")
            if not quiet or shot:
                role = tag if tag in QUIET else ("screen" if shot else "assistant")
                self.meeting.turn("" if tag in QUIET else (shown or ""), answer if not quiet else "(no comment)", role, shot)
            self.post("status", self.idle_status())
        except Exception as exc:
            log.exception("request failed")
            self.stats.agent_result("err")
            self.stats.last_err = f"agent {type(exc).__name__}: {exc}"[:120]
            self.post("err", f"{type(exc).__name__}: {exc}")
            self.post("status", "error")
        finally:
            self.busy.release()

    def _bg(self, **kw) -> None:
        threading.Thread(target=self.work, kwargs=kw, daemon=True, name="agent-req").start()

    def ask(self, text: str) -> None:
        self._bg(prompt=text, shown=text, tag="bot")

    def shortcut(self, prompt: str, label: str) -> None:
        """A button under the log: its prompt runs over the WHOLE meeting so far (not only the recent minutes)."""
        text = meeting_text(self.meeting.path)
        if not text.strip():
            self.post("err", f"[{label}] nothing has been said or asked in this meeting yet.")
            return
        self._bg(prompt=build_prompt(prompt, self.cfg.projects().get(self.session.project, {}).get("name", ""), text),
                 shown=f"[{label}]", tag="bot", remember=False)

    def check_now(self) -> None:
        self.transcript.take_new()  # the auto loop must not repeat what this check covers
        self._bg(prompt=self.cfg.section("prompts")["check"], shown="[fact-check]", tag="bot", remember=False)

    def screen(self) -> None:
        """Screenshot of the primary monitor -> saved to the meeting -> sent to the agent. The window is already hidden."""
        def run() -> None:
            png = None
            try:
                png = grab_primary(int(self.cfg.section("memory").get("screen_max_side", 1568)))
            except Exception:
                log.exception("screenshot failed")
                self.post("err", "Screenshot failed (see the log).")
            finally:
                self.post("unhide", "")
            if png:
                self.work(self.cfg.section("prompts")["screen"], "[screenshot]", "bot", True, png)

        threading.Thread(target=run, daemon=True, name="screenshot").start()

    def auto_loop(self) -> None:
        a = self.cfg.section("agent")
        while not self.stop.wait(1.0):
            if not self.auto or self.private.is_set() or self.busy.locked():
                continue
            if self.transcript.new_words() < a["min_new_words"]:
                continue
            if time.time() - self.transcript.last_ts() < a["quiet_sec"]:
                continue
            new, _window = self.transcript.take_new()
            log.debug("auto trigger: %d chars of new transcript", len(new))
            self.work(f"{self.cfg.section('prompts')['auto']}\n\nNEW PART:\n{new}", None, "auto", remember=False)

    def finish(self, closed: Closed, agent, show: bool = True) -> None:
        """Summary of a closed meeting (shown in the window), then the slow store/embedding part."""
        summary = ""
        try:
            if (self.cfg.section("memory").get("summary_on_end", True) and agent is not None
                    and worth_summarising(closed.lines)):
                self.post("status", "summarising the meeting...")
                name = self.cfg.projects().get(closed.project, {}).get("name", closed.project)
                summary = summarise(agent, self.cfg.section("prompts")["summary"], name, meeting_text(closed.path))
                if summary and show:
                    self.post("bot", f"[summary {closed.sid}]\n{summary}")
        except Exception:
            log.exception("summary failed")
            self.post("err", "Summary failed (see the log). The transcript and chat are saved.")
        try:
            self.meeting.finish(closed, summary)
        except Exception:
            log.exception("storing the meeting failed")
            self.post("err", "Storing the meeting in the memory failed (see the log). The files are saved.")
        self.post("status", self.idle_status())
