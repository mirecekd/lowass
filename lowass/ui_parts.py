# lowass/ui_parts.py
"""Pure helpers of the floating window (no tkinter, tested offline): button wrapping, caption state and parsing."""
from __future__ import annotations

PARTIAL_COLOR, FINAL_COLOR, TRANSLATION_COLOR = "#8a8a8a", "#e6e6e6", "#4fc1ff"
PRIVATE_COLOR, BACKGROUND = "#c0392b", "#1e1e1e"


def flow_rows(labels: list[str], width_px: int, char_px: int, pad_px: int = 2) -> list[list[int]]:
    """Label indices per row; a new row starts when the next button would not fit. A too wide label gets its own row."""
    rows: list[list[int]] = []
    used = 0
    for i, label in enumerate(labels):
        need = len(label) * char_px + 2 * pad_px + 2 * 2 + 2  # text + padding + border + gap
        if not rows or used + need > width_px:
            rows.append([])
            used = 0
        rows[-1].append(i)
        used += need
    return rows


def parse_caption(text: str) -> tuple[str, str, str]:
    """'Speaker<TAB>partial|final<TAB>text' -> (speaker, state, text); malformed input gives empty strings."""
    parts = text.split("\t", 2)
    if len(parts) != 3 or not parts[0] or parts[1] not in ("partial", "final"):
        return "", "", ""
    return parts[0], parts[1], parts[2]


def parse_translation(text: str) -> tuple[str, str]:
    """'Speaker<TAB>translation' -> (speaker, translation); malformed input gives empty strings."""
    parts = text.split("\t", 1)
    if len(parts) != 2 or not parts[0]:
        return "", ""
    return parts[0], parts[1]


class Captions:
    """Live transcript lines: one open (partial) line per speaker, translations under the last final line."""

    def __init__(self, max_lines: int = 4):
        self.max_lines = max_lines
        self._lines: list[dict] = []  # {'speaker', 'text', 'state', 'translation'}
        self._open: dict[str, dict] = {}
        self._last_final: dict[str, dict] = {}

    def update(self, speaker: str, state: str, text: str) -> None:
        if state not in ("partial", "final"):
            return
        line = self._open.get(speaker)
        if line is None:
            line = {"speaker": speaker, "text": "", "state": state, "translation": ""}
            self._lines.append(line)
            self._open[speaker] = line
        line["text"], line["state"] = text, state
        if state == "final":
            del self._open[speaker]
            if text.strip():
                self._last_final[speaker] = line
            else:
                self._lines.remove(line)
        del self._lines[:-self.max_lines]  # every line shows as at least one row, older ones are never visible

    def translation(self, speaker: str, text: str) -> None:
        line = self._last_final.get(speaker)
        if line is not None:
            line["translation"] = text

    def rows(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for line in self._lines:
            out.append((line["state"], f"{line['speaker']}: {line['text']}"))
            if line["translation"]:
                out.append(("translation", f"-> {line['translation']}"))
        return out[-self.max_lines:]

    def clear(self) -> None:
        self._lines.clear()
        self._open.clear()
        self._last_final.clear()
