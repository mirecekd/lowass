# lowass/wake.py
"""Wake phrase detection on the start of a transcribed sentence."""

import re
import unicodedata

MIN_FUZZY_LENGTH = 4
MAX_SPLIT = 3  # a phrase word may come out of the speech recogniser as up to this many words ("Tose" -> "to se")
_WORD = re.compile(r"\w+")


def _fold(word: str) -> str:
    """Lowercase a word and drop diacritics."""
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


class WakeWords:
    def __init__(self, phrases: list[str], max_edit: int = 1) -> None:
        self._max_edit = max_edit
        folded = (
            [_fold(w) for w in _WORD.findall(unicodedata.normalize("NFC", p))]
            for p in phrases
        )
        self._phrases = [words for words in folded if words]

    def _word_matches(self, expected: str, actual: str, pieces: int = 1) -> bool:
        if len(expected) < MIN_FUZZY_LENGTH:
            return expected == actual
        # a word glued together from several pieces must match exactly: with one typo allowed on top of the gluing
        # 'Samo to je' (= 'tojé') would wake the assistant by accident
        return _edit_distance(expected, actual) <= (self._max_edit if pieces == 1 else 0)

    def _match_from(self, phrase: list[str], words: list[str], pos: int, index: int) -> int | None:
        """Number of text words used when phrase[index:] matches words[pos:], or None. A phrase word may be spelled as
        one word or split into up to MAX_SPLIT words glued together: 'Tose' = 'to se' (a real Transcribe output)."""
        if index == len(phrase):
            return 0
        for take in range(1, MAX_SPLIT + 1):
            if pos + take > len(words):
                break
            if not self._word_matches(phrase[index], "".join(words[pos:pos + take]), take):
                continue
            rest = self._match_from(phrase, words, pos + take, index + 1)
            if rest is not None:
                return take + rest
        return None

    def strip(self, text: str) -> str | None:
        """Return the text after a leading wake phrase, or None if absent."""
        text = unicodedata.normalize("NFC", text)
        matches = list(_WORD.finditer(text))
        words = [_fold(m.group()) for m in matches]
        for phrase in self._phrases:
            used = self._match_from(phrase, words, 0, 0)
            if used:
                rest = text[matches[used - 1].end():]
                return re.sub(r"^[\W_]+", "", rest)
        return None
