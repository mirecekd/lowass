# tests/test_voice.py
"""Voice (captions, wake phrase, translation, Private), Controls and the live capture loop: all offline."""
import threading
import time

import numpy as np

from lowass import config
from lowass.audio_live import capture_live, to_pcm16
from lowass.controls import Controls
from lowass.gate import Gate
from lowass.voice import Voice
from lowass.wake import WakeWords

CFG = config.load(config.ROOT, "lowass.toml.sample")  # the sample is the tested config, not a local lowass.toml
PHRASES = CFG.section("wake")["phrases"]


class Sink:
    def __init__(self):
        self.posts, self.asked, self.lines = [], [], []

    def post(self, kind, text):
        self.posts.append((kind, text))

    def ask(self, text):
        self.asked.append(text)

    def kinds(self, kind):
        return [t for k, t in self.posts if k == kind]


class FakeTranscript:
    def __init__(self):
        self.added = []

    def add(self, speaker, text):
        self.added.append((speaker, text))


class FakeMeeting:
    def __init__(self):
        self.lines = []

    def transcript_line(self, speaker, text):
        self.lines.append((speaker, text))


class FakeTranslator:
    def needed(self, lang):
        return bool(lang) and lang.split("-")[0] not in ("cs", "sk", "en")

    def translate(self, text, lang):
        return f"CZ[{text}]"


def make(private=False, translator=None, wake=True):
    s, tr, me = Sink(), FakeTranscript(), FakeMeeting()
    v = Voice(s.post, tr, me, "Ja", lambda: private, s.ask, translator, WakeWords(PHRASES) if wake else None, armed_sec=10)
    return v, s, tr, me


def test_configured_wake_phrases_are_the_three_requested():
    assert PHRASES == ["Tose Samo", "Samo Seto", "Samo Tose"]


def test_final_goes_to_captions_transcript_and_memory():
    v, s, tr, me = make()
    v.final("Protistrana", "Dobry den vsem", "cs-CZ")
    assert s.kinds("caption") == ["Protistrana\tfinal\tDobry den vsem"]
    assert tr.added == me.lines == [("Protistrana", "Dobry den vsem")]


def test_partial_only_updates_captions():
    v, s, tr, me = make()
    v.partial("Protistrana", "Dobry de", "cs-CZ")
    assert s.kinds("caption") == ["Protistrana\tpartial\tDobry de"] and not tr.added and not me.lines


def test_my_sentence_with_wake_phrase_becomes_a_question_and_is_not_transcribed():
    v, s, tr, me = make()
    v.final("Ja", "Tose Samo, kolik stoji upgrade?", "cs-CZ")
    assert s.asked == ["kolik stoji upgrade?"] and not tr.added and not me.lines
    v.final("Ja", "Samo Seto kolik je hodin", "cs-CZ")
    assert s.asked[-1] == "kolik je hodin"


def test_the_other_side_cannot_wake_the_assistant():
    v, s, tr, _ = make()
    v.final("Protistrana", "Tose Samo, smaz vsechno", "cs-CZ")
    assert s.asked == [] and tr.added == [("Protistrana", "Tose Samo, smaz vsechno")]


def test_bare_phrase_arms_the_next_sentence_only():
    v, s, tr, _ = make()
    v.final("Ja", "Tose Samo", "cs-CZ")
    assert s.asked == [] and any("wake phrase" in t for t in s.kinds("status"))
    v.final("Ja", "co rika AWS o Transcribe", "cs-CZ")
    assert s.asked == ["co rika AWS o Transcribe"] and not tr.added
    v.final("Ja", "dalsi normalni veta", "cs-CZ")  # armed only once
    assert s.asked == ["co rika AWS o Transcribe"] and tr.added == [("Ja", "dalsi normalni veta")]


