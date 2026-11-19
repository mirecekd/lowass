# lowass/audio.py
"""WASAPI capture (microphone + loopback) with simple RMS VAD. Windows only at runtime."""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any

import numpy as np

from .dsp import prepare_audio_chunk, to_wav_bytes

log = logging.getLogger("lowass.audio")


def find_wasapi_devices(p: Any, pyaudio: Any) -> tuple[dict, dict]:
    """Default microphone and the WASAPI loopback of the default headphones."""
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    mic = p.get_device_info_by_index(wasapi["defaultInputDevice"])
    spk = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if not spk["isLoopbackDevice"]:
        for lb in p.get_loopback_device_info_generator():
            if spk["name"] in lb["name"]:
                spk = lb
                break
    return mic, spk


def open_input_stream(p: Any, pyaudio: Any, info: dict) -> tuple[Any, int, int, int]:
    rate = int(info["defaultSampleRate"])
    channels = max(1, int(info["maxInputChannels"]))
    chunk = int(rate * 0.05)  # 50 ms
    stream = p.open(format=pyaudio.paInt16, channels=channels, rate=rate,
                    frames_per_buffer=chunk, input=True, input_device_index=info["index"])
    return stream, rate, channels, chunk


class Segmenter:
    """Feeds 16 kHz mono chunks, emits a WAV when a sentence ends. Pure logic, testable."""

    def __init__(self, threshold: float, silence_sec: float, max_sec: float, min_speech: float):
        self.threshold, self.silence_sec, self.max_sec, self.min_speech = threshold, silence_sec, max_sec, min_speech
        self.buf: list[np.ndarray] = []
        self.silence = 0.0
        self.speech = 0.0
        self.speaking = False
        self.dropped = 0  # segments thrown away because speech was shorter than min_speech

    def feed(self, audio: np.ndarray, rms: float, chunk_sec: float) -> bytes | None:
        if rms > self.threshold:
            self.speaking, self.silence = True, 0.0
        elif not self.speaking:
            return None
        else:
            self.silence += chunk_sec
        self.buf.append(audio)
        self.speech += chunk_sec
        if self.silence < self.silence_sec and self.speech < self.max_sec:
            return None
        keep = self.speech - self.silence >= self.min_speech
        out = to_wav_bytes(np.concatenate(self.buf)) if keep else None
        if not keep:
            self.dropped += 1
        self.buf, self.silence, self.speech, self.speaking = [], 0.0, 0.0, False
        return out


def capture_worker(label: str, stream: Any, rate: int, channels: int, chunk: int, seg: Segmenter,
                   out: queue.Queue[tuple[str, bytes]], stop: threading.Event, stats: Any = None) -> None:
    chunk_sec = chunk / rate
    log.info("capture '%s' started: %d Hz, %d ch, chunk %d frames, threshold %.4f", label, rate, channels, chunk, seg.threshold)
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
        dropped_before = seg.dropped
        wav = seg.feed(mono, rms, chunk_sec)
        if seg.dropped != dropped_before:
            log.debug("'%s': speech too short, dropped", label)
            if stats:
                stats.segment(label, False)
        if wav:
            log.debug("'%s': segment %.1f KB queued for STT", label, len(wav) / 1024)
            if stats:
                stats.segment(label, True)
            out.put((label, wav))
