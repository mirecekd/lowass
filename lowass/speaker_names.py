# lowass/speaker_names.py
"""Map lit-up speaker names (from speaker_probe events) to time windows."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Interval:
    start: float
    end: float | None = None  # None while the interval is open


class SpeakerTimeline:
    """Keeps per-name lit intervals and attributes time windows to a name."""

    def __init__(self, history_seconds: float = 600.0, min_overlap: float = 0.4):
        self.history_seconds = history_seconds
        self.min_overlap = min_overlap
        self._intervals: dict[str, list[_Interval]] = {}
        self._newest = float("-inf")

    def feed(self, event: dict) -> None:
        name = event["name"]
        t = float(event["t"])
        intervals = self._intervals.setdefault(name, [])
        last = intervals[-1] if intervals else None
        is_open = last is not None and last.end is None
        if event["speaking"]:
            if not is_open:
                intervals.append(_Interval(t))
        elif last is not None and is_open and t >= last.start:
            last.end = t
        else:
            return
        self._newest = max(self._newest, t)
        self._prune()

    def _prune(self) -> None:
        cutoff = self._newest - self.history_seconds
        for name in list(self._intervals):
            kept = [
                iv for iv in self._intervals[name] if iv.end is None or iv.end >= cutoff
            ]
            if kept:
                self._intervals[name] = kept
            else:
                del self._intervals[name]

    def who(self, t0: float, t1: float) -> str | None:
        best_name: str | None = None
        best_lit = 0.0
        best_start = 0.0
        for name, intervals in self._intervals.items():
            lit = 0.0
            first_start: float | None = None
            for iv in intervals:
                end = t1 if iv.end is None else min(iv.end, t1)
                overlap = end - max(iv.start, t0)
                if overlap > 0:
                    lit += overlap
                    if first_start is None:
                        first_start = iv.start
            if first_start is None:
                continue
            if lit > best_lit or (lit == best_lit and first_start < best_start):
                best_name, best_lit, best_start = name, lit, first_start
        if best_name is None or best_lit < self.min_overlap:
            return None
        return best_name

    def lit_now(self, now: float) -> str | None:
        best_name: str | None = None
        best_lit = 0.0
        for name, intervals in self._intervals.items():
            if intervals and intervals[-1].end is None:
                lit = now - intervals[-1].start
                if best_name is None or lit > best_lit:
                    best_name, best_lit = name, lit
        return best_name


def display(label: str, name: str | None) -> str:
    """Return the speaker name when known, otherwise the fallback label."""
    return name if name else label
