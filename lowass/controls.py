# lowass/controls.py
"""User actions that are not agent work: Private mode, configurable shortcut buttons, chat commands, hotkeys."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger("lowass.controls")


class Controls:
    def __init__(self, cfg: Any, post: Callable[[str, str], None], flow: Any, login: Any):
        self.post, self.flow, self.login = post, flow, login
        self.shortcuts = {s["label"]: s for s in cfg.shortcuts()}

    def on_shortcut(self, prompt: str, label: str) -> None:
        """A button under the log. `action = "check"` is the fact-check of the recent conversation; any other
        button runs its own prompt over the WHOLE meeting so far."""
        if self.shortcuts.get(label, {}).get("action") == "check":
            self.flow.check_now()
        else:
            self.flow.shortcut(prompt, label)

    def set_private(self, on: bool, sync_button: bool = False) -> None:
        """Private: nothing is captured, sent, transcribed or stored from the audio, and the assistant makes no automatic
        comments, until it is switched off. A question you type or a button you press still works (your own act)."""
        if on:
            self.flow.private.set()
            self.post("caption_clear", "")
            self.post("status", "PRIVATE: not listening")
        else:
            self.flow.private.clear()
            self.post("status", self.flow.idle_status())
        if sync_button:
            self.post("private", "1" if on else "0")
        log.warning("private mode %s", "ON" if on else "off")

    def toggle_private(self) -> None:
        """The hotkey."""
        self.set_private(not self.flow.private.is_set(), sync_button=True)

    def ask_or_command(self, text: str) -> None:
        """The chat box: `/login` signs in to AWS (device code), anything else goes to the agent."""
        if text.strip().lower() == "/login":
            if not self.login.begin(force=True):
                self.post("err", "An AWS sign-in is already waiting for you in the browser.")
            return
        self.flow.ask(text)