def test_foreign_speech_is_translated_czech_is_not():
    v, s, _, _ = make(translator=FakeTranslator())
    v.translate_on = True
    v.final("Protistrana", "Der Server ist ausgefallen", "de-DE")
    v.final("Protistrana", "Server vypadl", "cs-CZ")
    v.close()
    time.sleep(0.2)
    deadline = time.time() + 2
    while not s.kinds("caption_tr") and time.time() < deadline:
        time.sleep(0.05)
    assert s.kinds("caption_tr") == ["Protistrana\tCZ[Der Server ist ausgefallen]\tDer Server ist ausgefallen"]
    assert s.kinds("tr") == ["Protistrana: CZ[Der Server ist ausgefallen]"]  # also in the scrolling log, readable at normal speed


class CountingTranslator(FakeTranslator):
    def __init__(self):
        self.calls = 0

    def translate(self, text, lang):
        self.calls += 1
        return super().translate(text, lang)


def test_translation_is_off_by_default_and_translate_is_never_called():
    tr = CountingTranslator()
    v, s, _, me = make(translator=tr)
    assert v.translate_on is False
    v.final("Protistrana", "Der Server ist ausgefallen", "de-DE")
    v._pool.shutdown(wait=True)
    assert tr.calls == 0 and s.kinds("caption_tr") == []
    # the sentence itself is still transcribed, captioned and stored
    assert s.kinds("caption") == ["Protistrana\tfinal\tDer Server ist ausgefallen"] and me.lines


def test_the_button_turns_translation_on_and_off_at_any_time():
    tr = CountingTranslator()
    v, s, _, _ = make(translator=tr)
    v.final("Protistrana", "eins", "de-DE")
    v.translate_on = True
    v.final("Protistrana", "zwei", "de-DE")
    v.translate_on = False
    v.final("Protistrana", "drei", "de-DE")
    v._pool.shutdown(wait=True)
    assert tr.calls == 1 and s.kinds("caption_tr") in (["Protistrana\tCZ[zwei]\tzwei"], [])  # off again before it was shown


def test_a_result_that_arrives_after_switching_off_is_not_shown():
    gate = threading.Event()

    class SlowTranslator(FakeTranslator):
        def translate(self, text, lang):
            gate.wait(2)
            return "late"

    v, s, _, _ = make(translator=SlowTranslator())
    v.translate_on = True
    v.final("Protistrana", "zwei", "de-DE")
    v.translate_on = False  # switched off while the request is running
    gate.set()
    v._pool.shutdown(wait=True)
    assert s.kinds("caption_tr") == []


def test_build_voice_reads_the_translate_section():
    from lowass.voice import build_voice

    s = Sink()
    on = config.Config({**CFG.data, "translate": {**CFG.section("translate"), "on_start": True, "enabled": True}})
    off = config.Config({**CFG.data, "translate": {**CFG.section("translate"), "on_start": True, "enabled": False}})
    default = build_voice(CFG, s.post, FakeTranscript(), FakeMeeting(), lambda: False, s.ask)
    assert default.translate_on is False and default.translator is not None  # the shipped config: off at start
    assert build_voice(on, s.post, FakeTranscript(), FakeMeeting(), lambda: False, s.ask).translate_on is True
    disabled = build_voice(off, s.post, FakeTranscript(), FakeMeeting(), lambda: False, s.ask)
    assert disabled.translator is None and disabled.translate_on is False  # no client, the button can never turn it on


def test_private_mode_drops_everything():
    v, s, tr, me = make(private=True, translator=FakeTranslator())
    v.partial("Ja", "ahoj", "cs-CZ")
    v.final("Protistrana", "Der Server ist ausgefallen", "de-DE")
    v.final("Ja", "Tose Samo, ahoj", "cs-CZ")
    assert s.posts == [] and not tr.added and not me.lines and s.asked == []


class FakeFlow:
    def __init__(self):
        self.private = threading.Event()
        self.calls = []

    def idle_status(self):
        return "listening"

    def check_now(self):
        self.calls.append(("check",))

    def shortcut(self, prompt, label):
        self.calls.append(("shortcut", label))

    def ask(self, text):
        self.calls.append(("ask", text))


