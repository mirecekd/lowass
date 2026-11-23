# tests/test_audio_probe.py
"""describe_device (the log line about a headset) and the argument rules of the probe script: no Windows needed."""
import pytest

from lowass.audio import describe_device
from scripts.audio_probe import parse


def test_the_device_line_has_the_rate_and_channels_and_never_raises_on_missing_keys():
    line = describe_device({"name": "Headset Microphone (Jabra EVOLVE 30 II)", "index": 18, "defaultSampleRate": 48000.0,
                            "maxInputChannels": 4, "maxOutputChannels": 0, "isLoopbackDevice": False})
    assert "rate=48000.0" in line and "in=4" in line and "Jabra" in line and "loopback=False" in line
    assert "?" in describe_device({})  # a device without those keys is still described
    assert describe_device({"name": "x"}).startswith("x | ")


def test_the_probe_opens_nothing_unless_asked_and_both_means_mic_and_loopback():
    with pytest.raises(SystemExit):
        parse([])  # nothing to open is an error, not a silent no-op
    a = parse(["--both"])
    assert a.mic and a.loopback and a.mic_channels == 0 and a.seconds == 20.0
    assert parse(["--mic", "--mic-channels", "1"]).mic_channels == 1
    only = parse(["--loopback", "--seconds", "5"])
    assert only.loopback and not only.mic and only.seconds == 5.0


def test_the_probe_can_list_devices_open_one_by_number_and_set_the_rate():
    assert parse(["--list"]).list is True
    a = parse(["--device", "8", "--rate", "16000"])
    assert a.device == 8 and a.rate == 16000 and not a.mic and not a.loopback
    assert parse(["--mic"]).device == -1 and parse(["--mic"]).rate == 0  # the defaults are what LOWASS uses
    with pytest.raises(SystemExit):
        parse(["--rate", "16000"])  # a rate alone opens nothing
