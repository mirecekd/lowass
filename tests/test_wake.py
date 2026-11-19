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


def named():
    return WakeWords(["Jarvis", "Botek", "Friday"], start_only=["Friday"])


def test_lead_in_words_may_come_before_the_phrase():
    w = named()
    for text in ("Hele Jarvis, co myslis?", "hey Jarvis co myslis?", "Hej, Jarvis, co myslis?", "kamo Jarvis, co myslis?",
                 "Ty Jarvis co myslis?", "hej kámo Jarvis, co myslis?"):
        assert w.strip(text) == "co myslis?", text


def test_only_the_listed_lead_ins_and_at_most_two_are_allowed():
    w = named()
    assert w.strip("No a Jarvis, jak to vidis") is None  # 'no' and 'a' are not lead-in words
    assert w.strip("hej hele kamo Jarvis, ahoj") is None  # three lead-ins are too many
    assert WakeWords(["Jarvis"], lead_ins=["slysis"]).strip("slysis Jarvis, ahoj") == "ahoj"  # the list is configurable
    assert WakeWords(["Jarvis"], lead_ins=[]).strip("hele Jarvis, ahoj") is None


def test_the_phrase_at_the_end_of_a_sentence_wakes_it_and_the_question_is_what_came_before():
    w = named()
    assert w.strip("Co myslis, Jarvis?") == "Co myslis"
    assert w.strip("Co myslis o tom, Botek.") == "Co myslis o tom"
    assert w.strip("Jak to vidis ty, Jarvis") == "Jak to vidis ty"


def test_a_name_in_the_middle_of_a_sentence_is_only_a_mention():
    w = named()
    assert w.strip("Myslim, ze Jarvis ma pravdu") is None
    assert w.strip("A pak jsem mu rekl Jarvis ma pravdu a odesel") is None


def test_a_phrase_that_is_an_ordinary_word_counts_only_at_the_start():
    w = named()
    assert w.strip("Pak to posleme Friday") is None  # 'on Friday' must not wake the assistant
    assert w.strip("Friday, what do you think?") == "what do you think?"
    assert w.strip("Hey Friday, what now?") == "what now?"
    assert WakeWords(["Friday"]).strip("Pak to posleme Friday") == "Pak to posleme"  # without start_only it would


def test_a_bare_phrase_still_arms_the_next_sentence():
    w = named()
    assert w.strip("Jarvis") == "" and w.strip("Hele Jarvis.") == ""


def test_the_end_rule_needs_something_before_the_phrase_and_works_for_split_words():
    w = WakeWords(["Tose Samo"])
    assert w.strip("Tose Samo") == ""  # nothing before it: the start rule, an armed phrase
    assert w.strip("Co delame, to se samo") == "Co delame"  # Transcribe split 'Tose' into 'to se'
    assert w.strip("To se stane samo") is None
