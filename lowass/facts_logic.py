# lowass/facts_logic.py
"""Pure logic of the facts window: how a sheet is shown, when the window opens by itself, where it sits."""
from __future__ import annotations

from dataclasses import dataclass

from .popup_logic import Rect
from .transcript_logic import place_transcript

HEADINGS = ("NUMBERS", "DATES", "PEOPLE", "AGREED", "OPEN", "CISLA", "TERMINY", "LIDE", "DOMLUVENO", "OTEVRENE")


def sheet_rows(text: str) -> list[tuple[str, str]]:
    """[(tag, line)]: a heading line (NUMBERS, DATES ...) is 'heading', everything else 'line'; blank lines are dropped."""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        word = line.strip().rstrip(":").upper()
        folded = "".join(c for c in word if c.isascii() and c.isalpha())
        out.append(("heading" if folded in HEADINGS and len(word) < 14 else "line", line))
    return out


@dataclass
class OpenOnce:
    """The facts window opens BY ITSELF the first time a meeting has a sheet, then leaves the decision to the user:
    closing it keeps it closed until the Facts button, Clear or a project switch (a new meeting) re-arms it."""

    armed: bool = True

    def should_open(self, sheet: str) -> bool:
        if self.armed and sheet.strip():
            self.armed = False
            return True
        return False

    def rearm(self) -> None:
        self.armed = True


def place_facts(main: Rect, card_w: int, transcript_w: int, w: int, h: int, screen_w: int, screen_h: int,
                transcript_open: bool, gap: int = 8, taskbar: int = 48) -> tuple[int, int]:
    """Left of the hint card; when the transcript window is open too, to the left of THAT one. Kept on the screen."""
    base_w = card_w + (transcript_w + gap if transcript_open else 0)
    x, y = place_transcript(main, base_w, w, h, screen_w, screen_h, gap, taskbar)
    return x, y
