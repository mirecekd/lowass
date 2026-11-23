# lowass/freeze.py
"""Private mode as a FREEZE: what is already running finishes, nothing new is listened to, sent or stored.

Pressing Private sets the gate at once. Capture, the auto loop, hints and the facts loop stop immediately (`is_set`), but
a sentence that was being spoken, its translation and a request that is already with the model still finish and show up.
After `drain_sec` the gate is `muted`: from then on even late results of the transcript path are dropped."""
from __future__ import annotations

import threading
import time
from typing import Any


class PrivateGate(threading.Event):
    def __init__(self, drain_sec: float = 0.0):
        super().__init__()
        self.drain_sec = drain_sec
        self._since = 0.0

    def set(self) -> None:
        if not self.is_set():
            self._since = time.monotonic()
        super().set()

    def start_muted(self) -> None:
        """Private from the very start: nothing was running, so there is nothing to drain; muted at once."""
        super().set()
        self._since = float("-inf")

    def muted(self) -> bool:
        """True once Private is on AND the running work had `drain_sec` to finish. The transcript path asks this."""
        return self.is_set() and time.monotonic() - self._since >= self.drain_sec


def make_gate(cfg: Any) -> PrivateGate:
    """Draining only makes sense for live streaming: the segment mode has no capture gate, so it is muted at once."""
    live = (cfg.section("stt").get("provider", "transcribe") == "transcribe"
            and cfg.section("transcribe").get("mode", "live") == "live")
    return PrivateGate(float(cfg.section("private").get("drain_sec", 10.0)) if live else 0.0)
