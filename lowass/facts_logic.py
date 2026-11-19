# lowass/facts_logic.py
"""Pure logic of the facts window: how a sheet is shown, when the window opens by itself, where it sits."""
from __future__ import annotations

from dataclasses import dataclass

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
