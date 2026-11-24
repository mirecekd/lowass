# tests/test_speaker_probe_core.py
"""Speaker border detection of scripts/speaker_probe_core.py on synthetic tiles (noise 'video', blue-violet border), fake names only."""
import numpy as np
import pytest

from scripts.speaker_probe_core import SpeakerTracker, read_rects
from scripts.speaker_probe_ring import ring_pixels, ring_stats
from scripts.ui_probe_tree import Node

NAMES = ["Eva", "Anna", "Dora", "Boris", "Clara", "Filip"]  # tile 2 is Anna, tile 4 is Boris
TILE = 200
DARK_THEME = (127, 133, 245)  # Teams brand colour #7F85F5
LIGHT_THEME = (91, 95, 199)  # #5B5FC7
FPS = 5


def rects() -> dict[str, tuple[int, int, int, int]]:
    return {name: ((i % 3) * TILE, (i // 3) * TILE, (i % 3) * TILE + TILE, (i // 3) * TILE + TILE) for i, name in enumerate(NAMES)}


def canvas(rng, border=(), colourful=(), solid=(), colour=DARK_THEME) -> np.ndarray:
    """6 tiles of grey noise; `colourful` tiles have random-colour noise (saturated, not border-coloured), `solid` tiles are one
    colour all over, `border` tiles get a 3 px border of `colour`."""
    img = np.zeros((2 * TILE, 3 * TILE, 3), np.uint8)
    for name, (left, top, right, bottom) in rects().items():
        if name in colourful:
            img[top:bottom, left:right] = rng.integers(0, 256, (TILE, TILE, 3), dtype=np.uint8)
        elif name in solid:
            img[top:bottom, left:right] = colour
        else:
            img[top:bottom, left:right] = rng.integers(0, 256, (TILE, TILE, 1), dtype=np.uint8)
        if name in border:
            img[top:bottom, left:right][:3] = colour
            img[top:bottom, left:right][-3:] = colour
            img[top:bottom, left:right][:, :3] = colour
            img[top:bottom, left:right][:, -3:] = colour
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


def test_light_theme_border_is_found():
    plan = QUIET + [("Anna",)] * 20 + [()] * 10
    assert run(plan, colour=LIGHT_THEME) == [("Anna", True), ("Anna", False)]


def test_noise_tiles_never_speak():
    assert run([()] * 100) == []


def test_naturally_saturated_but_not_border_coloured_edge_is_ignored():
    assert run([()] * 100, colourful=("Dora",)) == []


@pytest.mark.parametrize("kwargs", [{"solid": ("Dora",)}, {"colourful": ("Dora",), "solid": ("Filip",)},
                                    {"solid": ("Dora",), "colour": LIGHT_THEME}])
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


def test_read_rects_takes_tile_menu_items_only():
    tile = "Anna Novak, video je zapnuté, ztlumený mikrofon, K dispozici je kontextová nabídka."
    nodes = [Node("MenuItem", tile, "", "", (10, 20, 110, 90), "p"), Node("Button", tile, "", "", (0, 0, 1, 1), "p"),
             Node("MenuItem", "Settings", "", "", (0, 0, 5, 5), "p")]
    assert read_rects(nodes) == {"Anna Novak": (10, 20, 110, 90)}
