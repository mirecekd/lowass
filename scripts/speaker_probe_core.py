# scripts/speaker_probe_core.py
"""Pure logic of scripts/speaker_probe.py (numpy only, no Windows): decides from the share of 'Teams border blue' pixels
(scripts/speaker_probe_ring.py) on a thin ring around every participant tile which tile is speaking. Teams draws a coloured
border (brand blue-violet) around the active speaker. Works on aggregate numbers only; nothing here keeps or saves pixels.

What this method cannot do:
- Blue-ish VIDEO CONTENT on a tile edge that changes over time (a blue shirt moving to the edge, a blue screen share, a
  blue light switched on) raises the share like a border and can false-trigger; a tile whose edge is blue ALL the time is
  safe, because its own baseline is as high as its score.
- A tile that is already speaking when the tool starts is detected only after it was seen quiet once (its baseline is
  the border itself until enough quiet frames outweigh it); that first burst is missed, later ones are found.
- With only two tiles that both speak at once, each is the 'other tiles' median of the other, so none stands out.
- The speaker's own tile is not recognised if Teams hides the border (speaker / focus view, some themes)."""
from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np

from scripts.meeting_log_core import parse_tile
from scripts.speaker_probe_ring import Rect, Stats
from scripts.ui_probe_tree import Node

BASELINE_QUANTILE = 20.0  # percent: a low quantile, so a tile that was speaking at the start is not its own baseline for long


def read_rects(nodes: Iterable[Node]) -> dict[str, Rect]:
    """Participant name -> screen rectangle of its tile (MenuItem tiles of a UIA snapshot, like meeting_log reads them)."""
    rects: dict[str, Rect] = {}
    for node in nodes:
        tile = parse_tile(node.name) if node.control_type == "MenuItem" else None
        if tile and tile.name not in rects:
            rects[tile.name] = node.rect
    return rects


@dataclass
class _TileState:
    samples: deque = field(default_factory=deque)  # (t, fraction) while not speaking: the tile's own baseline
    speaking: bool = False
    streak: int = 0  # consecutive frames that stood out
    last_hit: float = 0.0


class SpeakerTracker:
    """feed(t, {name: Stats}) -> speaking / stopped events {"t", "name", "speaking"}.

    The tile score is the border-blue fraction of its ring (Stats[3]). A tile stands out in a frame when its score is at
    least min_score and exceeds both its own baseline (20th percentile of the scores of the last baseline_seconds, frozen
    while it is speaking) and the median score of the other tiles by margin; of those tiles only the ones within
    near_best of the best score count. Speaking starts after on_frames consecutive such frames (never before min_samples
    baseline frames, so a permanently coloured tile is not mistaken) and ends after off_seconds without one. The fade-in
    of a border (0.2 s per frame at 5 fps) therefore gives 'speaking' on its second frame.

    Thresholds: a real border covered about 43% of the ring (the rest was dark background), idle tiles 0%, so
    min_score 0.15 catches the first fade-in frame (17%) and margin 0.10 ignores noise of a few pixels; near_best 0.5 lets
    a second speaker with a thinner or partly hidden border count next to a full one."""

    def __init__(self, baseline_seconds: float = 30.0, min_samples: int = 5, min_score: float = 0.15, margin: float = 0.10,
                 on_frames: int = 2, off_seconds: float = 1.0, near_best: float = 0.5) -> None:
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
            baseline = float(np.percentile([s for _, s in tile.samples], BASELINE_QUANTILE))
            if value - baseline >= self.margin and value - (float(np.median(others)) if others else 0.0) >= self.margin:
                found[name] = value
        best = max(found.values(), default=0.0)
        return {name for name, value in found.items() if value >= self.near_best * best}

    def feed(self, t: float, stats: dict[str, Stats]) -> list[dict]:
        scores = {name: frac for name, (_rgb, _std, _sat, frac) in stats.items()}
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
