# lowass/app.py
"""Wires listener -> transcript/meeting memory -> Flow (agent work) -> window."""
from __future__ import annotations

import logging
import threading

from . import deps, hotkeys
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
        self.meeting = open_meeting(cfg, self.project, lambda m: self.ui.post("err", m))
        self.session.extra_tools = [make_search_tool(self.meeting.store, lambda: self.project)]
        self.flow = Flow(cfg, self.ui.post, self.session, self.transcript, self.meeting, self.stats, self.busy,
                         lambda: "listening" if self.listener else "idle")
        self.login = LoginManager(cfg.section("transcribe")["profile"], self.ui.post)
        self.controls = Controls(cfg, self.ui.post, self.flow, self.login)
        self.ui.bind(self.controls.ask_or_command, self.flow.check_now, self.flow.screen)
        self.voice = build_voice(cfg, self.ui.post, self.transcript, self.meeting, self.flow.private.muted, self.flow.ask)
        self.lang = LanguageControl(self.voice, self.ui.post)
        install_excepthook(self.ui.post)
        self.assist = Assist(cfg, self.flow, self.meeting, self.ui.post, lambda: self.model)
        self.voice.tap = self.assist.tap

    def _translate(self, on: bool) -> None:
        """The Translate button: translate foreign speech only while it is on."""
        self.voice.translate_on = on
        self.ui.post("status", "translation on" if on else "translation off: only transcribing")

    def _set_auto(self, value: bool) -> None:
        self.flow.auto = value

    def _end_meeting(self, closed, agent, show: bool = True) -> None:
        threading.Thread(target=self.flow.finish, args=(closed, agent, show), daemon=True, name="meeting-end").start()

    def clear_context(self) -> None:
        """Clear button: the meeting ends (summary in the window) and the LLM starts from a clean conversation."""
        agent = self.session.agent
        closed = self.meeting.rotate(self.project)
        if agent:
            agent.clear()
        self.transcript.clear()
        self.assist.reset()
        self.ui.post("status", "context cleared")
        self._end_meeting(closed, agent)

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
            self.cfg.save_state(project=key)
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
        if self.dbg.get("enabled"):
            threading.Thread(target=self.stats.heartbeat, daemon=True, name="stats", args=(
                self.ui.post, float(self.dbg.get("stats_interval_sec", 2)), self.stop,
                self.cfg.section("audio")["my_label"], lambda: str(self.transcript.new_words()))).start()
        hotkeys.start(hotkeys.app_bindings(self.cfg.section("hotkeys"), self.cfg.section("hint"), self.flow,
                                           self.controls, self.ui.post))
        if not self.use_audio:
            self.ui.post("status", "idle (no audio)")
            return
        from .listener import Listener
        if self.cfg.section("stt").get("provider") == "transcribe":
            self.login.begin()  # no valid AWS login: the device-code page opens at once, not at the first sentence
        self.listener = Listener(self.cfg, self.on_text, self.stats, lambda msg: self.ui.post("err", msg),
                                 self.login.begin, self.voice, self.flow.private.is_set, self.lang.attach)
        try:
            names = self.listener.start()
            self.ui.post("status", "listening")
            self.ui.post("bot", f"Listening. me: {names[0]} | other: {names[1]}")
        except Exception as exc:  # noqa: BLE001 - audio problems must be visible, chat still works
            self.listener = None
            self.ui.post("err", f"Audio failed: {deps.describe(exc)}. Chat still works.")
            self.ui.post("status", "no audio")

    def run(self) -> None:
        self.start()
        try:
            self.ui.run()
        finally:
            self.stop.set()
            self.flow.stop.set()
            self.login.cancel()
            self.voice.close()
            if self.listener:
                self.listener.close()
            closed = self.meeting.rotate()  # last meeting: summary is written to summary.md (window is gone)
            self.flow.finish(closed, self.session.agent, show=False)
            self.session.close()
            self.meeting.store.close()
