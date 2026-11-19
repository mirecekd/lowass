# tests/test_wake.py
# ruff: noqa: B005  (WakeWords.strip is not str.strip)
import pytest

from lowass.wake import WakeWords

PHRASES = ["Tose Samo", "Samo Seto", "Samo Tose"]


@pytest.fixture
def wake() -> WakeWords:
    return WakeWords(PHRASES)


@pytest.mark.parametrize("phrase", PHRASES)
def test_phrase_with_question_returns_question(wake: WakeWords, phrase: str) -> None:
    assert wake.strip(f"{phrase}, kolik stoji upgrade?") == "kolik stoji upgrade?"


@pytest.mark.parametrize("phrase", PHRASES)
def test_phrase_alone_returns_empty(wake: WakeWords, phrase: str) -> None:
    assert wake.strip(phrase) == ""


def test_case_is_ignored(wake: WakeWords) -> None:
    assert wake.strip("TOSE SAMO kolik je hodin") == "kolik je hodin"


def test_diacritics_are_ignored(wake: WakeWords) -> None:
    assert wake.strip("Tosé Šamo: ahoj") == "ahoj"


def test_punctuation_between_and_after_is_ignored(wake: WakeWords) -> None:
    assert wake.strip("Tose, samo! - co delas?") == "co delas?"


def test_one_character_typo_matches(wake: WakeWords) -> None:
    assert wake.strip("Toze samo, ahoj") == "ahoj"


def test_two_character_typo_does_not_match(wake: WakeWords) -> None:
    assert wake.strip("Tzzz samo ahoj") is None


def test_short_word_must_match_exactly(wake: WakeWords) -> None:
    assert wake.strip("Samo to je dobre") is None


def test_phrase_in_middle_does_not_match(wake: WakeWords) -> None:
    assert wake.strip("Rekl jsem Tose Samo ahoj") is None


def test_empty_text_does_not_match(wake: WakeWords) -> None:
    assert wake.strip("") is None


def test_empty_phrase_list_never_matches() -> None:
    assert WakeWords([]).strip("Tose Samo ahoj") is None


def test_only_empty_entries_never_match() -> None:
    assert WakeWords(["", "  ", "..."]).strip("ahoj") is None


def test_extra_spaces_in_phrase_are_ignored() -> None:
    assert WakeWords(["  Tose    Samo  "]).strip("tose samo ahoj") == "ahoj"


def test_empty_entries_do_not_break_other_phrases() -> None:
    assert WakeWords(["", "Tose Samo"]).strip("Tose Samo ahoj") == "ahoj"


def test_text_shorter_than_phrase_does_not_match(wake: WakeWords) -> None:
    assert wake.strip("Tose") is None


def test_a_word_split_by_the_recogniser_still_wakes(wake: WakeWords) -> None:
    # real Transcribe output for a spoken 'Tose Samo' was 'to se samo'
    assert wake.strip("to se samo, kolik stoji upgrade?") == "kolik stoji upgrade?"
    assert wake.strip("Samo to se kolik") == "kolik"
    assert wake.strip("to se samo") == ""


def test_split_words_are_not_fuzzy_and_ordinary_speech_does_not_wake(wake: WakeWords) -> None:
    assert wake.strip("ale to se samo stalo") is None  # the phrase must be at the START
    assert wake.strip("to se") is None
    assert wake.strip("Samo to je dobre") is None  # 'to je' would be 'toje', one typo away from 'tose': must NOT match
