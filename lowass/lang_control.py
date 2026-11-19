# lowass/lang_control.py
"""What the language dropdowns do: the order of languages for Transcribe and the FROM / TO rule of the translation."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .languages import DEFAULT, TranslateRule

log = logging.getLogger("lowass.lang")


def build_rule(cfg: Any) -> TranslateRule:
    """The start state: `[translate].from_default` into `[translate].to_default` (de-DE into cs-CZ)."""
    t = cfg.section("translate")
    return TranslateRule(default_from=str(t.get("from_default", "de-DE")), default_to=str(t.get("to_default", "cs-CZ")),
                         understood=tuple(t.get("understood", ("cs", "sk", "en"))))


class LanguageControl:
    """One place for both choices. `transcriber` is where the order of languages lives; it does not exist before the
    listener starts (and in `--no-audio`), so a choice made earlier is remembered and applied when it appears."""

    def __init__(self, voice: Any, post: Callable[[str, str], None]):
        self.voice, self.post = voice, post
        self.choice = DEFAULT
        self.transcriber: Any = None
        translator = getattr(voice, "translator", None)
        self.rule = translator.rule if translator is not None and translator.rule is not None else TranslateRule()

    def attach(self, transcriber: Any) -> None:
        """The listener created its Transcriber: give it the choice the user already made."""
        self.transcriber = transcriber
        transcriber.choice = self.choice

    def set_recognition(self, choice: str) -> None:
        self.choice = choice
        if self.transcriber is not None:
            self.transcriber.choice = choice
        log.warning("recognition language: %s", choice)
        self.post("status", "recognition order: default" if choice == DEFAULT else f"recognition: {choice} first")

    def set_translation(self, frm: str, to: str) -> None:
        self.rule = TranslateRule(frm=frm, to=to, default_from=self.rule.default_from, default_to=self.rule.default_to,
                                  understood=self.rule.understood)
        translator = getattr(self.voice, "translator", None)
        if translator is not None:
            translator.rule = self.rule
        log.warning("translation: %s -> %s", self.rule.source if frm != "any" else "any foreign", self.rule.target)
        self.post("status", f"translate {frm if frm != DEFAULT else self.rule.source} -> {self.rule.target}")
