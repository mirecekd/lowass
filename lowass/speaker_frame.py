# lowass/speaker_frame.py
"""Per-frame helpers shared by scripts/speaker_probe.py and lowass/speaker_watch.py: clip the meeting window to the screen,
grab it as an RGB array and measure the ring of every participant tile. Only aggregate numbers leave this module; no pixels
are kept, printed or logged. Linux-importable (mss is only used through the object the caller passes in)."""
from __future__ import annotations

from scripts.speaker_probe_ring import Rect, Stats, ring_pixels, ring_stats

RECT_REFRESH_SECONDS = 2.0  # how often the UIA tile rectangles are read again


def grab_box(sct, window: Rect):
    """Window rectangle clipped to the virtual desktop as an mss monitor dict (None when nothing of it is on screen)."""
    desk = sct.monitors[0]
    left, top = max(window[0], desk["left"]), max(window[1], desk["top"])
    right, bottom = min(window[2], desk["left"] + desk["width"]), min(window[3], desk["top"] + desk["height"])
    if right <= left or bottom <= top:
        return None
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def grab_rgb(sct, box):
    import numpy as np

    shot = sct.grab(box)
    return np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[:, :, [2, 1, 0]]


def measure_tiles(img, box: dict, rects: dict[str, Rect], warned: set) -> tuple[dict[str, Stats], list[str]]:
    """Ring statistics of every tile in one frame. Also returns the names of tiles that are partly outside the grabbed box
    for the first time (they are added to `warned`, so each name is reported once); their ring is cut."""
    stats: dict[str, Stats] = {}
    outside: list[str] = []
    for name, (left, top, right, bottom) in rects.items():
        rel = (left - box["left"], top - box["top"], right - box["left"], bottom - box["top"])
        if (rel[0] < 0 or rel[1] < 0 or rel[2] > box["width"] or rel[3] > box["height"]) and name not in warned:
            warned.add(name)
            outside.append(name)
        stats[name] = ring_stats(ring_pixels(img, rel))
    return stats, outside
