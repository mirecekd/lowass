# scripts/record_loopback_core.py
"""Pure helpers of scripts.record_loopback (no audio devices, testable anywhere): int16 PCM -> mono 16 kHz, a WAV sink
and the sidecar json."""
from __future__ import annotations

import json
import wave
from math import ceil, gcd
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

TARGET_RATE = 16000


class MonoResampler:
    """int16 little-endian interleaved PCM -> mono int16 at 16 kHz, in blocks of any size.

    Mono is the mean of the channels (nothing is dropped, nothing is normalised or gated). The rate change is
    resample_poly with the exact rational ratio (48000 -> 1/3, 44100 -> 160/441). resample_poly on separate blocks
    treats each block edge as silence and leaves a dip at every join, so every block is filtered together with
    `margin` input samples of context on both sides: the context is kept from the previous call and the newest
    `margin` samples are only emitted by the next call (or by flush). The margin is a multiple of the decimation
    factor, so the polyphase phase is the same as in one pass over the whole signal."""

    def __init__(self, channels: int, rate: int):
        self.channels = max(1, channels)
        common = gcd(TARGET_RATE, rate)
        self.up, self.down = TARGET_RATE // common, rate // common
        half_filter = 10 * max(self.up, self.down) // self.up  # resample_poly filter half-length in input samples
        self.margin = self.down * ceil((half_filter + 8) / self.down)
        self._buf = np.zeros(0)
        self._skip = 0  # input samples at the start of _buf that were already emitted (context only)
        self._tail = b""  # a partial frame left from the previous call

    def _mono(self, raw: bytes) -> np.ndarray:
        raw = self._tail + raw
        usable = len(raw) - len(raw) % (2 * self.channels)
        self._tail = raw[usable:]
        pcm = np.frombuffer(raw[:usable], dtype="<i2").astype(np.float64)
        return pcm.reshape(-1, self.channels).mean(axis=1)

    @staticmethod
    def _to_int16(x: np.ndarray) -> np.ndarray:
        return np.clip(np.rint(x), -32768, 32767).astype(np.int16)

    def push(self, raw: bytes) -> np.ndarray:
        self._buf = np.concatenate([self._buf, self._mono(raw)])
        if self.up == self.down:
            out, self._buf = self._buf, np.zeros(0)
            return self._to_int16(out)
        end = (len(self._buf) - self.margin) // self.down * self.down  # emit up to here; the rest is look-ahead
        if end <= self._skip:
            return np.zeros(0, dtype=np.int16)
        full = resample_poly(self._buf, self.up, self.down)
        out = full[self._skip * self.up // self.down:end * self.up // self.down]
        keep = max(0, end - self.margin)
        self._buf, self._skip = self._buf[keep:], end - keep
        return self._to_int16(out)

    def flush(self) -> np.ndarray:
        """The end of the signal: the look-ahead is real silence now."""
        if self.up == self.down or len(self._buf) <= self._skip:
            return np.zeros(0, dtype=np.int16)
        out = resample_poly(self._buf, self.up, self.down)[self._skip * self.up // self.down:]
        self._buf, self._skip = np.zeros(0), 0
        return self._to_int16(out)


def to_mono_16k(raw: bytes, channels: int, rate: int) -> np.ndarray:
    """A whole recording (or any block) of int16 interleaved PCM -> mono int16 16 kHz."""
    r = MonoResampler(channels, rate)
    return np.concatenate([r.push(raw), r.flush()])


def silence_frames(written: int, elapsed_sec: float, rate: int = TARGET_RATE, slack_sec: float = 0.3) -> int:
    """How many silent frames keep the file on the wall clock. A loopback of a silent output delivers no data at all;
    without padding the file would be shorter than the meeting and every later time would be off. Nothing is added
    while the file is within slack_sec of the clock (device buffering, the resampler look-ahead)."""
    lag = int(elapsed_sec * rate) - written
    return lag if lag > slack_sec * rate else 0


class WavSink:
    """A 16 kHz mono 16-bit WAV writer. close() may be called twice; the header is finalised by the first call."""

    def __init__(self, path: Path, rate: int = TARGET_RATE):
        self.path, self.rate, self.frames = Path(path), rate, 0
        self._wav: wave.Wave_write | None = wave.open(str(self.path), "wb")  # noqa: SIM115 - open until close()
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(rate)

    @property
    def duration(self) -> float:
        return self.frames / self.rate

    def write(self, samples: np.ndarray) -> None:
        if self._wav is not None and len(samples):
            self._wav.writeframes(samples.astype("<i2").tobytes())
            self.frames += len(samples)

    def close(self) -> None:
        if self._wav is not None:
            self._wav.close()
            self._wav = None


def write_sidecar(path: Path, start_epoch: float, device: str, mic_file: str | None, duration: float) -> None:
    """The json next to the WAV; start_epoch is what aligns the audio with a timeline of UI events."""
    data = {"start_epoch": start_epoch, "rate": TARGET_RATE, "channels": 1, "device": device,
            "mic_file": mic_file, "duration": round(duration, 3)}
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
