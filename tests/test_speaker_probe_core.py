# tests/test_speaker_probe_core.py
"""Speaker border detection of scripts/speaker_probe_core.py on synthetic tiles (noise 'video', violet border), fake names only."""
import numpy as np
import pytest

from scripts.speaker_probe_core import (
    SpeakerTracker,
    read_rects,
    ring_pixels,
    ring_stats,
    score,
)
from scripts.ui_probe_tree import Node

NAMES = ["Eva", "Anna", "Dora", "Boris", "Clara", "Filip"]  # tile 2 is Anna, tile 4 is Boris
TILE = 200
VIOLET = (120, 60, 220)
FPS = 5


def rects() -> dict[str, tuple[int, int, int, int]]:
    return {name: ((i % 3) * TILE, (i // 3) * TILE, (i % 3) * TILE + TILE, (i // 3) * TILE + TILE) for i, name in enumerate(NAMES)}


def canvas(rng, border=(), colourful=(), solid=()) -> np.ndarray:
    """6 tiles of grey noise; `colourful` tiles have random-colour noise (saturated, not uniform), `solid` tiles are one
    colour all over, `border` tiles get a 3 px violet border."""
    img = np.zeros((2 * TILE, 3 * TILE, 3), np.uint8)
    for name, (left, top, right, bottom) in rects().items():
        if name in colourful:
            img[top:bottom, left:right] = rng.integers(0, 256, (TILE, TILE, 3), dtype=np.uint8)
        elif name in solid:
            img[top:bottom, left:right] = VIOLET
        else:
            img[top:bottom, left:right] = rng.integers(0, 256, (TILE, TILE, 1), dtype=np.uint8)
        if name in border:
            img[top:bottom, left:right][:3] = VIOLET
            img[top:bottom, left:right][-3:] = VIOLET
            img[top:bottom, left:right][:, :3] = VIOLET
            img[top:bottom, left:right][:, -3:] = VIOLET
    return img


def measure(img) -> dict:
    return {name: ring_stats(ring_pixels(img, rect)) for name, rect in rects().items()}


def run(plan, **canvas_kwargs) -> list[tuple[str, bool]]:
    """plan: border names per frame; returns (name, speaking) events in order."""
    rng = np.random.default_rng(1)
    tracker = SpeakerTracker()
    events = []
    for i, border in enumerate(plan):
        events += [(e["name"], e["speaking"]) for e in tracker.feed(i / FPS, measure(canvas(rng, border, **canvas_kwargs)))]
    return events


QUIET = [()] * 30  # 6 s of baseline


def test_speaker_changes_from_anna_to_boris():
    plan = QUIET + [("Anna",)] * 20 + [()] * 10 + [("Boris",)] * 20 + [()] * 10
    assert run(plan) == [("Anna", True), ("Anna", False), ("Boris", True), ("Boris", False)]


def test_noise_tiles_never_speak():
    assert run([()] * 100) == []


def test_naturally_saturated_but_not_uniform_edge_is_ignored():
    assert run([()] * 100, colourful=("Dora",)) == []


@pytest.mark.parametrize("kwargs", [{"solid": ("Dora",)}, {"colourful": ("Dora",), "solid": ("Filip",)}])
def test_tile_that_is_always_coloured_is_not_speaking(kwargs):
    assert run([()] * 100, **kwargs) == []


def test_always_coloured_tile_does_not_hide_a_real_speaker():
    plan = QUIET + [("Anna",)] * 20 + [()] * 10
    assert run(plan, solid=("Dora",)) == [("Anna", True), ("Anna", False)]


def test_single_frame_flicker_is_ignored():
    assert run(QUIET + [("Anna",)] + [()] * 20) == []


def test_short_gap_does_not_stop_speaking():
    plan = QUIET + [("Anna",)] * 10 + [()] * 3 + [("Anna",)] * 10 + [()] * 10
    assert run(plan) == [("Anna", True), ("Anna", False)]


def test_two_speakers_at_once_both_count():
    plan = QUIET + [("Anna", "Boris")] * 10 + [()] * 10
    assert sorted(run(plan)) == [("Anna", False), ("Anna", True), ("Boris", False), ("Boris", True)]


def test_tile_leaving_while_speaking_stops_it():
    tracker = SpeakerTracker()
    rng = np.random.default_rng(2)
    for i in range(30):
        tracker.feed(i / FPS, measure(canvas(rng)))
    for i in range(30, 36):
        tracker.feed(i / FPS, measure(canvas(rng, border=("Anna",))))
    stats = measure(canvas(rng, border=("Anna",)))
    del stats["Anna"]
    assert tracker.feed(7.0, stats) == [{"t": 7.0, "name": "Anna", "speaking": False}]


def test_ring_of_a_border_is_saturated_and_uniform():
    rgb, std, sat = ring_stats(ring_pixels(canvas(np.random.default_rng(3), border=("Anna",)), rects()["Anna"]))
    assert rgb == VIOLET
    assert std == 0.0
    assert sat == pytest.approx(160 / 220)
    assert score(std, sat) == pytest.approx(sat)


def test_ring_of_noise_scores_zero():
    _rgb, std, sat = ring_stats(ring_pixels(canvas(np.random.default_rng(4)), rects()["Dora"]))
    assert score(std, sat) == 0.0


def test_ring_skips_the_corners():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:6, :6] = 255  # a corner square only
    assert not ring_pixels(img, (0, 0, 100, 100), inset=1, edge_fraction=0.8).any()


def test_rect_partly_or_fully_off_screen_does_not_raise():
    img = canvas(np.random.default_rng(5))
    partly = ring_pixels(img, (-50, -50, 150, 150))
    assert 0 < len(partly) < len(ring_pixels(img, (0, 0, 200, 200)))
    assert len(ring_pixels(img, (5000, 5000, 5200, 5200))) == 0
    assert len(ring_pixels(img, (50, 50, 50, 50))) == 0
    assert ring_stats(ring_pixels(img, (5000, 5000, 5200, 5200))) == ((0, 0, 0), 0.0, 0.0)


def test_read_rects_takes_tile_menu_items_only():
    tile = "Anna Novak, video je zapnuté, ztlumený mikrofon, K dispozici je kontextová nabídka."
    nodes = [Node("MenuItem", tile, "", "", (10, 20, 110, 90), "p"), Node("Button", tile, "", "", (0, 0, 1, 1), "p"),
             Node("MenuItem", "Settings", "", "", (0, 0, 5, 5), "p")]
    assert read_rects(nodes) == {"Anna Novak": (10, 20, 110, 90)}
