# tests/test_voice_speaker_names.py
"""Voice with Teams speaker names ([speaker].enabled): only the other side is named, the translation still finds its line."""
import time

from lowass import config
from lowass.speaker_names import SpeakerTimeline
from lowass.transcript_logic import TranscriptLines
from lowass.ui_parts import parse_caption, parse_translation
from lowass.voice import Voice, build_voice

CFG = config.load(config.ROOT, "lowass.toml.sample")
OTHER = CFG.section("audio")["other_label"]
SENTENCE = "Dobry den vsem dnes projdeme rozpocet"


class Sink:
    def __init__(self):
        self.posts = []

    def post(self, kind, text):
        self.posts.append((kind, text))

    def kinds(self, kind):
        return [t for k, t in self.posts if k == kind]


class Store:
    def __init__(self):
        self.added = []

    def add(self, speaker, text):
        self.added.append((speaker, text))

    transcript_line = add


class Translator:
    def needed(self, lang):
        return True

    def translate(self, text, lang):
        return f"CZ[{text}]"


def make(timeline, translator=None):
    s, tr, me = Sink(), Store(), Store()
    v = Voice(s.post, tr, me, "Ja", lambda: False, lambda t: None, translator, None, 10.0, timeline, OTHER, 0.3)
    return v, s, tr, me


def lit(name, seconds_ago, seconds_long):
    t = time.time() - seconds_ago
    return [{"t": t, "name": name, "speaking": True}, {"t": t + seconds_long, "name": name, "speaking": False}]


def timeline(*events):
    tl = SpeakerTimeline()
    for e in events:
        tl.feed(e)
    return tl


def test_names_are_off_by_default_and_the_messages_are_the_old_ones():
    assert CFG.section("speaker")["enabled"] is False
    s = Sink()
    v = build_voice(CFG, s.post, Store(), Store(), lambda: False, lambda t: None)
    assert v.names is None
    v.final(OTHER, SENTENCE, "cs-CZ")
    assert s.kinds("caption") == [f"{OTHER}\tfinal\t{SENTENCE}"]


def test_without_a_timeline_nothing_changes():
    v, s, tr, me = make(None)
    v.final(OTHER, SENTENCE, "cs-CZ")
    assert s.kinds("caption") == [f"{OTHER}\tfinal\t{SENTENCE}"]
    assert tr.added == me.added == [(OTHER, SENTENCE)]


def test_lit_name_goes_to_caption_transcript_and_memory():
    v, s, tr, me = make(timeline(*lit("Anna Test", 2.5, 2.0)))
    v.final(OTHER, SENTENCE, "cs-CZ")
    assert s.kinds("caption") == [f"{OTHER}\tfinal\tAnna Test: {SENTENCE}"]  # the caption key stays the other label
    assert tr.added == me.added == [("Anna Test", SENTENCE)]


def test_longest_lit_name_wins():
    v, _, tr, _ = make(timeline(*lit("Anna Test", 2.8, 0.6), *lit("Boris Test", 2.2, 1.8)))
    v.final(OTHER, SENTENCE, "cs-CZ")
    assert tr.added == [("Boris Test", SENTENCE)]


def test_nothing_lit_keeps_the_plain_label():
    v, s, tr, _ = make(timeline())
    v.final(OTHER, SENTENCE, "cs-CZ")
    assert s.kinds("caption") == [f"{OTHER}\tfinal\t{SENTENCE}"] and tr.added == [(OTHER, SENTENCE)]


def test_my_sentences_and_partials_are_never_named():
    v, s, tr, _ = make(timeline(*lit("Anna Test", 2.5, 2.0)))
    v.partial(OTHER, "Dobry de", "cs-CZ")
    v.final("Ja", "Dekuji", "cs-CZ")
    assert s.kinds("caption") == [f"{OTHER}\tpartial\tDobry de", "Ja\tfinal\tDekuji"]
    assert tr.added == [("Ja", "Dekuji")]


def test_translation_is_made_from_the_plain_sentence_and_pins_the_named_line():
    v, s, _, _ = make(timeline(*lit("Anna Test", 2.5, 2.0)), Translator())
    v.translate_on = True
    lines = TranscriptLines()
    v.partial(OTHER, "Dobry de", "cs-CZ")
    lines.update(*parse_caption(s.kinds("caption")[-1]))
    v.final(OTHER, SENTENCE, "cs-CZ")
    lines.update(*parse_caption(s.kinds("caption")[-1]))
    v._pool.shutdown(wait=True)  # lets the translation finish
    speaker, out, source = parse_translation(s.kinds("caption_tr")[-1])
    assert out == f"CZ[{SENTENCE}]"  # the name was not translated
    lines.update(OTHER, "partial", "next sentence")  # a newer line is open, the translation still finds its own
    lines.translate(speaker, out, source)
    assert [e.text for e in lines.entries] == [f"Anna Test: {SENTENCE}", "next sentence"]
    assert lines.entries[0].translation == out and not lines.entries[1].translation
    assert s.kinds("tr") == [f"Anna Test: CZ[{SENTENCE}]"]
