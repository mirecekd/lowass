# lowass/wake.py
"""Wake phrase detection: at the start of a sentence (also after a lead-in word) or at its end."""

import re
import unicodedata

MIN_FUZZY_LENGTH = 4
MAX_SPLIT = 3  # a phrase word may come out of the speech recogniser as up to this many words ("Tose" -> "to se")
MAX_LEAD = 2  # at most this many lead-in words before the phrase ("hej hele Jarvis")
LEAD_INS = ("hey", "hej", "hele", "ty", "kámo")
_WORD = re.compile(r"\w+")


def _fold(word: str) -> str:
    """Lowercase a word and drop diacritics."""
    decomposed = unicodedata.normalize("NFKD", word.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _words(text: str) -> tuple[str, ...]:
    return tuple(_fold(w) for w in _WORD.findall(unicodedata.normalize("NFC", text)))


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
    """`lead_ins`: words that may come before the phrase ("hele Jarvis, ..."). `start_only`: phrases that count only at
    the START (also after a lead-in), not at the end of a sentence: for a phrase that is also an ordinary word
    ("I will send it on Friday") the end of a sentence would wake the assistant by accident."""

    def __init__(self, phrases: list[str], max_edit: int = 1, lead_ins: tuple[str, ...] | list[str] = LEAD_INS,
                 start_only: tuple[str, ...] | list[str] = ()) -> None:
        self._max_edit = max_edit
        self._lead = {w for item in lead_ins for w in _words(item)}
        only = {_words(p) for p in start_only}
        self._phrases = [(words, words in only) for words in (_words(p) for p in phrases) if words]

    def _word_matches(self, expected: str, actual: str, pieces: int = 1) -> bool:
        if len(expected) < MIN_FUZZY_LENGTH:
            return expected == actual
        # a word glued together from several pieces must match exactly: with one typo allowed on top of the gluing
        # 'Samo to je' (= 'tojé') would wake the assistant by accident
        return _edit_distance(expected, actual) <= (self._max_edit if pieces == 1 else 0)

    def _match_from(self, phrase: tuple[str, ...], words: list[str], pos: int, index: int) -> int | None:
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
        """The question of a sentence that wakes the assistant, or None. '' = only the phrase was said (wait for the next
        sentence). Start: 'Jarvis, what now?' and 'hele Jarvis, what now?' give 'what now?'. End: 'What now, Jarvis?' gives
        'What now'."""
        text = unicodedata.normalize("NFC", text)
        matches = list(_WORD.finditer(text))
        words = [_fold(m.group()) for m in matches]
        for phrase, start_only in self._phrases:
            for skip in range(MAX_LEAD + 1):
                if skip and (skip > len(words) or words[skip - 1] not in self._lead):
                    break
                used = self._match_from(phrase, words, skip, 0)
                if used:
                    return re.sub(r"^[\W_]+", "", text[matches[skip + used - 1].end():])
            if start_only:
                continue
            for pos in range(1, len(words)):
                used = self._match_from(phrase, words, pos, 0)
                if used and pos + used == len(words):  # the phrase is the LAST thing said
                    before = re.sub(r"[\W_]+$", "", text[:matches[pos].start()])
                    if before:
                        return before
        return None
