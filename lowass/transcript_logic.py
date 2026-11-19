# lowass/transcript_logic.py
"""Pure logic of the transcript window: lines per speaker and the translation hanging under the final line."""
from __future__ import annotations

from dataclasses import dataclass, field

from .ui_parts import pick_line


@dataclass
class Entry:
    speaker: str
    text: str = ""
    final: bool = False
    translation: str = ""


@dataclass
class TranscriptLines:
    """One open (partial) entry per speaker, finished entries stay; the translation hangs under the last final one."""

    keep: int = 200
    entries: list[Entry] = field(default_factory=list)
    _open: dict[str, Entry] = field(default_factory=dict)
    _last_final: dict[str, Entry] = field(default_factory=dict)

    def update(self, speaker: str, state: str, text: str) -> None:
        if state not in ("partial", "final"):
            return
        entry = self._open.get(speaker)
        if entry is None:
            entry = Entry(speaker)
            self.entries.append(entry)
            self._open[speaker] = entry
        entry.text = text
        if state == "final":
            del self._open[speaker]
            entry.final = True
            if text.strip():
                self._last_final[speaker] = entry
            else:
                self.entries.remove(entry)
        del self.entries[:-self.keep]

    def translate(self, speaker: str, text: str, source: str = "") -> None:
        entry = pick_line(self.entries, speaker, source, self._last_final.get(speaker))
        if isinstance(entry, Entry):
            entry.translation = text

    def clear(self) -> None:
        self.entries.clear()
        self._open.clear()
        self._last_final.clear()
