# lowass/transcript.py
"""Rolling, thread-safe conversation transcript. Never shown in the UI."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class Line:
    ts: float
    speaker: str
    text: str


class Transcript:
    def __init__(self, window_minutes: float = 6.0):
        self._lines: list[Line] = []
        self._lock = threading.Lock()
        self._window = window_minutes * 60.0
        self._mark = 0  # absolute count of lines already handed to the auto agent
        self._dropped = 0

    def clear(self) -> None:
        with self._lock:
            self._lines, self._mark, self._dropped = [], 0, 0

    def add(self, speaker: str, text: str, ts: float | None = None) -> None:
        with self._lock:
            self._lines.append(Line(ts if ts is not None else time.time(), speaker, text))
            self._trim()

    def _trim(self) -> None:
        cutoff = time.time() - self._window
        while self._lines and self._lines[0].ts < cutoff:
            self._lines.pop(0)
            self._dropped += 1

    @staticmethod
    def _fmt(lines: list[Line]) -> str:
        return "\n".join(f"[{time.strftime('%H:%M:%S', time.localtime(x.ts))}] {x.speaker}: {x.text}" for x in lines)

    def window_text(self) -> str:
        with self._lock:
            self._trim()
            return self._fmt(self._lines)

    def _new_lines(self) -> list[Line]:
        start = max(0, self._mark - self._dropped)
        return self._lines[start:]

    def new_words(self) -> int:
        with self._lock:
            return sum(len(x.text.split()) for x in self._new_lines())

    def last_ts(self) -> float:
        with self._lock:
            return self._lines[-1].ts if self._lines else 0.0

    def take_new(self) -> tuple[str, str]:
        """Return (new_text, window_text) and advance the mark."""
        with self._lock:
            self._trim()
            new = self._fmt(self._new_lines())
            window = self._fmt(self._lines)
            self._mark = self._dropped + len(self._lines)
            return new, window
