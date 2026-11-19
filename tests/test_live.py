# tests/test_live.py
"""LiveTranscriber with a fake Transcribe client: no network, no AWS."""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from botocore.exceptions import NoCredentialsError

from lowass.gate import GateEvent
from lowass.live import LiveTranscriber


def result(text: str, partial: bool, lang: str | None = "cs-CZ") -> SimpleNamespace:
    alt = SimpleNamespace(transcript=text)
    return SimpleNamespace(transcript=SimpleNamespace(results=[
        SimpleNamespace(is_partial=partial, alternatives=[alt], language_code=lang)]))


class FakeStream:
    """Every audio chunk yields a partial 'p<n>'; end_stream yields the final 'final:<n>' and closes the output."""

    def __init__(self, open_delay: float = 0.0):
        self.chunks: list[bytes] = []
        self.ended = False
        self._out: asyncio.Queue[SimpleNamespace | None] = asyncio.Queue()
        self.input_stream = self
        self.output_stream = self

    async def send_audio_event(self, audio_chunk: bytes) -> None:
        self.chunks.append(audio_chunk)
        self._out.put_nowait(result(f"p{len(self.chunks)}", True))

    async def end_stream(self) -> None:
        self.ended = True
        self._out.put_nowait(result(f"final:{len(self.chunks)}", False))
        self._out.put_nowait(None)

    def __aiter__(self) -> FakeStream:
        return self

    async def __anext__(self) -> SimpleNamespace:
        item = await self._out.get()
        if item is None:
            raise StopAsyncIteration
        return item


class FakeClient:
    def __init__(self, streams: list[FakeStream], open_delay: float = 0.0, fail_first: bool = False):
        self.streams = streams
        self.open_delay = open_delay
        self.fail_first = fail_first
        self.calls = 0

    async def start_stream_transcription(self, **kwargs: object) -> FakeStream:
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("boom")
        await asyncio.sleep(self.open_delay)
        stream = FakeStream()
        self.streams.append(stream)
        return stream


class Rec:
    def __init__(self) -> None:
        self.partials: list[tuple[str, str, str | None]] = []
        self.finals: list[tuple[str, str, str | None]] = []
        self.errors: list[BaseException] = []

    def wait(self, cond, timeout: float = 3.0) -> None:
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return
            time.sleep(0.01)
        raise AssertionError("timeout waiting for the condition")


def make(client: FakeClient, creds_error: BaseException | None = None) -> tuple[LiveTranscriber, Rec]:
    def credentials() -> SimpleNamespace:
        if creds_error is not None:
            raise creds_error
        return SimpleNamespace(**dict.fromkeys(("access_key", "secret_key", "token"), "fake"))

    tr = SimpleNamespace(region="eu-central-1", langs=["cs-CZ"], credentials=credentials)
    rec = Rec()
    live = LiveTranscriber(tr, lambda *a: rec.partials.append(a), lambda *a: rec.finals.append(a),  # type: ignore[arg-type]
                           rec.errors.append, client_factory=lambda region, creds: client)
    return live, rec


def audio(n: int) -> GateEvent:
    return GateEvent("audio", pcm=bytes([n]) * 4)


@pytest.fixture
def live_pair():
    made: list[LiveTranscriber] = []

    def factory(client: FakeClient, creds_error: BaseException | None = None):
        live, rec = make(client, creds_error)
        made.append(live)
        return live, rec

    yield factory
    for live in made:
        live.close()


def test_partials_then_final_in_order(live_pair):
    streams: list[FakeStream] = []
    live, rec = live_pair(FakeClient(streams))
    live.feed("me", GateEvent("start"))
    live.feed("me", audio(1))
    live.feed("me", audio(2))
    live.feed("me", GateEvent("end"))
    rec.wait(lambda: rec.finals)
    assert rec.partials == [("me", "p1", "cs-CZ"), ("me", "p2", "cs-CZ")]
    assert rec.finals == [("me", "final:2", "cs-CZ")]
    assert streams[0].ended


def test_two_speakers_do_not_mix(live_pair):
    streams: list[FakeStream] = []
    live, rec = live_pair(FakeClient(streams))
    live.feed("me", GateEvent("start"))
    live.feed("them", GateEvent("start"))
    live.feed("me", audio(1))
    live.feed("them", audio(2))
    live.feed("them", audio(3))
    live.feed("me", GateEvent("end"))
    live.feed("them", GateEvent("end"))
    rec.wait(lambda: len(rec.finals) == 2)
    assert sorted(rec.finals) == [("me", "final:1", "cs-CZ"), ("them", "final:2", "cs-CZ")]
    assert [p for p in rec.partials if p[0] == "me"] == [("me", "p1", "cs-CZ")]
    assert [p for p in rec.partials if p[0] == "them"] == [("them", "p1", "cs-CZ"), ("them", "p2", "cs-CZ")]


