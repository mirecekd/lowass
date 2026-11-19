# lowass/gate.py
"""Speech gate for LIVE streaming: turns 16 kHz mono PCM chunks into start / audio / end events.

GateEvent is the contract between the gate (cuts the audio into utterances) and lowass/live.py (one Transcribe stream
per utterance). Everything here is pure logic: no devices, no network.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class GateEvent:
    kind: str          # "start" | "audio" | "end"
    pcm: bytes = b""   # int16 little-endian mono 16 kHz; set for "audio"
    kept: bool = True  # only for "end": False = the utterance was too short and must be discarded


_EPS = 1e-9  # tolerance for summed float chunk lengths


class Gate:
    """Cuts a stream of PCM chunks into utterances by loudness (rms > threshold = speech)."""

    def __init__(self, threshold: float, silence_sec: float, max_sec: float,
                 min_speech: float, preroll_sec: float = 0.3) -> None:
        self._threshold = threshold
        self._silence_sec = silence_sec
        self._max_sec = max_sec
        self._min_speech = min_speech
        self._preroll_sec = preroll_sec
        self._preroll: deque[tuple[bytes, float]] = deque()
        self._preroll_total = 0.0
        self._speaking = False
        self._total = 0.0     # seconds fed since the utterance started (pre-roll not counted)
        self._trailing = 0.0  # seconds of silence at the end of the utterance so far

    def feed(self, pcm: bytes, rms: float, chunk_sec: float) -> list[GateEvent]:
        loud = rms > self._threshold
        if not self._speaking:
            if not loud:
                self._remember(pcm, chunk_sec)
                return []
            audio = b"".join(chunk for chunk, _ in self._preroll) + pcm
            self._preroll.clear()
            self._preroll_total = 0.0
            self._speaking = True
            self._total = 0.0
            self._trailing = 0.0
            events = [GateEvent("start"), GateEvent("audio", pcm=audio)]
        else:
            events = [GateEvent("audio", pcm=pcm)]
        self._total += chunk_sec
        self._trailing = 0.0 if loud else self._trailing + chunk_sec
        if self._trailing >= self._silence_sec - _EPS or self._total >= self._max_sec - _EPS:
            events.extend(self.flush())
        return events

    def flush(self) -> list[GateEvent]:
        if not self._speaking:
            return []
        speech = self._total - self._trailing
        self._speaking = False
        self._total = 0.0
        self._trailing = 0.0
        return [GateEvent("end", kept=speech >= self._min_speech - _EPS)]

    def _remember(self, pcm: bytes, chunk_sec: float) -> None:
        self._preroll.append((pcm, chunk_sec))
        self._preroll_total += chunk_sec
        while len(self._preroll) > 1 and self._preroll_total - self._preroll[0][1] >= self._preroll_sec - _EPS:
            _, dropped_sec = self._preroll.popleft()
            self._preroll_total -= dropped_sec