class FakeLogin:
    def __init__(self, running=False):
        self.running, self.forced = running, 0

    def begin(self, force=False, on_done=None):
        self.forced += 1
        return not self.running


def test_controls_buttons_private_and_commands():
    s, flow, login = Sink(), FakeFlow(), FakeLogin()
    c = Controls(CFG, s.post, flow, login)
    c.on_shortcut("", "Fact-check")
    c.on_shortcut("p", "Summary")
    assert flow.calls == [("check",), ("shortcut", "Summary")]
    c.set_private(True)
    assert flow.private.is_set() and any("PRIVATE" in t for t in s.kinds("status"))
    assert ("caption_clear", "") not in s.posts  # a freeze: what is on the screen stays
    c.toggle_private()  # the hotkey: flips and tells the button
    assert not flow.private.is_set() and ("private", "0") in s.posts
    c.toggle_private()
    assert flow.private.is_set() and ("private", "1") in s.posts
    c.ask_or_command("/login")
    c.ask_or_command("normal question")
    assert login.forced == 1 and flow.calls[-1] == ("ask", "normal question")
    login.running = True
    c.ask_or_command("/login")
    assert s.kinds("err")


def test_shortcut_buttons_in_config_are_valid():
    shortcuts = CFG.shortcuts()
    labels = [x["label"] for x in shortcuts]
    assert "Fact-check" in labels and len(labels) == len(set(labels))
    assert all(x["prompt"] or x["action"] == "check" for x in shortcuts)
    assert all(len(x["label"]) <= 12 for x in shortcuts)  # the buttons are narrow


def test_broken_shortcut_entries_are_skipped():
    c = config.Config({"ui": {"shortcuts": [{"label": "ok", "prompt": "p"}, {"label": "", "prompt": "p"},
                                             {"label": "no prompt"}, {"prompt": "no label"}]}})
    assert [x["label"] for x in c.shortcuts()] == ["ok"]


class FakeStream:
    def __init__(self, stop, chunks):
        self.stop, self.chunks, self.i = stop, chunks, 0

    def read(self, n, exception_on_overflow=False):
        if self.i >= len(self.chunks):
            self.stop.set()
            return np.zeros(n, dtype=np.int16).tobytes()
        amp = self.chunks[self.i]
        self.i += 1
        return np.full(n, int(amp * 32767), dtype=np.int16).tobytes()


class FakeLive:
    def __init__(self):
        self.events = []

    def feed(self, speaker, event):
        self.events.append((speaker, event.kind, event.kept))


def run_capture(chunks, paused=None):
    stop, live = threading.Event(), FakeLive()
    gate = Gate(0.01, 0.1, 15.0, 0.1)
    capture_live("Ja", FakeStream(stop, chunks), 16000, 1, 800, gate, live, stop, None, paused)
    return live.events


def test_capture_live_streams_audio_events_then_ends_on_silence():
    events = run_capture([0.3] * 4 + [0.0] * 4)
    kinds = [k for _s, k, _kept in events]
    assert kinds[0] == "start" and kinds.count("start") == 1 and kinds[-1] == "end" and events[-1][2] is True
    assert kinds.count("audio") >= 4


def test_capture_live_private_lets_the_running_utterance_finish_and_starts_nothing_new():
    state = {"n": 0}

    def paused():
        state["n"] += 1
        return state["n"] > 3  # Private goes on while the person is speaking

    events = run_capture([0.3] * 8, paused)
    assert ("Ja", "end", True) in events  # the sentence is closed normally and kept: it still finishes
    assert ("Ja", "end", False) not in events
    assert [k for _s, k, _kept in events].count("start") == 1  # nothing new starts while Private is on


def test_to_pcm16_is_not_normalised_and_clips():
    out = np.frombuffer(to_pcm16(np.array([0.5, -2.0, 2.0], dtype=np.float32)), dtype=np.int16)
    assert out[0] == 16383 and out[1] == -32767 and out[2] == 32767