def test_end_not_kept_emits_nothing(live_pair):
    streams: list[FakeStream] = []
    live, rec = live_pair(FakeClient(streams))
    live.feed("me", GateEvent("start"))
    live.feed("me", audio(1))
    live.feed("me", GateEvent("end", kept=False))
    live.feed("me", GateEvent("start"))
    live.feed("me", audio(2))
    live.feed("me", GateEvent("end"))
    rec.wait(lambda: rec.finals)
    assert rec.finals == [("me", "final:1", "cs-CZ")]
    assert ("me", "p1", "cs-CZ") in rec.partials and len(rec.partials) <= 2
    assert not rec.errors


def test_discarded_utterance_alone_is_silent(live_pair):
    streams: list[FakeStream] = []
    live, rec = live_pair(FakeClient(streams))
    live.feed("me", GateEvent("start"))
    live.feed("me", audio(1))
    live.feed("me", GateEvent("end", kept=False))
    time.sleep(0.4)  # a discarded utterance may not even need to open a stream: nothing may come out either way
    assert rec.finals == [] and rec.errors == []


def test_a_failed_open_is_retried_and_the_sentence_still_arrives(live_pair):
    """The first open fails (boom): a new stream is opened and the SAME sentence is transcribed. No error is shown."""
    streams: list[FakeStream] = []
    client = FakeClient(streams, fail_first=True)
    live, rec = live_pair(client)
    live.feed("me", GateEvent("start"))
    live.feed("me", audio(1))
    live.feed("me", GateEvent("end"))
    rec.wait(lambda: rec.finals)
    assert rec.finals == [("me", "final:1", "cs-CZ")] and rec.errors == [] and client.calls == 2


def test_the_next_sentence_works_after_a_hopeless_one(live_pair):
    """Every open attempt of the first sentence fails (MAX_REOPEN + 1 tries): ONE error is reported, then the next works."""
    streams: list[FakeStream] = []
    client = FakeClient(streams)
    state = {"fail": True}
    real = client.start_stream_transcription

    async def flaky(**kw):
        if state["fail"]:
            raise RuntimeError("down")
        return await real(**kw)

    client.start_stream_transcription = flaky  # type: ignore[method-assign]
    live, rec = live_pair(client)
    live.feed("me", GateEvent("start"))
    live.feed("me", audio(1))
    live.feed("me", GateEvent("end"))
    rec.wait(lambda: rec.errors)
    assert len(rec.errors) == 1 and isinstance(rec.errors[0], RuntimeError)
    state["fail"] = False
    live.feed("me", GateEvent("start"))
    live.feed("me", audio(2))
    live.feed("me", GateEvent("end"))
    rec.wait(lambda: rec.finals)
    assert rec.finals == [("me", "final:1", "cs-CZ")] and len(rec.errors) == 1


def test_login_error_is_passed_on_unchanged(live_pair):
    err = NoCredentialsError()
    live, rec = live_pair(FakeClient([]), creds_error=err)
    live.feed("me", GateEvent("start"))
    live.feed("me", audio(1))
    live.feed("me", GateEvent("end"))
    rec.wait(lambda: rec.errors)
    assert rec.errors == [err]


def test_audio_before_the_stream_opens_is_sent(live_pair):
    streams: list[FakeStream] = []
    live, rec = live_pair(FakeClient(streams, open_delay=0.3))
    live.feed("me", GateEvent("start"))
    live.feed("me", audio(1))
    live.feed("me", audio(2))
    live.feed("me", GateEvent("end"))
    assert streams == []  # still opening
    rec.wait(lambda: rec.finals)
    assert streams[0].chunks == [bytes([1]) * 4, bytes([2]) * 4]


def test_feed_does_not_block_while_the_stream_opens(live_pair):
    live, _ = live_pair(FakeClient([], open_delay=0.5))
    t0 = time.time()
    live.feed("me", GateEvent("start"))
    for i in range(50):
        live.feed("me", audio(i % 200))
    assert time.time() - t0 < 0.2


def test_close_ends_cleanly_with_an_open_stream():
    streams: list[FakeStream] = []
    live, rec = make(FakeClient(streams))
    live.feed("me", GateEvent("start"))
    live.feed("me", audio(1))
    rec.wait(lambda: rec.partials)
    live.close()
    live.close()  # a second close is harmless
    live.feed("me", audio(2))  # and feeding after close does nothing
    assert not [t for t in threading.enumerate() if t.name == "live-transcribe"]
    assert rec.errors == []


class DyingStream(FakeStream):
    """The connection breaks after `n` audio chunks (AWS_IO_SOCKET_TIMEOUT in the field)."""

    def __init__(self, n: int):
        super().__init__()
        self.n = n

    async def send_audio_event(self, audio_chunk: bytes) -> None:
        await super().send_audio_event(audio_chunk)
        if len(self.chunks) >= self.n:
            self._out.put_nowait(RuntimeError("AwsCrtError: AWS_IO_SOCKET_TIMEOUT"))  # type: ignore[arg-type]

    async def __anext__(self) -> SimpleNamespace:
        item = await self._out.get()
        if isinstance(item, Exception):
            raise item
        if item is None:
            raise StopAsyncIteration
        return item


