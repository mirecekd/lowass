# scripts/record_loopback.py
"""Record what the headphones play (WASAPI loopback of the default output, i.e. the other side of a Teams meeting) to a
16 kHz mono 16-bit WAV, optionally the microphone too. Nothing is normalised or gated. Run it on Windows:

  python -m scripts.record_loopback                   until Ctrl+C
  python -m scripts.record_loopback --seconds 600 --mic --out-dir data

Files: <out-dir>/rec-YYYYmmdd-HHMMSS.wav (+ -mic.wav) and rec-YYYYmmdd-HHMMSS.json. The json holds start_epoch (time.time()
when the first loopback chunk was read), which aligns the audio with a timeline of UI events. Gaps in the delivery of
the loopback (a silent output sends no data) are filled with silence so the file stays on the wall clock."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from scripts.record_loopback_core import (
    TARGET_RATE,
    MonoResampler,
    WavSink,
    silence_frames,
    write_sidecar,
)


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="record_loopback", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=0.0, help="stop after this many seconds (0 = until Ctrl+C)")
    ap.add_argument("--mic", action="store_true", help="also record the default microphone to a second WAV")
    ap.add_argument("--out-dir", type=Path, default=Path("data"), help="folder for the files (created if missing)")
    return ap.parse_args(argv)


class Tap:
    """One open input stream feeding one WAV through a resampler."""

    def __init__(self, stream: Any, rate: int, channels: int, path: Path):
        self.stream, self.resampler, self.sink = stream, MonoResampler(channels, rate), WavSink(path)
        self.rate = rate

    def drain(self, elapsed: float) -> bool:
        """Move what the device has ready into the WAV. Polls instead of a blocking read: a silent output delivers
        nothing, and a blocked read would hang Ctrl+C and --seconds. True when data was read."""
        ready = int(self.stream.get_read_available())
        if ready < 1:
            self.sink.write(np.zeros(silence_frames(self.sink.frames, elapsed), np.int16))
            return False
        gap = silence_frames(self.sink.frames, elapsed - ready / self.rate)  # a silent stretch before this data
        self.sink.write(np.zeros(gap, np.int16))
        self.sink.write(self.resampler.push(self.stream.read(ready, exception_on_overflow=False)))
        return True

    def discard(self) -> None:
        """Drop what is buffered (the mic before the first loopback chunk), so both files start together."""
        ready = int(self.stream.get_read_available())
        if ready > 0:
            self.stream.read(ready, exception_on_overflow=False)

    def finish(self) -> None:
        self.stream.stop_stream()
        self.stream.close()
        self.sink.write(self.resampler.flush())
        self.sink.close()


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    import pyaudiowpatch as pyaudio  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]  # Windows only

    from lowass.audio import describe_device, find_wasapi_devices, open_input_stream

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("rec-%Y%m%d-%H%M%S")
    wav_path, mic_path, json_path = (args.out_dir / f"{stamp}{ext}" for ext in (".wav", "-mic.wav", ".json"))
    p = pyaudio.PyAudio()
    mic_info, loop_info = find_wasapi_devices(p, pyaudio)
    print(f"loopback: {describe_device(loop_info)}")
    stream, rate, channels, _ = open_input_stream(p, pyaudio, loop_info)
    loop = Tap(stream, rate, channels, wav_path)
    mic = None
    if args.mic:
        print(f"mic:      {describe_device(mic_info)}")
        stream, rate, channels, _ = open_input_stream(p, pyaudio, mic_info)
        mic = Tap(stream, rate, channels, mic_path)
    taps = [loop] + ([mic] if mic else [])
    device, mic_name = str(loop_info["name"]), (mic_path.name if mic else None)
    start_epoch = 0.0
    started: float | None = None  # time.monotonic() of the first loopback chunk
    next_report = 5.0
    print(f"waiting for audio from the loopback ({'Ctrl+C to stop' if not args.seconds else f'{args.seconds:.0f} s'}) ...")
    try:
        while True:
            if started is None:
                if not int(loop.stream.get_read_available()):
                    time.sleep(0.01)
                    continue
                start_epoch, started = time.time(), time.monotonic()
                if mic:
                    mic.discard()
                write_sidecar(json_path, start_epoch, device, mic_name, 0.0)  # a kill still leaves an aligned sidecar
            elapsed = time.monotonic() - started
            got = [tap.drain(elapsed) for tap in taps]
            if elapsed >= next_report:
                print(f"recording {elapsed:.0f} s, Ctrl+C to stop")
                next_report += 5.0
            if args.seconds and elapsed >= args.seconds:
                break
            if not any(got):
                time.sleep(0.01)
    except KeyboardInterrupt:
        print("stopping ...")
    finally:
        for tap in taps:
            tap.finish()
        p.terminate()
        if started is not None:
            write_sidecar(json_path, start_epoch, device, mic_name, loop.sink.frames / TARGET_RATE)
    if started is None:
        print("no audio arrived from the loopback: is something playing in the headphones?")
        return 1
    print(f"saved {wav_path} ({loop.sink.duration:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
