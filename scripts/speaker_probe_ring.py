# scripts/speaker_probe_ring.py
"""Ring measurement of scripts/speaker_probe.py (numpy only): which pixels of a Teams tile edge to look at and how to turn
them into aggregate numbers (mean colour, spread, saturation, share of 'Teams border blue' pixels). Nothing here keeps pixels."""
from __future__ import annotations

import numpy as np

Rect = tuple[int, int, int, int]  # left, top, right, bottom
# mean RGB, std (0..255 scale), mean saturation (0..1), fraction of border-coloured pixels (0..1)
Stats = tuple[tuple[int, int, int], float, float, float]

# Teams draws its speaker border in the brand colour: #7F85F5 (127,133,245) dark theme, #5B5FC7 (91,95,199) light theme;
# hue about 237 degrees in both. A real tile showed that colour on about 43% of a thin ring, the rest being dark background.
HUE_RANGE = (215.0, 265.0)  # degrees
MIN_SATURATION = 0.35
MIN_VALUE = 0.40

RING_WIDTH = 6  # px: wide and starting at the very edge, so a border of 2-3 px that is thicker than, offset from or
RING_INSET = 0  # rounded off a thin ring is still covered whole (the dark pixels around it only lower the fraction)


def ring_pixels(img: np.ndarray, rect: Rect, inset: int = RING_INSET, edge_fraction: float = 0.8,
                width: int = RING_WIDTH) -> np.ndarray:
    """Pixels (N x 3) of a band `width` px thick that starts `inset` px inside the tile edge, on the middle `edge_fraction`
    of each of the 4 edges (rounded corners are skipped). A negative inset reaches outside the tile. Parts outside the
    image are cut off; a rect completely outside gives an empty array."""
    height, wide = img.shape[:2]
    left, top, right, bottom = (int(v) for v in rect)
    if right <= left or bottom <= top:
        return np.empty((0, 3), np.uint8)
    skip_x = int((right - left) * (1 - edge_fraction) / 2)
    skip_y = int((bottom - top) * (1 - edge_fraction) / 2)
    x0, x1, y0, y1 = left + skip_x, right - skip_x, top + skip_y, bottom - skip_y
    bands = [(x0, x1, top + inset, top + inset + width), (x0, x1, bottom - inset - width, bottom - inset),
             (left + inset, left + inset + width, y0, y1), (right - inset - width, right - inset, y0, y1)]
    parts = []
    for bx0, bx1, by0, by1 in bands:
        bx0, by0, bx1, by1 = max(bx0, 0), max(by0, 0), min(bx1, wide), min(by1, height)
        if bx1 > bx0 and by1 > by0:
            parts.append(img[by0:by1, bx0:bx1, :3].reshape(-1, 3))
    return np.concatenate(parts) if parts else np.empty((0, 3), np.uint8)


def border_fraction(pixels: np.ndarray) -> float:
    """Fraction (0..1) of the pixels that are Teams border blue: HSV hue within HUE_RANGE, saturation >= MIN_SATURATION and
    value >= MIN_VALUE. Grey, dark, skin, green and red pixels do not qualify."""
    if len(pixels) == 0:
        return 0.0
    r, g, b = (pixels[:, i].astype(np.float32) for i in range(3))
    top, low = pixels.max(axis=1).astype(np.float32), pixels.min(axis=1).astype(np.float32)
    spread = top - low
    blue_max = (b >= r) & (b >= g) & (spread > 0)  # hues 215..265 always have blue as the strongest channel
    hue = 60.0 * ((r - g) / np.where(spread > 0, spread, 1.0) + 4.0)
    ok = (blue_max & (hue >= HUE_RANGE[0]) & (hue <= HUE_RANGE[1]) & (spread >= MIN_SATURATION * top)
          & (top >= MIN_VALUE * 255.0))
    return float(ok.mean())


def ring_stats(pixels: np.ndarray) -> Stats:
    """Mean RGB, spread (mean over the channels of the std across the pixels), mean saturation (HSV) and border_fraction."""
    if len(pixels) == 0:
        return (0, 0, 0), 0.0, 0.0, 0.0
    pix = pixels.astype(np.float32)
    top, low = pix.max(axis=1), pix.min(axis=1)
    sat = np.where(top > 0, (top - low) / np.maximum(top, 1.0), 0.0)
    r, g, b = (round(float(v)) for v in pix.mean(axis=0))
    return (r, g, b), float(pix.std(axis=0).mean()), float(sat.mean()), border_fraction(pixels)
