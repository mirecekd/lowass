# tests/test_speaker_probe_replay.py
"""Replay of the first real Windows run of scripts/speaker_probe (numbers only): a speaking ring was about 43% border blue
(127,133,245) and the rest dark background (47,46,46); the border faded in over 0.4 s at 5 fps. Fake names only."""
import numpy as np
import pytest

from scripts.speaker_probe_core import SpeakerTracker
from scripts.speaker_probe_ring import ring_stats

RING_PIXELS = 1000
FPS = 5
BLUE = (127, 133, 245)
LIGHT_BLUE = (91, 95, 199)
BACKGROUND = (47, 46, 46)
FADE_IN = [0.17, 0.4]  # then 0.43 steady
FULL = 0.43
NAMES = ["Anna", "Boris", "Clara", "Dora", "Eva", "Filip", "Gita", "Hana"]


def ring(fraction: float, colour=BLUE) -> tuple:
    """Stats of a synthetic ring in which `fraction` of the pixels have the border colour."""
    blue = round(fraction * RING_PIXELS)
    pixels = np.array([colour] * blue + [BACKGROUND] * (RING_PIXELS - blue), np.uint8)
    return ring_stats(pixels)


def replay(frames: list[dict[str, float]], colour=BLUE) -> list[tuple[float, str, bool]]:
    """frames: border fraction per tile name, one dict per frame; returns (t, name, speaking) events."""
    tracker = SpeakerTracker()
    events = []
    for i, fractions in enumerate(frames):
        stats = {name: ring(f, colour) for name, f in fractions.items()}
        events += [(e["t"], e["name"], e["speaking"]) for e in tracker.feed(i / FPS, stats)]
    return events


def tiles(**fractions: float) -> dict[str, float]:
    return {name: fractions.get(name, 0.0) for name in NAMES}


IDLE = [tiles()] * 50  # 10 s of quiet


def test_real_ring_stats_match_the_measured_speaking_numbers():
    rgb, std, sat, frac = ring(FULL)
    assert rgb == pytest.approx((80, 83, 131), abs=2)  # measured (79,82,138): the real border was a bit more violet
    assert std > 60
    assert sat > 0.2
    assert frac == pytest.approx(FULL)
    assert ring(0.0) == (BACKGROUND, 0.0, pytest.approx(0.0215, abs=0.001), 0.0)


def test_fade_in_gives_speaking_within_the_second_frame_and_fade_out_stops_it():
    frames = IDLE + [tiles(Anna=f) for f in FADE_IN] + [tiles(Anna=FULL)] * 40 + [tiles(Anna=0.02)] + [tiles()] * 20
    events = replay(frames)
    assert [(name, speaking) for _t, name, speaking in events] == [("Anna", True), ("Anna", False)]
    border_starts = len(IDLE) / FPS
    assert events[0][0] - border_starts <= 0.6
    assert events[1][0] - (len(IDLE) + 2 + 40) / FPS <= 1.4


def test_light_theme_replay():
    frames = IDLE + [tiles(Anna=f) for f in FADE_IN] + [tiles(Anna=FULL)] * 20 + [tiles()] * 20
    assert [e[1:] for e in replay(frames, colour=LIGHT_BLUE)] == [("Anna", True), ("Anna", False)]


def test_one_bordered_tile_among_eight():
    frames = IDLE + [tiles(Eva=FULL)] * 20 + [tiles()] * 20
    assert [e[1:] for e in replay(frames)] == [("Eva", True), ("Eva", False)]


def test_two_bordered_tiles_are_both_speaking():
    frames = IDLE + [tiles(Boris=FULL, Gita=0.35)] * 20 + [tiles()] * 20
    events = [e[1:] for e in replay(frames)]
    assert sorted(events) == [("Boris", False), ("Boris", True), ("Gita", False), ("Gita", True)]


def test_tile_that_is_always_blue_never_fires():
    wobble = [0.40, 0.46, 0.43, 0.44, 0.41] * 40  # the blue shirt moves a little, never leaves the edge
    assert replay([tiles(Dora=f) for f in wobble]) == []


def test_always_blue_tile_does_not_hide_a_real_speaker():
    frames = [tiles(Dora=FULL)] * 50 + [tiles(Dora=FULL, Anna=f) for f in FADE_IN] + [tiles(Dora=FULL, Anna=FULL)] * 20
    assert [e[1:] for e in replay(frames)] == [("Anna", True)]


def test_tile_speaking_at_the_start_is_found_on_its_next_burst():
    first_burst = [tiles(Anna=FULL)] * 20  # 4 s: swallowed, its baseline is still the border itself
    frames = first_burst + IDLE + [tiles(Anna=FULL)] * 20 + [tiles()] * 20
    events = [e[1:] for e in replay(frames)]
    assert events == [("Anna", True), ("Anna", False)]


def test_single_frame_of_blue_is_ignored():
    assert replay(IDLE + [tiles(Anna=FULL)] + IDLE) == []
