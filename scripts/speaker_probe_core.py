# scripts/speaker_probe_core.py
"""Pure logic of scripts/speaker_probe.py (numpy only, no Windows): measures a ring of pixels just inside the edge of a
Teams participant tile and decides from a solid, saturated, uniform ring (the border Teams draws around the active speaker)
that the tile is speaking. Works on aggregate numbers only; nothing here keeps or saves pixels."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from statistics import median

import numpy as np

from scripts.meeting_log_core import parse_tile
from scripts.ui_probe_tree import Node

Rect = tuple[int, int, int, int]  # left, top, right, bottom
Stats = tuple[tuple[int, int, int], float, float]  # mean RGB, std (0..255 scale), mean saturation (0..1)

STD_LIMIT = 25.0  # a ring whose pixels spread by this much (std) or more is video content, not a flat border


def read_rects(nodes: Iterable[Node]) -> dict[str, Rect]:
    """Participant name -> screen rectangle of its tile (MenuItem tiles of a UIA snapshot, like meeting_log reads them)."""
    rects: dict[str, Rect] = {}
    for node in nodes:
        tile = parse_tile(node.name) if node.control_type == "MenuItem" else None
        if tile and tile.name not in rects:
            rects[tile.name] = node.rect
    return rects


def ring_pixels(img: np.ndarray, rect: Rect, inset: int = 1, edge_fraction: float = 0.8, width: int = 2) -> np.ndarray:
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


def ring_stats(pixels: np.ndarray) -> Stats:
    """Mean RGB, uniformity (mean over the channels of the std across the pixels) and mean saturation (HSV) of a ring."""
    if len(pixels) == 0:
        return (0, 0, 0), 0.0, 0.0
    pix = pixels.astype(np.float32)
    top, low = pix.max(axis=1), pix.min(axis=1)
    sat = np.where(top > 0, (top - low) / np.maximum(top, 1.0), 0.0)
    r, g, b = (round(float(v)) for v in pix.mean(axis=0))
    return (r, g, b), float(pix.std(axis=0).mean()), float(sat.mean())


def score(std: float, sat: float) -> float:
    """0..1: high only when the ring is saturated AND uniform."""
    return float(sat) * max(0.0, 1.0 - float(std) / STD_LIMIT)


@dataclass
class _TileState:
    samples: deque = field(default_factory=deque)  # (t, score) while not speaking: the tile's own baseline
    speaking: bool = False
    streak: int = 0  # consecutive frames that stood out
    last_hit: float = 0.0


class SpeakerTracker:
    """feed(t, {name: Stats}) -> speaking / stopped events {"t", "name", "speaking"}.

    A tile stands out in a frame when its score is at least min_score and exceeds both its own baseline (median of the
    scores of the last baseline_seconds, frozen while it is speaking) and the median score of the other tiles by margin;
    of those tiles only the ones near the best score count. Speaking starts after on_frames consecutive such frames
    (never before min_samples baseline frames, so a permanently coloured tile is not mistaken) and ends after
    off_seconds without one."""

    def __init__(self, baseline_seconds: float = 10.0, min_samples: int = 5, min_score: float = 0.25, margin: float = 0.2,
                 on_frames: int = 2, off_seconds: float = 1.0, near_best: float = 0.8) -> None:
        self.baseline_seconds, self.min_samples, self.min_score, self.margin = baseline_seconds, min_samples, min_score, margin
        self.on_frames, self.off_seconds, self.near_best = on_frames, off_seconds, near_best
        self._tiles: dict[str, _TileState] = {}

    def _standing_out(self, scores: dict[str, float]) -> set[str]:
        found = {}
        for name, value in scores.items():
            tile = self._tiles[name]
            if value < self.min_score or len(tile.samples) < self.min_samples:
                continue
            others = [v for n, v in scores.items() if n != name]
            baseline = median(s for _, s in tile.samples)
            if value - baseline >= self.margin and value - (median(others) if others else 0.0) >= self.margin:
                found[name] = value
        best = max(found.values(), default=0.0)
        return {name for name, value in found.items() if value >= self.near_best * best}

    def feed(self, t: float, stats: dict[str, Stats]) -> list[dict]:
        scores = {name: score(std, sat) for name, (_rgb, std, sat) in stats.items()}
        events = []
        for name in [n for n in self._tiles if n not in scores]:  # the tile left the gallery
            if self._tiles.pop(name).speaking:
                events.append({"t": t, "name": name, "speaking": False})
        for name in scores:
            self._tiles.setdefault(name, _TileState())
        hits = self._standing_out(scores)
        for name, value in scores.items():
            tile = self._tiles[name]
            tile.streak = tile.streak + 1 if name in hits else 0
            if name in hits:
                tile.last_hit = t
            if not tile.speaking and tile.streak >= self.on_frames:
                tile.speaking = True
                events.append({"t": t, "name": name, "speaking": True})
            elif tile.speaking and t - tile.last_hit >= self.off_seconds:
                tile.speaking = False
                events.append({"t": t, "name": name, "speaking": False})
            if not tile.speaking:
                tile.samples.append((t, value))
                while tile.samples and t - tile.samples[0][0] > self.baseline_seconds:
                    tile.samples.popleft()
        return events
