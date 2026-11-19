# tests/test_languages.py
"""Language order for Transcribe and the translate rule: pure logic."""
import pytest

from lowass.languages import (
    ANY,
    DEFAULT,
    TranslateRule,
    order_for,
    recognition_choices,
    translate_from_choices,
    translate_to_choices,
)

CONF = ["cs-CZ", "sk-SK", "en-US", "de-DE"]


def test_default_keeps_the_configured_order_and_a_chosen_language_moves_to_the_front():
    assert order_for(DEFAULT, CONF) == CONF
    assert order_for("de-DE", CONF) == ["de-DE", "cs-CZ", "sk-SK", "en-US"]  # the rest keep their order
    assert order_for("cs-CZ", CONF) == CONF  # already first
    assert order_for("en-US", CONF) == ["en-US", "cs-CZ", "sk-SK", "de-DE"]


def test_the_result_is_always_a_permutation_of_the_configured_languages():
    for choice in (DEFAULT, "de-DE", "xx-XX", "", "cs-cz", "de"):
        out = order_for(choice, CONF)
        assert sorted(out) == sorted(CONF) and len(out) == len(CONF), choice  # nothing added, nothing lost, no duplicate


def test_an_unknown_or_stale_choice_changes_nothing_and_never_adds_a_language():
    assert order_for("fr-FR", CONF) == CONF
    assert order_for("de-DE", ["cs-CZ"]) == ["cs-CZ"]  # not configured any more: ignored


def test_the_configured_list_is_not_modified():
    conf = list(CONF)
    order_for("de-DE", conf)
    assert conf == CONF


def test_one_configured_language_is_a_valid_order():
    assert order_for("cs-CZ", ["cs-CZ"]) == ["cs-CZ"] and order_for(DEFAULT, ["cs-CZ"]) == ["cs-CZ"]


def test_dropdown_choices_start_with_default():
    assert recognition_choices(CONF) == [DEFAULT, *CONF]
    assert translate_to_choices(CONF)[0] == DEFAULT and translate_from_choices(CONF, "de-DE")[-1] == ANY


def test_the_default_rule_translates_german_into_czech_only():
    rule = TranslateRule()
    assert rule.source == "de-DE" and rule.target == "cs-CZ"
    assert rule.wants("de-DE") and not rule.wants("en-US") and not rule.wants("cs-CZ") and not rule.wants("sk-SK")
    assert not rule.wants(None) and not rule.wants("")


def test_the_user_can_say_english_into_czech():
    rule = TranslateRule(frm="en-US", to="cs-CZ")
    assert rule.wants("en-US") and not rule.wants("de-DE")


def test_a_sentence_is_never_translated_into_its_own_language():
    assert not TranslateRule(frm="cs-CZ", to="cs-CZ").wants("cs-CZ")
    assert not TranslateRule(frm="en-US", to="en-US").wants("en-GB")  # same base language
    assert not TranslateRule(frm=DEFAULT, to="de-DE").wants("de-DE")  # default de -> de makes no sense


def test_to_can_be_any_configured_language():
    rule = TranslateRule(frm="de-DE", to="en-US")
    assert rule.target == "en-US" and rule.wants("de-DE")


def test_any_translates_every_foreign_language_like_before():
    rule = TranslateRule(frm=ANY)
    assert rule.wants("de-DE") and rule.wants("fr-FR") and not rule.wants("cs-CZ") and not rule.wants("en-US")
    assert rule.wants("sk-SK") is False  # understood


@pytest.mark.parametrize("lang", ["de-DE", "de-AT", "DE-de"])
def test_regional_variants_count_as_the_same_language(lang):
    assert TranslateRule().wants(lang)
