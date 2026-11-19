# tests/test_lang_control.py
"""The language dropdowns reach the places that use them: the Transcribe order and the translation rule."""
from types import SimpleNamespace

from lowass.lang_control import LanguageControl, build_rule
from lowass.languages import ANY, DEFAULT
from lowass.transcribe import Transcriber, stream_kwargs
from lowass.translate import Translator


def cfg(**translate):
    sections = {"translate": {"understood": ["cs", "sk", "en"], **translate}}
    return SimpleNamespace(section=lambda n: sections.get(n, {}))


def make_transcriber(monkeypatch):
    monkeypatch.setattr("lowass.transcribe.boto3.Session", lambda **_kw: SimpleNamespace())  # no AWS profile is read
    return Transcriber({"profile": "p", "region": "eu-central-1", "languages": ["cs-CZ", "sk-SK", "en-US", "de-DE"]})


def make_control(rule=None):
    posts = []
    translator = Translator("p", "r", "cs", ("cs", "sk", "en"), client=SimpleNamespace(), rule=rule or build_rule(cfg()))
    voice = SimpleNamespace(translator=translator)
    return LanguageControl(voice, lambda k, t: posts.append((k, t))), translator, posts


def test_the_default_rule_comes_from_the_config_and_is_german_into_czech():
    assert (build_rule(cfg()).source, build_rule(cfg()).target) == ("de-DE", "cs-CZ")
    rule = build_rule(cfg(from_default="en-US", to_default="de-DE"))
    assert (rule.source, rule.target) == ("en-US", "de-DE")


def test_default_choice_keeps_the_order_and_german_goes_first_for_the_next_stream(monkeypatch):
    tr = make_transcriber(monkeypatch)
    ctl, _t, _p = make_control()
    ctl.attach(tr)
    assert tr.langs == ["cs-CZ", "sk-SK", "en-US", "de-DE"] and stream_kwargs(tr.langs)["language_options"][0] == "cs-CZ"
    ctl.set_recognition("de-DE")
    assert tr.langs == ["de-DE", "cs-CZ", "sk-SK", "en-US"]  # what live_stream passes to Transcribe at the next open
    assert stream_kwargs(tr.langs)["language_options"][0] == "de-DE"
    ctl.set_recognition(DEFAULT)
    assert tr.langs == ["cs-CZ", "sk-SK", "en-US", "de-DE"]


def test_a_choice_made_before_the_listener_exists_is_applied_when_it_appears(monkeypatch):
    tr = make_transcriber(monkeypatch)
    ctl, _t, posts = make_control()
    ctl.set_recognition("de-DE")  # no Transcriber yet (--no-audio, or the listener is still starting)
    assert any("de-DE" in t for _k, t in posts)
    ctl.attach(tr)
    assert tr.langs[0] == "de-DE"


def test_changing_the_order_never_adds_or_loses_a_language(monkeypatch):
    tr = make_transcriber(monkeypatch)
    ctl, _t, _p = make_control()
    ctl.attach(tr)
    for choice in ("de-DE", "en-US", "xx-XX", DEFAULT, "sk-SK"):
        ctl.set_recognition(choice)
        assert sorted(tr.langs) == sorted(["cs-CZ", "sk-SK", "en-US", "de-DE"]), choice


def test_translation_rule_is_replaced_at_runtime_and_the_translator_sees_it_at_once():
    ctl, translator, posts = make_control()
    assert translator.needed("de-DE") and not translator.needed("en-US")
    ctl.set_translation("en-US", "cs-CZ")
    assert translator.needed("en-US") and not translator.needed("de-DE")
    ctl.set_translation(ANY, DEFAULT)
    assert translator.needed("de-DE") and translator.needed("fr-FR") and not translator.needed("en-US")  # understood
    assert any(k == "status" for k, _t in posts)


def test_the_translation_goes_into_the_chosen_target_language():
    calls = []

    class Client:
        def translate_text(self, **kw):
            calls.append(kw)
            return {"TranslatedText": "x"}

    translator = Translator("p", "r", client=Client(), rule=build_rule(cfg()))
    ctl = LanguageControl(SimpleNamespace(translator=translator), lambda *_a: None)
    assert translator.translate("Hello", "en-US") is None  # default rule: English is not translated, no call is made
    assert calls == []
    ctl.set_translation("en-US", "de-DE")
    assert translator.translate("Hello", "en-US") == "x"
    assert calls[-1]["SourceLanguageCode"] == "en" and calls[-1]["TargetLanguageCode"] == "de"
    ctl.set_translation("en-US", "cs-CZ")
    translator.translate("Hello", "en-US")
    assert calls[-1]["TargetLanguageCode"] == "cs"


def test_a_sentence_without_a_language_label_is_never_translated():
    _ctl, translator, _p = make_control()
    assert not translator.needed(None) and not translator.needed("")


def test_old_behaviour_without_a_rule_is_unchanged():
    translator = Translator("p", "r", "cs", ("cs", "sk", "en"), client=SimpleNamespace())
    assert translator.needed("de-DE") and translator.needed("fr-FR") and not translator.needed("en-US")


def test_the_shipped_sample_has_the_agreed_default_order_and_the_default_pair():
    from lowass.config import ROOT, load

    cfg = load(ROOT, "lowass.toml.sample")
    assert cfg.section("transcribe")["languages"] == ["cs-CZ", "sk-SK", "en-US", "de-DE"]  # German LAST: the default order
    rule = build_rule(cfg)
    assert (rule.source, rule.target) == ("de-DE", "cs-CZ")
