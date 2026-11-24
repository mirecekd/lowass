# tests/test_record_loopback_core.py
"""scripts.record_loopback_core: downmix, resampling without seams, the WAV sink and the sidecar."""
from __future__ import annotations

import json
import wave

import numpy as np
import pytest
from scipy.signal import resample_poly

from scripts.record_loopback_core import (
    MonoResampler,
    WavSink,
    silence_frames,
    to_mono_16k,
    write_sidecar,
)


def sine(freq: float, rate: int, seconds: float, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(rate * seconds)) / rate
    return np.rint(amp * 32767 * np.sin(2 * np.pi * freq * t)).astype(np.int16)


def peak_freq(x: np.ndarray, rate: int = 16000) -> float:
    spectrum = np.abs(np.fft.rfft(x.astype(np.float64) * np.hanning(len(x))))
    return float(np.argmax(spectrum)) * rate / len(x)


def stream_in_blocks(x: np.ndarray, rate: int, block_sec: float) -> np.ndarray:
    r, step, parts = MonoResampler(1, rate), int(rate * block_sec), []
    for i in range(0, len(x), step):
        parts.append(r.push(x[i:i + step].tobytes()))
    parts.append(r.flush())
    return np.concatenate(parts)


def test_mono_passthrough_at_16k():
    x = sine(440, 16000, 0.5)
    assert np.array_equal(to_mono_16k(x.tobytes(), 1, 16000), x)


def test_stereo_is_averaged():
    left, right = np.full(160, 1000, np.int16), np.full(160, 3000, np.int16)
    out = to_mono_16k(np.column_stack([left, right]).tobytes(), 2, 16000)
    assert out.dtype == np.int16
    assert np.all(out == 2000)


def test_one_silent_channel_is_not_dropped():
    left = sine(440, 16000, 0.2)
    out = to_mono_16k(np.column_stack([left, np.zeros_like(left)]).tobytes(), 2, 16000)
    assert abs(int(np.max(out)) - int(np.max(left)) // 2) <= 1


@pytest.mark.parametrize("rate", [48000, 44100])
def test_length_within_one_sample(rate):
    x = sine(440, rate, 2.0)
    assert abs(len(to_mono_16k(x.tobytes(), 1, rate)) - 32000) <= 1


@pytest.mark.parametrize("rate", [48000, 44100])
def test_sine_frequency_preserved(rate):
    out = to_mono_16k(sine(1000, rate, 2.0).tobytes(), 1, rate)
    assert abs(peak_freq(out[1000:-1000]) - 1000) < 5


def test_surround_channels_downmix_to_mono():
    x = sine(440, 48000, 1.0)
    out = to_mono_16k(np.tile(x[:, None], (1, 8)).tobytes(), 8, 48000)
    assert abs(len(out) - 16000) <= 1


@pytest.mark.parametrize(("rate", "block_sec"), [(48000, 0.05), (44100, 0.05), (44100, 1.0)])
def test_no_seam_at_block_joins(rate, block_sec):
    """Consecutive blocks resampled one after another equal one pass over the whole signal."""
    x = sine(1000, rate, 3.0, amp=0.8)
    whole = to_mono_16k(x.tobytes(), 1, rate).astype(np.int32)
    blocks = stream_in_blocks(x, rate, block_sec).astype(np.int32)
    assert abs(len(blocks) - len(whole)) <= 1
    n = min(len(blocks), len(whole))
    assert np.max(np.abs(blocks[:n] - whole[:n])) <= 2
    # no step larger than the steepest slope of this sine, so the joins are smooth
    max_step = 0.8 * 32767 * 2 * np.pi * 1000 / 16000
    assert np.max(np.abs(np.diff(blocks[500:-500]))) <= max_step + 3


def test_plain_block_resample_has_a_seam():
    """Why MonoResampler exists: resample_poly per block treats the block edge as silence and jumps at the join."""
    x = sine(1100, 48000, 1.0, amp=0.8).astype(np.float64)
    whole = resample_poly(x, 1, 3)
    naive = np.concatenate([resample_poly(x[:23001], 1, 3), resample_poly(x[23001:], 1, 3)])
    assert np.max(np.abs(naive - whole)[100:-100]) > 1000  # the error sits at the join (a split at a sine zero would hide it)


def test_partial_frame_is_carried_over():
    x = sine(440, 16000, 0.2)
    raw = x.tobytes()
    r = MonoResampler(1, 16000)
    out = np.concatenate([r.push(raw[:101]), r.push(raw[101:]), r.flush()])
    assert np.array_equal(out, x)


def test_silence_frames_keep_the_file_on_the_wall_clock():
    assert silence_frames(16000 * 10, 10.1) == 0  # within the slack: buffering, not a gap
    assert silence_frames(16000 * 10, 12.0) == 32000  # the loopback was silent for 2 s: pad them
    assert silence_frames(16000 * 12, 10.0) == 0  # never negative


def test_wav_sink_roundtrip_and_double_close(tmp_path):
    path = tmp_path / "a.wav"
    sink = WavSink(path)
    sink.write(sine(440, 16000, 0.5))
    sink.write(np.zeros(0, np.int16))
    sink.write(sine(440, 16000, 0.5))
    assert sink.duration == pytest.approx(1.0)
    sink.close()
    sink.close()
    sink.write(sine(440, 16000, 0.5))  # ignored after close
    with wave.open(str(path), "rb") as wf:
        assert (wf.getnchannels(), wf.getsampwidth(), wf.getframerate(), wf.getnframes()) == (1, 2, 16000, 16000)


def test_sidecar_fields(tmp_path):
    path = tmp_path / "rec.json"
    write_sidecar(path, 1700000000.123, "Headphones [Loopback]", None, 12.34567)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "start_epoch": 1700000000.123, "rate": 16000, "channels": 1, "device": "Headphones [Loopback]",
        "mic_file": None, "duration": 12.346}
