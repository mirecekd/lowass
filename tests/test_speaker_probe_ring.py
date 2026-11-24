# tests/test_speaker_probe_ring.py
"""Ring geometry and border_fraction of scripts/speaker_probe_ring.py (fake data only)."""
import numpy as np
import pytest

from scripts.speaker_probe_ring import border_fraction, ring_pixels, ring_stats


def fraction_of(*rgb) -> float:
    return border_fraction(np.array([rgb], np.uint8))


@pytest.mark.parametrize("rgb", [(127, 133, 245), (91, 95, 199), (0, 0, 255), (110, 110, 255)])
def test_brand_blue_passes(rgb):
    assert fraction_of(*rgb) == 1.0


@pytest.mark.parametrize("rgb", [(0, 0, 0), (47, 46, 46), (128, 128, 128), (255, 255, 255), (224, 172, 105), (30, 160, 60),
                                 (200, 40, 40), (10, 10, 30), (150, 150, 170), (0, 128, 255), (200, 0, 255), (240, 240, 20)])
def test_other_colours_do_not_pass(rgb):
    assert fraction_of(*rgb) == 0.0


def test_fraction_is_the_share_of_blue_pixels():
    pixels = np.array([(127, 133, 245)] * 43 + [(47, 46, 46)] * 57, np.uint8)
    assert border_fraction(pixels) == pytest.approx(0.43)
    assert ring_stats(pixels)[3] == pytest.approx(0.43)
    assert border_fraction(np.empty((0, 3), np.uint8)) == 0.0


def test_stats_of_a_mixture_keep_mean_std_and_saturation():
    pixels = np.array([(127, 133, 245)] * 43 + [(47, 46, 46)] * 57, np.uint8)
    rgb, std, sat, _frac = ring_stats(pixels)
    assert rgb == (81, 83, 132)
    assert std > 60
    assert 0.2 < sat < 0.3


def test_ring_covers_a_border_thicker_than_the_ring_start():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:4] = (127, 133, 245)  # 4 px border at the very top edge
    ring = ring_pixels(img, (0, 0, 100, 100))
    assert (ring == (127, 133, 245)).all(axis=1).sum() >= 4 * 80  # all 4 rows of the middle 80% of the top edge
    assert border_fraction(ring) == pytest.approx(4 * 82 / len(ring))


def test_ring_skips_the_corners():
    img = np.zeros((100, 100, 3), np.uint8)
    img[:6, :6] = 255  # a corner square only
    assert not ring_pixels(img, (0, 0, 100, 100), edge_fraction=0.8).any()


def test_rect_partly_or_fully_off_screen_does_not_raise():
    img = np.zeros((200, 200, 3), np.uint8)
    partly = ring_pixels(img, (-50, -50, 150, 150))
    assert 0 < len(partly) < len(ring_pixels(img, (0, 0, 200, 200)))
    assert len(ring_pixels(img, (5000, 5000, 5200, 5200))) == 0
    assert len(ring_pixels(img, (50, 50, 50, 50))) == 0
    assert ring_stats(ring_pixels(img, (5000, 5000, 5200, 5200))) == ((0, 0, 0), 0.0, 0.0, 0.0)
