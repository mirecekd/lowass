# lowass/facts_logic.py
"""Pure logic of the facts window: how a sheet is shown, when the window opens by itself, where it sits."""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

HEADINGS = ("NUMBERS", "DATES", "PEOPLE", "AGREED", "OPEN", "CISLA", "TERMINY", "LIDE", "DOMLUVENO", "OTEVRENE")
MAX_HEADING = 24  # "OTEVRENE BODY" is fine; a whole sentence in capitals is not a heading


def _fold(text: str) -> str:
    """Upper case without diacritics, letters only: 'Termíny:' -> 'TERMINY'."""
    decomposed = unicodedata.normalize("NFKD", text.upper())
    return "".join(c for c in decomposed if c.isalpha() and not unicodedata.combining(c))


def sheet_rows(text: str) -> list[tuple[str, str]]:
    """[(tag, line)]: a heading line (NUMBERS, DATES, CISLA, TERMINY ... also with diacritics) is 'heading', everything
    else 'line'; blank lines are dropped."""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        word = line.strip().rstrip(":")
        folded = _fold(word)
        known = any(folded == h or folded.startswith(h) and len(folded) <= len(h) + 8 for h in HEADINGS)
        out.append(("heading" if known and len(word) <= MAX_HEADING and not word.startswith("-") else "line", line))
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
