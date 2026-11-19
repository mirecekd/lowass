# lowass/facts.py
"""Incremental rolling summary / facts sheet of a meeting."""
from __future__ import annotations

import threading
from collections.abc import Callable


class FactsSheet:
    """Keeps a short facts sheet; each update sends only the new text plus the previous sheet."""

    def __init__(self, complete: Callable[[str, str], str], prompt: str,
                 min_new_words: int = 60, max_chars: int = 3500):
        self._complete = complete
        self._prompt = prompt
        self._min_new_words = min_new_words
        self._max_chars = max_chars
        self._lock = threading.Lock()
        self._buffer_lock = threading.Lock()  # feed() must not wait for a running LLM call
        self._buffer: list[str] = []
        self.text = ""

    def feed(self, new_text: str) -> None:
        if new_text.strip():
            with self._buffer_lock:
                self._buffer.append(new_text.strip())

    def due(self) -> bool:
        with self._buffer_lock:
            return sum(len(part.split()) for part in self._buffer) >= self._min_new_words

    def update(self) -> bool:
        with self._lock:
            with self._buffer_lock:
                taken = list(self._buffer)
            if not taken:
                return False
            new_text = "\n".join(taken)
            user = f"PREVIOUS SHEET:\n{self.text or '(empty)'}\n\nNEW TRANSCRIPT:\n{new_text}"
            try:
                answer = self._complete(self._prompt, user).strip()
            except Exception:  # noqa: BLE001 - any failed call keeps the old sheet and the buffer
                return False
            with self._buffer_lock:
                del self._buffer[:len(taken)]  # keep text fed while the call was running
            if not answer or answer == "NOTHING":
                return False
            sheet = self._cut(answer)
            changed = sheet != self.text
            self.text = sheet
            return changed

    def reset(self) -> None:
        with self._lock:
            with self._buffer_lock:
                self._buffer.clear()
            self.text = ""

    def _cut(self, text: str) -> str:
        if len(text) <= self._max_chars:
            return text
        head = text[:self._max_chars]
        if text[self._max_chars] == "\n":
            return head.rstrip()
        cut = head.rfind("\n")
        return head[:cut].rstrip() if cut > 0 else head.rstrip()
