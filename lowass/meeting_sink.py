# lowass/meeting_sink.py
"""The bridge between a finished piece of a meeting and agentmemory: turns what Meeting stored into memlink Events."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from . import memlink
from .memlink import Event

log = logging.getLogger("lowass.sink")

KIND = {"sentence": memlink.SENTENCE, "turn": memlink.TURN, "facts": memlink.FACTS, "summary": memlink.SUMMARY}


class Sink:
    """`Meeting._emit` calls this with (kind, project, session, text, speaker). It numbers the sentences of each meeting (so two
    identical sentences are two different observations) and hands an Event to `add`, which must never block or raise."""

    def __init__(self, add: Callable[[Event], bool]):
        self._add, self._lock, self._seq = add, threading.Lock(), {}

    def __call__(self, kind: str, project: str, session: str, text: str, speaker: str = "") -> None:
        mapped = KIND.get(kind)
        if mapped is None:
            return
        with self._lock:
            self._seq[session] = n = self._seq.get(session, 0) + 1
        try:
            self._add(Event(mapped, project, session, text, speaker=speaker, seq=n))
        except Exception:
            log.warning("could not hand an event to agentmemory", exc_info=True)

    def forget(self, session: str) -> None:
        with self._lock:
            self._seq.pop(session, None)
