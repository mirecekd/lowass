# lowass/languages.py
"""Pure language logic: the order of languages Transcribe gets, and which sentences are translated.

Measured on the real service: with identify_multiple_languages the ORDER of `language_options` is a prior for SHORT
sentences (the first language wins), so a short German sentence is labelled Czech when Czech comes first."""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT = "default"  # the entry of both dropdowns that means "as configured"
ANY = "any"  # FROM: translate every language that is not the target


def order_for(choice: str, configured: list[str]) -> list[str]:
    """`choice` 'default' (or unknown) keeps the configured order; a language in the list moves to the FRONT, the rest keep
    their order. A code that is not configured is ignored, so a stale dropdown value can never add a language."""
    if choice == DEFAULT or choice not in configured:
        return list(configured)
    return [choice] + [lang for lang in configured if lang != choice]


def recognition_choices(configured: list[str]) -> list[str]:
    return [DEFAULT, *configured]


def base(code: str | None) -> str:
    """'de-DE' -> 'de'; None or '' -> ''."""
    return (code or "").split("-")[0].lower()


@dataclass(frozen=True)
class TranslateRule:
    """What is translated: sentences of language `frm` into `to`. frm DEFAULT = the configured `default_from` only (de);
    frm ANY = every foreign language (anything that is not `to` and not in `understood`)."""

    frm: str = DEFAULT
    to: str = DEFAULT
    default_from: str = "de-DE"
    default_to: str = "cs-CZ"
    understood: tuple[str, ...] = ("cs", "sk", "en")

    @property
    def source(self) -> str:
        return self.default_from if self.frm == DEFAULT else self.frm

    @property
    def target(self) -> str:
        return self.default_to if self.to == DEFAULT else self.to

    def wants(self, lang: str | None) -> bool:
        """Is a sentence labelled `lang` to be translated? Never into its own language, never without a label."""
        if not lang or base(lang) == base(self.target):
            return False
        if self.frm == ANY:
            return base(lang) not in self.understood
        return base(lang) == base(self.source)


def translate_from_choices(configured: list[str], default_from: str) -> list[str]:
    """FROM dropdown: default (= de only), every configured language, and 'any'."""
    return [DEFAULT, *configured, ANY] if default_from else [DEFAULT, *configured]


def translate_to_choices(configured: list[str]) -> list[str]:
    return [DEFAULT, *configured]
