# lowass/audio_live.py
"""Capture thread for LIVE transcription: audio goes through the Gate and is streamed while the person speaks."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

from .dsp import prepare_audio_chunk
from .gate import Gate, GateEvent

log = logging.getLogger("lowass.audio")


def to_pcm16(audio: np.ndarray) -> bytes:
    """float32 mono (-1..1) -> int16 little-endian. NOT normalised: a per-chunk gain would pump the volume."""
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()


def capture_live(label: str, stream: Any, rate: int, channels: int, chunk: int, gate: Gate, live: Any,
                 stop: threading.Event, stats: Any = None, paused: Callable[[], bool] | None = None) -> None:
    """Reads the device, cuts utterances with the gate and hands the events to `live` (LiveTranscriber.feed).

    While `paused()` is true (the Private button) the device is still read, so it keeps running and the debug counters
    stay honest, but NOTHING is processed or sent; a running utterance is discarded."""
    chunk_sec = chunk / rate
    log.info("live capture '%s' started: %d Hz, %d ch, chunk %d frames", label, rate, channels, chunk)
    was_paused = False
    while not stop.is_set():
        try:
            raw = stream.read(chunk, exception_on_overflow=False)
        except OSError:
            if stop.is_set():
                return
            raise
        mono, rms = prepare_audio_chunk(raw, channels, rate)
        if stats:
            stats.chunk(label, rms)
        if paused is not None and paused():
            if not was_paused and gate.flush():
                live.feed(label, GateEvent("end", kept=False))  # discard what was being said when Private went on
            was_paused = True
            continue
        was_paused = False
        for event in gate.feed(to_pcm16(mono), rms, chunk_sec):
            if event.kind == "end" and stats:
                stats.segment(label, event.kept)
            live.feed(label, event)
