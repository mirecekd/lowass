# lowass/live.py
"""Live Amazon Transcribe streaming: the audio is sent WHILE the person speaks, so partial results appear at once.

One asyncio loop runs in one worker thread. Every sentence (gate events start .. end) of a speaker is an Utterance run
by lowass/live_stream.py (which also survives a connection that breaks in the middle); a speaker has at most one OPEN
sentence: a new 'start' closes the previous one.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable
from typing import Any

from lowass.gate import GateEvent
from lowass.live_stream import (
    GRACE_SEC,
    OPEN_SEC,
    Callback,
    Utterance,
    UtteranceRunner,
    real_client,
)
from lowass.transcribe import Transcriber

log = logging.getLogger("lowass.live")


class LiveTranscriber:
    def __init__(self, tr: Transcriber, on_partial: Callback, on_final: Callback,
                 on_error: Callable[[BaseException], None], client_factory: Callable[[str, Any], Any] | None = None,
                 grace_sec: float = GRACE_SEC, open_sec: float = OPEN_SEC):
        self._on_error = on_error
        self._current: dict[str, Utterance] = {}
        self._all: set[Utterance] = set()
        self._closed = False
        self._loop = asyncio.new_event_loop()
        self._runner = UtteranceRunner(tr, self._loop, client_factory or real_client, on_partial, on_final,
                                       self._report, self._finished, grace_sec, open_sec)
        self._thread = threading.Thread(target=self._loop.run_forever, name="live-transcribe", daemon=True)
        self._thread.start()

    def feed(self, speaker: str, event: GateEvent) -> None:
        """Thread-safe and never blocks: the event is handed over to the worker loop."""
        if self._closed:
            return
        with contextlib.suppress(RuntimeError):  # the loop is already closed
            self._loop.call_soon_threadsafe(self._dispatch, speaker, event)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        done = threading.Event()

        async def shutdown() -> None:
            tasks = [u.task for u in self._all if u.task is not None]
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            done.set()

        self._loop.call_soon_threadsafe(lambda: self._loop.create_task(shutdown()))
        done.wait(5)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)
        if not self._thread.is_alive():
            self._loop.close()

    def _dispatch(self, speaker: str, event: GateEvent) -> None:
        cur = self._current.get(speaker)
        if event.kind == "start":
            if cur is not None and not cur.ended:  # one open sentence per speaker: close the previous one first
                cur.ended = True
                cur.events.put_nowait(GateEvent("end", kept=True))
            utt = Utterance()
            self._current[speaker] = utt
            self._all.add(utt)
            utt.task = self._loop.create_task(self._runner.run(speaker, utt))
            return
        if cur is None or cur.ended:
            return  # audio or end without an open sentence
        if event.kind == "end":
            cur.ended = True
        cur.events.put_nowait(event)

    def _finished(self, speaker: str, utt: Utterance) -> None:
        if self._current.get(speaker) is utt:
            del self._current[speaker]
        self._all.discard(utt)

    def _report(self, exc: BaseException) -> None:
        log.error("live transcribe error: %s: %s", type(exc).__name__, exc)
        try:
            self._on_error(exc)
        except Exception:  # a broken callback must not kill the worker
            log.exception("on_error callback failed")
