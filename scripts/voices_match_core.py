# scripts/voices_match_core.py
"""Pure logic of voice naming by the mute timeline: who was unmuted when, evidence per voice and name, assignment.
No sherpa-onnx import here.

A person can only be heard while unmuted. Every moment a voice speaks, the people unmuted at that moment share the
moment equally (weight 1/k for k unmuted people), so a moment with one open mic is strong evidence and a moment with
six open mics is weak. The evidence matrix is then resolved one-to-one with the Hungarian algorithm."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from scripts.voices_core import Segment

Intervals = dict[str, list[tuple[float, float]]]
EPSILON = 1e-9


def load_timeline(path: Path, start_epoch: float, duration: float) -> Intervals:
    """Unmuted intervals per name in audio seconds (0 .. duration), from the jsonl state-change timeline.

    A name is unmuted while its last state line says present and not muted; the state holds until its next line
    and, after the last line, until the end of the audio. Lines with an 'event' key are ignored."""
    events = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "event" not in row:
            events.append(row)
    end_epoch = start_epoch + duration
    result: Intervals = {}
    open_since: dict[str, float | None] = {}
    for row in sorted(events, key=lambda r: r["t"]):
        name = row["name"]
        result.setdefault(name, [])
        unmuted = bool(row.get("present", True)) and not bool(row.get("muted", True))
        opened = open_since.get(name)
        if unmuted and opened is None:
            open_since[name] = row["t"]
        elif not unmuted and opened is not None:
            result[name].append((opened, row["t"]))
            open_since[name] = None
    for name, opened in open_since.items():
        if opened is not None:
            result[name].append((opened, end_epoch))
    return {name: _to_audio_time(spans, start_epoch, duration) for name, spans in result.items()}


def _to_audio_time(spans: list[tuple[float, float]], start_epoch: float, duration: float) -> list[tuple[float, float]]:
    clipped = [(max(a - start_epoch, 0.0), min(b - start_epoch, duration)) for a, b in spans]
    return [(a, b) for a, b in clipped if b > a]


def evidence_matrix(
    segments: list[Segment], intervals: Mapping[str, Sequence[tuple[float, float]]]
) -> tuple[list[str], list[int | str], np.ndarray]:
    """(names, speakers, matrix) where matrix[i, j] is the weighted seconds speaker i spoke while name j was unmuted.

    Each stretch of a segment during which k people are unmuted gives every one of them duration / k seconds.
    Speakers are in order of first appearance, names in the order of the timeline."""
    names = list(intervals)
    speakers = list(dict.fromkeys(s.speaker for s in sorted(segments, key=lambda s: s.start)))
    matrix = np.zeros((len(speakers), len(names)))
    for seg in segments:
        row = speakers.index(seg.speaker)
        cuts = {seg.start, seg.end}
        for spans in intervals.values():
            cuts.update(edge for span in spans for edge in span if seg.start < edge < seg.end)
        points = sorted(cuts)
        for a, b in pairwise(points):
            middle = (a + b) / 2
            open_cols = [j for j, name in enumerate(names) if any(s <= middle < e for s, e in intervals[name])]
            for j in open_cols:
                matrix[row, j] += (b - a) / len(open_cols)
    return names, speakers, matrix


@dataclass(frozen=True)
class Match:
    """Result for one speaker (matrix row). col is the matrix column picked by the assignment, None if no name has
    evidence for it. known is False when confidence is below the minimum, then the voice should be shown as unknown."""
    row: int
    col: int | None
    confidence: float
    evidence: float
    runner_up: int | None
    known: bool


def _best_total(matrix: np.ndarray) -> tuple[float, list[tuple[int, int]]]:
    rows, cols = linear_sum_assignment(matrix, maximize=True)
    pairs = [(int(r), int(c)) for r, c in zip(rows, cols, strict=True) if matrix[r, c] > EPSILON]
    return sum(matrix[r, c] for r, c in pairs), pairs


def assign(matrix: np.ndarray, min_confidence: float) -> list[Match]:
    """One-to-one assignment of speakers (rows) to names (columns) maximising the total evidence, one Match per row.

    Confidence of the pair (row, col) is the share of the row's total evidence that the assignment would lose if
    this pair were forbidden and everything else re-optimised: (best total - best total without the pair) / row
    total, within 0..1. Without competition from other voices it is (best name - second best name) / total evidence
    of the voice. When another voice competes for the same name, the margin is measured against that voice taking
    the name instead. Rows with no evidence, or fewer than min_confidence, are not known."""
    if matrix.size == 0:
        return [Match(row, None, 0.0, 0.0, None, False) for row in range(matrix.shape[0])]
    best, pairs = _best_total(matrix)
    picked = dict(pairs)
    matches = []
    for row in range(matrix.shape[0]):
        col = picked.get(row)
        others = [(matrix[row, j], j) for j in range(matrix.shape[1]) if j != col and matrix[row, j] > EPSILON]
        runner_up = max(others)[1] if others else None
        if col is None:
            matches.append(Match(row, None, 0.0, 0.0, runner_up, False))
            continue
        without = matrix.copy()
        without[row, col] = 0.0
        confidence = float(np.clip((best - _best_total(without)[0]) / matrix[row].sum(), 0.0, 1.0))
        matches.append(Match(row, col, confidence, float(matrix[row, col]), runner_up, confidence >= min_confidence - EPSILON))
    return matches
