# tests/test_transcribe.py
import io
import queue
import threading
import wave

import pytest
from botocore.exceptions import NoCredentialsError, ProfileNotFound

from lowass import config
from lowass.transcribe import (
    check_languages,
    friendly_error,
    stream_kwargs,
    transcribe_worker,
    wav_to_pcm,
)

CFG = config.load(config.ROOT, "lowass.toml.sample")  # the sample is the tested config, not a local lowass.toml


def make_wav(n=16000, rate=16000, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * n * channels)
    return buf.getvalue()


def test_default_languages_are_cs_sk_de_en_and_valid():
    langs = CFG.section("transcribe")["languages"]
    assert langs == ["cs-CZ", "sk-SK", "de-DE", "en-US"]
    assert check_languages(list(langs)) == langs
    assert CFG.section("stt")["provider"] == "transcribe"


@pytest.mark.parametrize("bad", [[], ["cs"], ["en-US", "en-GB"], ["cs-cz"], ["de-DE", "xx"]])
def test_bad_language_lists_rejected(bad):
    with pytest.raises(ValueError):
        check_languages(bad)


def test_stream_kwargs_single_fixed_multi_identifies():
    assert stream_kwargs(["cs-CZ"]) == {"language_code": "cs-CZ"}
    kw = stream_kwargs(["cs-CZ", "de-DE"])
    assert kw["language_code"] is None and kw["identify_multiple_languages"] and kw["language_options"] == ["cs-CZ", "de-DE"]


def test_wav_to_pcm_roundtrip_and_format_check():
    assert len(wav_to_pcm(make_wav(8000))) == 16000
    with pytest.raises(ValueError):
        wav_to_pcm(make_wav(rate=8000))
    with pytest.raises(ValueError):
        wav_to_pcm(make_wav(channels=2))


def test_friendly_errors_name_the_profile_and_the_fix():
    assert "sign-in" not in friendly_error(NoCredentialsError(), "ai")  # the worker starts the sign-in itself
    assert "login" in friendly_error(NoCredentialsError(), "ai")
    assert "not found" in friendly_error(ProfileNotFound(profile="x"), "x")
    assert "transcribe:StartStreamTranscription" in friendly_error(RuntimeError("User is not authorized to perform"), "ai")


class FakeTr:
    profile, langs = "ai", ["cs-CZ"]

    def __init__(self, script):
        self.script = list(script)

    def run(self, pcm):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, ["cs-CZ"]


def run_worker(script, n):
    q, stop, texts, errors = queue.Queue(), threading.Event(), [], []
    for _ in range(n):
        q.put(("Ja", make_wav()))
    t = threading.Thread(target=transcribe_worker, args=(q, stop, FakeTr(script), lambda s, x: texts.append((s, x)), None, errors.append))
    t.start()
    stop.set()
    t.join(5)
    return texts, errors


def test_worker_delivers_text_and_skips_empty():
    texts, errors = run_worker(["ahoj svete", ""], 2)
    assert texts == [("Ja", "ahoj svete")] and errors == []


def test_worker_reports_same_error_once_and_survives():
    texts, errors = run_worker([NoCredentialsError(), NoCredentialsError(), "zase funguje"], 3)
    assert len(errors) == 1 and "login" in errors[0]
    assert texts == [("Ja", "zase funguje")]


def test_worker_starts_the_sign_in_instead_of_reporting_when_login_is_missing():
    q, stop, texts, errors, started = queue.Queue(), threading.Event(), [], [], []
    for _ in range(3):
        q.put(("Ja", make_wav()))
    tr = FakeTr([NoCredentialsError(), NoCredentialsError(), "po prihlaseni"])
    t = threading.Thread(target=transcribe_worker, args=(q, stop, tr, lambda s, x: texts.append((s, x)), None,
                                                           errors.append, lambda: started.append(1) or True))
    t.start()
    stop.set()
    t.join(5)
    assert len(started) == 2 and errors == []  # the manager de-duplicates; the worker never nags the window
    assert texts == [("Ja", "po prihlaseni")]
