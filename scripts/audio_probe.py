# scripts/audio_probe.py
"""Which audio stream of LOWASS makes the headset sound like in a tunnel? Opens ONLY what you ask for, keeps it open and
lets you listen. Run it on Windows from the project folder, with music playing in the headphones:

  python -m scripts.audio_probe --mic                      the microphone, opened exactly as LOWASS opens it
  python -m scripts.audio_probe --loopback                 the loopback of the headphones only
  python -m scripts.audio_probe --both                     both, as LOWASS does
  python -m scripts.audio_probe --mic --mic-channels 1     the microphone as ONE channel instead of its maximum

Listen while it runs (default 20 s). The device format is printed before and after the streams are opened. Nothing is
recorded or sent anywhere."""
from __future__ import annotations

import argparse
import sys
import time


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="audio_probe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mic", action="store_true", help="open the microphone")
    ap.add_argument("--loopback", action="store_true", help="open the loopback of the default headphones")
    ap.add_argument("--both", action="store_true", help="open both (like LOWASS)")
    ap.add_argument("--mic-channels", type=int, default=0, help="channels of the microphone stream (0 = the device maximum, like LOWASS)")
    ap.add_argument("--seconds", type=float, default=20.0, help="how long to keep the streams open")
    args = ap.parse_args(argv)
    if args.both:
        args.mic = args.loopback = True
    if not (args.mic or args.loopback):
        ap.error("say what to open: --mic, --loopback or --both")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    import pyaudiowpatch as pyaudio  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]  # Windows only

    from lowass.audio import describe_device, find_wasapi_devices

    p = pyaudio.PyAudio()
    mic, loop = find_wasapi_devices(p, pyaudio)
    wanted = [(name, info) for name, info, on in (("mic", mic, args.mic), ("loopback", loop, args.loopback)) if on]
    for name, info in wanted:
        print(f"BEFORE {name}: {describe_device(info)}")
    streams = []
    for name, info in wanted:
        channels = args.mic_channels if name == "mic" and args.mic_channels > 0 else max(1, int(info["maxInputChannels"]))
        rate = int(info["defaultSampleRate"])
        chunk = int(rate * 0.05)  # 50 ms, like LOWASS
        streams.append((name, chunk, p.open(format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
                                            input_device_index=info["index"], frames_per_buffer=chunk)))
        print(f"OPENED {name}: {channels} channel(s) at {rate} Hz")
    for name, info in wanted:
        print(f"AFTER  {name}: {describe_device(p.get_device_info_by_index(info['index']))}")
    print(f"\nLISTEN NOW for {args.seconds:.0f} s: does the music in the headphones sound worse than before?")
    end = time.monotonic() + args.seconds
    while time.monotonic() < end:
        for _name, chunk, stream in streams:
            stream.read(chunk, exception_on_overflow=False)
    for _name, _chunk, stream in streams:
        stream.stop_stream()
        stream.close()
    p.terminate()
    print("closed. Does the sound recover at once? (that tells whether it is the OPEN stream or a state that stays)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
