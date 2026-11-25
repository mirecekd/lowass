# lowass/app.py
"""Wires listener -> transcript/meeting memory -> Flow (agent work) -> window."""
from __future__ import annotations

import logging
import threading

from . import hotkeys
from .am_service import MemoryLink
from .app_audio import make_choice, start_listening
from .app_speaker import start_speaker_names, stop_speaker_watch
from .assist import Assist
from .config import Config
from .controls import Controls
from .debug import Stats, install_excepthook
from .flow import Flow
from .lang_control import LanguageControl
from .memory import make_search_tool, open_meeting
from .session import Session
from .sso_login import LoginManager
from .transcript import Transcript
from .ui_build import build_window
from .voice import build_voice

log = logging.getLogger("lowass.app")


class App:
    def __init__(self, cfg: Config, audio: bool = True):
        a = cfg.section("agent")
        self.cfg, self.use_audio = cfg, audio
        self.transcript = Transcript(a["window_minutes"])
        models, self.model = cfg.models()
        projects, self.project = cfg.project()
        self.session = Session(cfg)
        self.stop = threading.Event()
        self.busy = threading.Lock()
        self.listener = None
        self.stats = Stats()
        self.dbg = cfg.section("debug")
        self.ui = build_window(cfg, self, bool(a["auto"]), models, self.model, projects, self.project)
        self.link = MemoryLink(cfg, lambda: self.project)  # agentmemory: a quiet no-op unless [agentmemory].enabled
        self.meeting = open_meeting(cfg, self.project, lambda m: self.ui.post("err", m), sink=self.link.sink)
        self.session.extra_tools = [make_search_tool(self.meeting.store, lambda: self.project), *self.link.tools()]
        self.flow = Flow(cfg, self.ui.post, self.session, self.transcript, self.meeting, self.stats, self.busy,
                         lambda: "listening" if self.listener else "idle")
        self.login = LoginManager(cfg.section("transcribe")["profile"], self.ui.post)
        self.choice = make_choice(self)  # which project a new meeting belongs to (asked when Private is left)
        self.controls = Controls(cfg, self.ui.post, self.flow, self.login, self._private_changed, self.choice)
        self.ui.bind(self.controls.ask_or_command, self.flow.check_now, self.flow.screen)
        names, self.name_watch = start_speaker_names(cfg)  # (None, None) unless [speaker].enabled
        self.voice = build_voice(cfg, self.ui.post, self.transcript, self.meeting, self.flow.private.muted, self.flow.ask,
                                 names=names)
        self.lang = LanguageControl(self.voice, self.ui.post)
        install_excepthook(self.ui.post)
        self.assist = Assist(cfg, self.flow, self.meeting, self.ui.post, lambda: self.model)
        self.voice.tap = self.assist.tap

    def _private_changed(self, on: bool) -> None:
        """Told by Controls: agentmemory stops/starts sending; leaving Private (Play) signs in to AWS when that is still needed."""
        self.link.set_private(on)
        if not on and self.cfg.section("stt").get("provider") == "transcribe":
            self.login.begin()

    def _translate(self, on: bool) -> None:
        """The Translate button: translate foreign speech only while it is on."""
        self.voice.translate_on = on
        self.ui.post("status", "translation on" if on else "translation off: only transcribing")

    def _set_auto(self, value: bool) -> None:
        self.flow.auto = value

    def _end_meeting(self, closed, agent, show: bool = True) -> None:
        def work() -> None:
            self.flow.finish(closed, agent, show)  # the summary is stored (and copied to agentmemory) first
            self.link.end_meeting(closed.sid, closed.project)

        threading.Thread(target=work, daemon=True, name="meeting-end").start()

    def _set_model(self, model: str) -> None:
        self.model = model
        if self.session.agent:
            self.session.agent.set_model(model)
        self.cfg.save_model(model)
        self.ui.post("status", f"model: {model}")

    def switch_project(self, key: str) -> None:
        """Dropdown: connect to the project's mcphub address with its prompt; the old meeting ends."""
        threading.Thread(target=self._switch, args=(key,), daemon=True, name="switch").start()

    def _switch(self, key: str) -> None:
        with self.busy:  # no request may run on a half-swapped session
            self.ui.post("status", f"connecting: {key} ...")
            old = self.session.agent
            try:
                self.session.open(key, self.model)
            except Exception as exc:  # a failed switch keeps the old session, but must be visible
                log.exception("project switch failed")
                self.ui.post("err", f"Cannot connect project '{key}': {type(exc).__name__}: {exc}")
                self.ui.post("project", self.session.project or self.project)
                self.ui.post("status", "not connected" if not self.session.agent else self.flow.idle_status())
                return
            changed = key != self.project
            self.project = key
            if changed:
                self.transcript.clear()
                self.assist.reset()
                self._end_meeting(self.meeting.rotate(key), old)
            self.ui.post("status", f"project: {key}")

    def on_text(self, speaker: str, text: str) -> None:
        """Used by the segment mode (stt.mode or provider groq): one finished sentence at a time."""
        self.voice.final(speaker, text, None)

    def start(self) -> None:
        self.switch_project(self.project)  # first connection runs in the background; the window is usable at once
        threading.Thread(target=self.flow.auto_loop, daemon=True, name="auto").start()
        threading.Thread(target=self.assist.run, daemon=True, name="assist").start()
        self.link.start()
        if self.link.problem:
            self.ui.post("err", self.link.problem)
        if self.dbg.get("enabled"):
            threading.Thread(target=self.stats.heartbeat, daemon=True, name="stats", args=(
                self.ui.post, float(self.dbg.get("stats_interval_sec", 2)), self.stop,
                self.cfg.section("audio")["my_label"], lambda: str(self.transcript.new_words()))).start()
        hotkeys.start(hotkeys.app_bindings(self.cfg.section("hotkeys"), self.cfg.section("hint"), self.flow,
                                           self.controls, self.ui.post))
        if not self.use_audio:
            self.ui.post("status", "idle (no audio)")
            return
        start_listening(self)

    def run(self) -> None:
        self.start()
        try:
            self.ui.run()
        finally:
            self.stop.set()
            self.flow.stop.set()
            self.login.cancel()
            self.voice.close()
            stop_speaker_watch(self.name_watch)
            if self.listener:
                self.listener.close()
            closed = self.meeting.rotate()  # last meeting: summary is written to summary.md (window is gone)
            self.flow.finish(closed, self.session.agent, show=False)
            self.link.end_meeting(closed.sid, closed.project)
            self.link.stop()  # one last flush, bounded; never hangs the exit
            self.session.close()
            self.meeting.store.close()
