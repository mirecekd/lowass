# lowass/dsp.py
"""Pure audio helpers (no audio devices): safe to import and test anywhere."""
from __future__ import annotations

import io
import wave
from math import gcd

import numpy as np
from scipy.signal import resample_poly


def prepare_audio_chunk(raw_bytes: bytes, channels: int, orig_rate: int) -> tuple[np.ndarray, float]:
    """Raw PCM int16 -> mono float32 16 kHz and its RMS loudness."""
    audio = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        # headsets may carry the voice in one channel only: take the stronger one
        reshaped = audio.reshape(-1, channels)
        ch_rms = np.sqrt(np.mean(reshaped ** 2, axis=0))
        audio = reshaped[:, np.argmax(ch_rms).item()]
    if orig_rate != 16000:
        common = gcd(16000, orig_rate)
        audio = resample_poly(audio, 16000 // common, orig_rate // common).astype(np.float32)
    return audio, np.sqrt(np.mean(audio ** 2)).item()


def normalize_audio(audio: np.ndarray, target_peak: float = 0.7) -> np.ndarray:
    peak = np.max(np.abs(audio)).item()
    if peak > 1e-5:
        audio = audio * min(target_peak / peak, 25.0)
    return np.clip(audio, -1.0, 1.0)


def to_wav_bytes(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    pcm = np.clip(normalize_audio(audio) * 32767.0, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()
