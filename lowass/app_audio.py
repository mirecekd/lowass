# lowass/app_audio.py
"""Starting the listener, either listening at once or PAUSED (`[private].start_on`: Private is on until you press Play)."""
from __future__ import annotations

import logging
from typing import Any

from . import deps

log = logging.getLogger("lowass.app")


def start_listening(app: Any) -> None:
    from .listener import Listener

    paused = bool(app.cfg.section("private").get("start_on", False))
    if paused:  # BEFORE the listener exists, so not a single sentence is captured; the AWS login waits for Play
        app.flow.private.start_muted()
        app.controls.set_private(True, sync_button=True)
    elif app.cfg.section("stt").get("provider") == "transcribe":
        app.login.begin()  # no valid AWS login: the device-code page opens at once, not at the first sentence
    app.listener = Listener(app.cfg, app.on_text, app.stats, lambda msg: app.ui.post("err", msg),
                            app.login.begin, app.voice, app.flow.private.is_set, app.lang.attach)
    try:
        names = app.listener.start()
        if paused:
            app.ui.post("status", "PRIVATE: paused at start, press Private to listen")
            app.ui.post("bot", "Paused (Private is on). Press Private or Ctrl+Alt+P to start listening.")
            return
        app.ui.post("status", "listening")
        app.ui.post("bot", f"Listening. me: {names[0]} | other: {names[1]}")
    except Exception as exc:  # noqa: BLE001 - audio problems must be visible, chat still works
        app.listener = None
        app.ui.post("err", f"Audio failed: {deps.describe(exc)}. Chat still works.")
        app.ui.post("status", "no audio")
