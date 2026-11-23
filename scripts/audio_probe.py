# scripts/audio_probe.py
"""Which audio stream of LOWASS makes the headset sound like in a tunnel? Opens ONLY what you ask for, keeps it open and
lets you listen. Run it on Windows from the project folder, with music playing in the headphones:

  python -m scripts.audio_probe --list                     every input device with its number, API and rate
  python -m scripts.audio_probe --mic                      the default WASAPI microphone, as LOWASS opens it
  python -m scripts.audio_probe --loopback                 the loopback of the headphones only
  python -m scripts.audio_probe --device 8                 ANY input device by its number from --list
  python -m scripts.audio_probe --device 8 --rate 16000    the same at another rate (when the device accepts it)

Listen while it runs (default 20 s). The device format is printed before and after the streams are opened. Nothing is
recorded or sent anywhere."""
from __future__ import annotations

import argparse
import sys
import time


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="audio_probe", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list the input devices and exit")
    ap.add_argument("--mic", action="store_true", help="open the default WASAPI microphone")
    ap.add_argument("--loopback", action="store_true", help="open the loopback of the default headphones")
    ap.add_argument("--both", action="store_true", help="open both (like LOWASS)")
    ap.add_argument("--device", type=int, default=-1, help="open this device number (from --list)")
    ap.add_argument("--mic-channels", type=int, default=0, help="channels of the stream (0 = the device maximum, like LOWASS)")
    ap.add_argument("--rate", type=int, default=0, help="sample rate of the stream (0 = the device default, like LOWASS)")
    ap.add_argument("--seconds", type=float, default=20.0, help="how long to keep the streams open")
    args = ap.parse_args(argv)
    if args.both:
        args.mic = args.loopback = True
    if not (args.list or args.mic or args.loopback or args.device >= 0):
        ap.error("say what to do: --list, --mic, --loopback, --both or --device N")
    return args


def api_name(p, info) -> str:
    return str(p.get_host_api_info_by_index(info["hostApi"]).get("name", "?"))


def list_inputs(p) -> None:
    from lowass.audio import describe_device

    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        if int(info["maxInputChannels"]) > 0:
            print(f"[{i:2}] {api_name(p, info):24} {describe_device(info)}")


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    import pyaudiowpatch as pyaudio  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]  # Windows only

    from lowass.audio import describe_device, find_wasapi_devices

    p = pyaudio.PyAudio()
    if args.list:
        list_inputs(p)
        p.terminate()
        return 0
    mic, loop = find_wasapi_devices(p, pyaudio)
    wanted = [(name, info) for name, info, on in (("mic", mic, args.mic), ("loopback", loop, args.loopback)) if on]
    if args.device >= 0:
        wanted.append((f"device {args.device}", p.get_device_info_by_index(args.device)))
    for name, info in wanted:
        print(f"BEFORE {name} [{api_name(p, info)}]: {describe_device(info)}")
    streams = []
    for name, info in wanted:
        channels = args.mic_channels if name != "loopback" and args.mic_channels > 0 else max(1, int(info["maxInputChannels"]))
        rate = args.rate or int(info["defaultSampleRate"])
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
