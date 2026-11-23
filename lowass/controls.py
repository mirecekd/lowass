# lowass/controls.py
"""User actions that are not agent work: Private mode, configurable shortcut buttons, chat commands, hotkeys."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .review import Review

log = logging.getLogger("lowass.controls")


class Controls:
    def __init__(self, cfg: Any, post: Callable[[str, str], None], flow: Any, login: Any, on_private: Callable[[bool], None] | None = None):
        self.post, self.flow, self.login = post, flow, login
        self.review = Review(cfg, post, flow)  # /load: a read-only look at an older meeting
        self.on_private = on_private  # told when Private goes on or off (agentmemory must stop sending at once)
        self.shortcuts = {s["label"]: s for s in cfg.shortcuts()}

    def on_shortcut(self, prompt: str, label: str) -> None:
        """A button under the log. `action = "check"` is the fact-check of the recent conversation; any other
        button runs its own prompt over the WHOLE meeting so far."""
        if self.shortcuts.get(label, {}).get("action") == "check":
            if self.review.active:
                self.post("err", "Fact-check works on the running meeting. /unload first.")
                return
            self.flow.check_now()
        elif self.review.active:
            self.review.run(prompt, label)  # a loaded old meeting: read-only, stored nowhere
        else:
            self.flow.shortcut(prompt, label)

    def set_private(self, on: bool, sync_button: bool = False) -> None:
        """Private is a FREEZE: nothing new is listened to, sent or stored and the assistant makes no automatic comments,
        but what is already running finishes and stays on screen (captions are NOT cleared). A question you type or a
        button you press still works (your own act)."""
        if on:
            self.flow.private.set()
            self.post("status", "PRIVATE: frozen (finishing what was running)")
        else:
            self.flow.private.clear()
            self.post("status", self.flow.idle_status())
        if self.on_private:
            self.on_private(on)
        if sync_button:
            self.post("private", "1" if on else "0")
        log.warning("private mode %s", "ON" if on else "off")

    def toggle_private(self) -> None:
        """The hotkey."""
        self.set_private(not self.flow.private.is_set(), sync_button=True)

    def ask_or_command(self, text: str) -> None:
        """The chat box: `/login` signs in to AWS (device code), `/hint` shows a test card, anything else goes to the agent."""
        if text.strip().lower() == "/hint":
            self.post("hint", "Test\t12\tThis is a test card. It must appear next to this window without taking the keyboard focus.")
            return
        if text.strip().lower() == "/login":
            if not self.login.begin(force=True):
                self.post("err", "An AWS sign-in is already waiting for you in the browser.")
            return
        if self.review.command(text):
            return
        if self.review.active:
            self.review.run(text, text[:30])  # a question about the loaded meeting
            return
        self.flow.ask(text)
