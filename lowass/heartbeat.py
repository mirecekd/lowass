# lowass/heartbeat.py
"""Debug heartbeat: pushes the stats rows to the window and the log, and warns about a dead microphone."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger("lowass.debug")


def run_heartbeat(stats: Any, post: Callable[[str, str], None] | None, interval: float, stop: threading.Event,
                  my_label: str, extra: Callable[[], str], warn_after: float = 10.0) -> None:
    """Every `interval` s: stats rows to the window, every ~10 s to the log. The 'no audio' warning counts from the
    moment the capture of `my_label` is REGISTERED (the audio may open long after the app started: counting from the
    start gave a false 'No audio after 10 s' before any device was open)."""
    n, warned_none, warned_flat = 0, False, False
    every = max(1, int(10 / interval))
    armed_at: float | None = None
    while not stop.wait(interval):
        n += 1
        rows = stats.rows(extra())
        if post:
            post("stats", "\n".join(f"{level}|{text}" for level, text in rows))
        if n % every == 0:
            log.info("stats: %s", " | ".join(text for _level, text in rows))
        opened, chunks, peak = stats.mic_state(my_label)
        if not opened:
            continue  # no capture yet: nothing to warn about
        now = n * interval
        armed_at = now if armed_at is None else armed_at
        elapsed = now - armed_at
        msg = ""
        if elapsed >= warn_after and chunks == 0 and not warned_none:
            warned_none = True
            msg = (f"No audio from '{my_label}' after {warn_after:.0f} s: wrong default input device, or Windows "
                   "microphone privacy setting blocks desktop apps.")
        elif elapsed >= warn_after * 1.5 and chunks > 0 and peak == 0.0 and not warned_flat:
            warned_flat = True
            msg = f"'{my_label}' delivers only digital silence (muted or wrong device?)."
        if msg:
            log.error(msg)
            if post:
                post("err", msg)
