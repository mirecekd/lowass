# lowass/live_stream.py
"""One sentence on Transcribe: open a stream, send the audio WHILE it is spoken, continue on a NEW stream when one breaks.

A connection can die in the middle of a sentence (AWS_IO_SOCKET_TIMEOUT) or go silent without any error. Both are
handled: the event that could not be sent is kept (`carry`) and goes first to the new stream, finals already delivered
stay, and no stream may live longer than its sentence plus a short grace time, so nothing stays stuck.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from amazon_transcribe.auth import StaticCredentialResolver
from amazon_transcribe.client import TranscribeStreamingClient

from lowass.gate import GateEvent
from lowass.transcribe import LOGIN_ERRORS, Transcriber, stream_kwargs

log = logging.getLogger("lowass.live")

Callback = Callable[[str, str, str | None], None]

MAX_REOPEN = 2          # how many times one sentence may be continued on a new stream
GRACE_SEC = 8.0         # after the sentence ended: how long the service may take to return the last results
OPEN_SEC = 10.0         # opening a stream, or one send, must not take longer than this
MAX_UTTERANCE_SEC = 60  # no sentence lives longer than this, whatever happens


def real_client(region: str, creds: Any) -> TranscribeStreamingClient:
    return TranscribeStreamingClient(region=region,
                                     credential_resolver=StaticCredentialResolver(creds.access_key, creds.secret_key, creds.token))


class NoRetry(Exception):
    """A failure a new stream would repeat (it hung, or the results were lost): report it and give up on this sentence."""


class Utterance:
    """Events of one sentence wait here (also while a stream is being opened) until the task sends them."""

    def __init__(self) -> None:
        self.events: asyncio.Queue[GateEvent | None] = asyncio.Queue()  # None = a stream's receiver stopped
        self.carry: GateEvent | None = None  # taken from the queue but not sent: goes first to the next stream
        self.ended = False
        self.discarded = False
        self.task: asyncio.Task[None] | None = None
        self.started_at = time.monotonic()


class UtteranceRunner:
    def __init__(self, tr: Transcriber, loop: asyncio.AbstractEventLoop, client_factory: Callable[[str, Any], Any],
                 on_partial: Callback, on_final: Callback, on_error: Callable[[BaseException], None],
                 on_done: Callable[[str, Utterance], None], grace_sec: float = GRACE_SEC, open_sec: float = OPEN_SEC):
        self._tr, self._loop, self._client_factory = tr, loop, client_factory
        self._on_partial, self._on_final, self._on_error, self._on_done = on_partial, on_final, on_error, on_done
        self._grace, self._open_sec = grace_sec, open_sec

    async def run(self, speaker: str, utt: Utterance) -> None:
        failures = 0
        try:
            while True:
                try:
                    await self._stream(speaker, utt)
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - one broken stream must not stop the worker
                    if utt.discarded:
                        return
                    failures += 1
                    log.warning("stream of %s failed (%d): %s: %s", speaker, failures, type(exc).__name__, exc)
                    if failures > MAX_REOPEN or isinstance(exc, (NoRetry, *LOGIN_ERRORS)):
                        self._on_error(exc)
                        return
        finally:
            self._on_done(speaker, utt)

    async def _open(self) -> Any:
        creds = await asyncio.wait_for(self._loop.run_in_executor(None, self._tr.credentials), self._open_sec)
        client = self._client_factory(self._tr.region, creds)
        return await asyncio.wait_for(
            client.start_stream_transcription(media_sample_rate_hz=16000, media_encoding="pcm",
                                              **stream_kwargs(self._tr.langs)), self._open_sec)

    async def _stream(self, speaker: str, utt: Utterance) -> None:
        """Sends the queued events to ONE stream. Returns when the sentence is complete; raises when the stream broke."""
        stream = await self._open()
        receiver = self._loop.create_task(self._receive(speaker, utt, stream.output_stream))
        receiver.add_done_callback(lambda t: utt.events.put_nowait(None) if not t.cancelled() else None)
        try:
            while True:
                await asyncio.sleep(0)  # a receiver that has just failed gets to run before the next send
                ev = utt.carry or await self._next(utt)
                utt.carry = None
                if ev is None:
                    if not receiver.done():
                        continue  # a stale marker of an earlier stream
                    receiver.result()
                    raise ConnectionError("the stream was closed before the sentence ended")
                if receiver.done():  # the connection is gone: this event goes to the next stream
                    utt.carry = ev
                    receiver.result()
                    raise ConnectionError("the stream was closed before the sentence ended")
                if ev.kind == "audio":
                    await self._guard(utt, ev, stream.input_stream.send_audio_event(audio_chunk=ev.pcm))
                elif ev.kind == "end":
                    utt.discarded = not ev.kept
                    if utt.discarded:
                        return
                    await self._guard(utt, ev, stream.input_stream.end_stream())
                    await self._finish(receiver)
                    return
        finally:
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver

    async def _guard(self, utt: Utterance, ev: GateEvent, awaitable: Awaitable[Any]) -> None:
        """One send with a time limit; on failure the event is kept for the next stream."""
        try:
            await asyncio.wait_for(awaitable, self._open_sec)
        except asyncio.CancelledError:
            raise
        except Exception:
            utt.carry = ev
            raise

    async def _finish(self, receiver: asyncio.Task[None]) -> None:
        """After the end of the sentence: the last results may take a moment. If they never come, say so."""
        try:
            await asyncio.wait_for(asyncio.shield(receiver), self._grace)
        except TimeoutError:
            raise NoRetry(f"no result {self._grace:.0f} s after the sentence ended") from None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise NoRetry(f"the connection broke before the last results: {type(exc).__name__}: {exc}") from exc

    async def _next(self, utt: Utterance) -> GateEvent | None:
        age = time.monotonic() - utt.started_at
        limit = self._grace if utt.ended else max(0.5, MAX_UTTERANCE_SEC - age)
        try:
            return await asyncio.wait_for(utt.events.get(), limit)
        except TimeoutError:
            raise NoRetry(f"no audio for {limit:.0f} s, the stream is given up") from None

    async def _receive(self, speaker: str, utt: Utterance, output: Any) -> None:
        async for event in output:
            transcript = getattr(event, "transcript", None)
            for r in getattr(transcript, "results", None) or []:
                if utt.discarded or not r.alternatives:
                    continue
                text = r.alternatives[0].transcript
                lang = getattr(r, "language_code", None) or None
                (self._on_partial if r.is_partial else self._on_final)(speaker, text, lang)