class SequenceClient:
    """Hands out the given streams one after another and counts the opens."""

    def __init__(self, streams: list[FakeStream]):
        self.streams, self.calls = streams, 0

    async def start_stream_transcription(self, **kwargs: object) -> FakeStream:
        self.calls += 1
        return self.streams[min(self.calls, len(self.streams)) - 1]


def test_a_connection_that_breaks_mid_sentence_is_continued_on_a_new_stream(live_pair):
    """The field failure: the stream died after 3 chunks. The other chunks must not be lost: they go to a new stream."""
    first, second = DyingStream(3), FakeStream()
    client = SequenceClient([first, second])
    live, rec = live_pair(client)  # type: ignore[arg-type]
    live.feed("me", GateEvent("start"))
    for i in range(1, 9):
        live.feed("me", audio(i))
    live.feed("me", GateEvent("end"))
    rec.wait(lambda: rec.finals)
    assert client.calls == 2 and rec.errors == []
    assert len(first.chunks) == 3
    assert len(second.chunks) == 5 and second.ended  # chunks 4..8 arrived on the NEW stream and it was closed properly
    assert rec.finals == [("me", "final:5", "cs-CZ")]


def test_a_stream_that_keeps_breaking_reports_once_and_gives_up(live_pair):
    streams = [DyingStream(1) for _ in range(5)]
    client = SequenceClient(streams)  # type: ignore[arg-type]
    live, rec = live_pair(client)  # type: ignore[arg-type]
    live.feed("me", GateEvent("start"))
    for i in range(1, 9):
        live.feed("me", audio(i))
    live.feed("me", GateEvent("end"))
    rec.wait(lambda: rec.errors)
    time.sleep(0.2)
    assert len(rec.errors) == 1 and client.calls == 3  # the first try and MAX_REOPEN (2) retries, then it stops


class HangingStream(FakeStream):
    """Sends block and nothing ever returns: a socket that went silent without an error."""

    async def send_audio_event(self, audio_chunk: bytes) -> None:
        self.chunks.append(audio_chunk)
        await asyncio.sleep(3600)

    async def end_stream(self) -> None:
        await asyncio.sleep(3600)


def test_a_stream_that_hangs_is_replaced_and_the_sentence_still_arrives():
    """A socket that went silent (no error, sends block): after the time limit a NEW stream takes over the same
    sentence, so the text is not lost and nothing stays stuck."""
    streams: list[FakeStream] = []

    class Client:
        calls = 0

        async def start_stream_transcription(self, **kwargs: object) -> FakeStream:
            Client.calls += 1
            s = HangingStream() if Client.calls == 1 else FakeStream()
            streams.append(s)
            return s

    creds = SimpleNamespace(**dict.fromkeys(("access_key", "secret_key", "token"), "fake"))
    tr = SimpleNamespace(region="x", langs=["cs-CZ"], credentials=lambda: creds)
    rec = Rec()
    live = LiveTranscriber(tr, lambda *a: rec.partials.append(a), lambda *a: rec.finals.append(a),  # type: ignore[arg-type]
                           rec.errors.append, client_factory=lambda r, k: Client(), grace_sec=0.3, open_sec=0.3)
    try:
        live.feed("me", GateEvent("start"))
        live.feed("me", audio(1))
        live.feed("me", GateEvent("end"))
        rec.wait(lambda: rec.finals, timeout=6)  # about open_sec, not "never"
        assert rec.finals == [("me", "final:1", "cs-CZ")] and rec.errors == [] and Client.calls == 2
        assert streams[1].ended  # the new stream was closed properly
        live.feed("me", GateEvent("start"))  # and the next sentence works as usual
        live.feed("me", audio(2))
        live.feed("me", GateEvent("end"))
        rec.wait(lambda: len(rec.finals) == 2, timeout=6)
        assert live._current == {} or all(u.ended for u in live._current.values())  # nothing is stuck
    finally:
        live.close()


def test_a_service_that_never_answers_after_the_end_is_reported_once_and_released():
    """The stream accepts everything but returns nothing at all: after the grace time the sentence is given up."""

    class Mute(FakeStream):
        async def end_stream(self) -> None:
            self.ended = True  # accepted, but no final and no close ever comes back

    class Client:
        async def start_stream_transcription(self, **kwargs: object) -> FakeStream:
            return Mute()

    creds = SimpleNamespace(**dict.fromkeys(("access_key", "secret_key", "token"), "fake"))
    tr = SimpleNamespace(region="x", langs=["cs-CZ"], credentials=lambda: creds)
    rec = Rec()
    live = LiveTranscriber(tr, lambda *a: rec.partials.append(a), lambda *a: rec.finals.append(a),  # type: ignore[arg-type]
                           rec.errors.append, client_factory=lambda r, k: Client(), grace_sec=0.3, open_sec=0.3)
    try:
        live.feed("me", GateEvent("start"))
        live.feed("me", GateEvent("end"))
        rec.wait(lambda: rec.errors, timeout=6)
        time.sleep(0.2)
        assert len(rec.errors) == 1 and "no result" in str(rec.errors[0])
        assert live._current == {}  # the sentence was released
    finally:
        live.close()
