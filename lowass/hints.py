# lowass/hints.py
"""Pure decision logic: when to offer a suggested answer to an unanswered question."""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger("lowass.hints")

# Normalized (lowercase, no diacritics) openers of a request addressed to the user.
REQUEST_OPENERS: tuple[str, ...] = (
    "mohl bys",
    "muzes",
    "could you",
    "can you",
    "kannst du",
    "what do you think",
    "co si myslis",
)

# A user sentence with at least this many words counts as an answer.
MIN_ANSWER_WORDS = 3


@dataclass
class Pending:
    speaker: str
    text: str
    asked_at: float


def _normalize(text: str) -> str:
    """Lowercase, strip diacritics and collapse whitespace."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(stripped.split())


def name_pattern(name: str) -> re.Pattern[str]:
    """A first name as people say it in Czech: the name and its case forms. The endings are an explicit short list, NOT
    'any 3 letters': that wrongly matched surnames ('Miroslavsky', 'Mironov').
      Miroslav -> Miroslav, Miroslave, Miroslava, Miroslavu, Miroslavovi, Miroslavem
      Mirek    -> Mirek, Mirku, Mirka, Mirkovi, Mirkem (the -ek drops its 'e' before an ending)
      Miro     -> Miro, Mira, Mirovi, Mirem
    Whole words only. A name that is not listed here simply matches exactly."""
    forms = {name}
    if name.endswith("ek") and len(name) >= 4:  # Mirek -> Mirk-u / -a / -ovi / -em (and the pet form Mirecek -> Mirecku)
        stem = name[:-2] + "k"
        forms |= {stem + e for e in ("u", "a", "ovi", "em", "y")}
    else:
        forms |= {name + e for e in ("e", "a", "u", "ovi", "em", "ovi")}
        if name.endswith("o"):  # Miro -> Mira, Mirovi, Mirem (the o is the ending: Mir-ovi, Mir-a, Mir-em)
            forms |= {name[:-1] + e for e in ("a", "em", "ovi", "u")}
    alternatives = "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)")


class HintWatcher:
    def __init__(
        self,
        my_label: str,
        names: list[str],
        wait_sec: float = 12.0,
        cooldown_sec: float = 45.0,
        max_age_sec: float = 90.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._my_label = my_label
        self._name_patterns = [name_pattern(normalized) for normalized in (_normalize(n) for n in names) if normalized]
        self._wait_sec = wait_sec
        self._cooldown_sec = cooldown_sec
        self._max_age_sec = max_age_sec
        self._clock = clock
        self._pending: Pending | None = None
        self._delivered = False
        self._last_handled: float | None = None

    def heard(self, speaker: str, text: str) -> None:
        """Feed every final sentence of either side, in order."""
        stripped = text.strip()
        if not stripped:
            return
        if speaker == self._my_label:
            if len(stripped.split()) >= MIN_ANSWER_WORDS:
                self._pending = None
                self._delivered = False
            return
        if self._is_candidate(stripped):
            self._pending = Pending(speaker, stripped, self._clock())
            self._delivered = False
            log.info("hint: a question for you is pending (%s): %s", speaker, stripped[:100])

    def due(self) -> Pending | None:
        """Return the question to ask about once, or None."""
        pending = self._pending
        if pending is None or self._delivered:
            return None
        now = self._clock()
        age = now - pending.asked_at
        if age >= self._max_age_sec:
            self._pending = None
            return None
        if age <= self._wait_sec:
            return None
        if self._last_handled is not None and now - self._last_handled <= self._cooldown_sec:
            return None
        self._delivered = True
        return pending

    def reset(self) -> None:
        """A new meeting: forget the pending question and the cooldown."""
        self._pending = None
        self._delivered = False
        self._last_handled = None

    def handled(self) -> None:
        """The caller used the question: drop it and start the cooldown."""
        self._pending = None
        self._delivered = False
        self._last_handled = self._clock()

    def _is_candidate(self, text: str) -> bool:
        if text.endswith("?"):
            return True
        normalized = _normalize(text)
        if normalized.startswith(REQUEST_OPENERS):
            return True
        return any(pattern.search(normalized) for pattern in self._name_patterns)
