# scripts/voices_core.py
"""Pure logic of the voices spike: segments, cosine matching, voice profiles. No sherpa-onnx import here."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

UNKNOWN = "unknown"


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    speaker: int | str

    @property
    def duration(self) -> float:
        return self.end - self.start


def merge_segments(segments: list[Segment], max_gap: float = 0.5) -> list[Segment]:
    """Join neighbouring segments of the same speaker when the pause between them is at most max_gap seconds."""
    merged: list[Segment] = []
    for seg in sorted(segments, key=lambda s: s.start):
        last = merged[-1] if merged else None
        if last and last.speaker == seg.speaker and seg.start - last.end <= max_gap:
            merged[-1] = Segment(last.start, max(last.end, seg.end), seg.speaker)
        else:
            merged.append(seg)
    return merged


def speaker_stats(segments: list[Segment]) -> dict[int | str, tuple[float, int]]:
    """speaker -> (total speaking seconds, number of segments)."""
    stats: dict[int | str, tuple[float, int]] = {}
    for seg in segments:
        total, count = stats.get(seg.speaker, (0.0, 0))
        stats[seg.speaker] = (total + seg.duration, count + 1)
    return stats


def longest(segments: list[Segment], speaker: int | str, count: int = 3) -> list[Segment]:
    own = [s for s in segments if s.speaker == speaker]
    return sorted(sorted(own, key=lambda s: -s.duration)[:count], key=lambda s: s.start)


def fmt_time(seconds: float) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"{int(minutes):02d}:{rest:04.1f}"


def fmt_range(seg: Segment) -> str:
    return f"{fmt_time(seg.start)}-{fmt_time(seg.end)}"


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b)) / denom if denom else 0.0


def mean_embedding(embeddings: list[np.ndarray], weights: list[float] | None = None) -> np.ndarray:
    """Weighted mean of the unit-length embeddings (the weight is usually the segment duration)."""
    units = np.array([e / (np.linalg.norm(e) or 1.0) for e in embeddings])
    return np.average(units, axis=0, weights=weights)


def load_profile(path: Path) -> dict[str, np.ndarray]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name: np.array(vec, dtype=np.float32) for name, vec in data["voices"].items()}


def save_profile(path: Path, voices: dict[str, np.ndarray], model: str) -> None:
    data = {"model": model, "voices": {name: [round(float(x), 6) for x in vec] for name, vec in voices.items()}}
    path.write_text(json.dumps(data), encoding="utf-8")


def match_voice(embedding: np.ndarray, voices: dict[str, np.ndarray], threshold: float) -> tuple[str, float]:
    """The profile name with the highest cosine similarity, or UNKNOWN when even the best one is below threshold."""
    best_name, best = UNKNOWN, -1.0
    for name, vec in voices.items():
        score = cosine(embedding, vec)
        if score > best:
            best_name, best = name, score
    return (best_name if best >= threshold else UNKNOWN), best


def timeline_lines(segments: list[Segment]) -> list[str]:
    return [f"[{fmt_time(s.start)}] {s.speaker}: ({s.duration:.1f}s)" for s in sorted(segments, key=lambda s: s.start)]


def purity(truth: list[Segment], hyp: list[Segment], step: float = 0.02) -> float:
    """Frame-level accuracy: every hypothesis label is mapped to the truth speaker it overlaps most, silence frames
    of the truth are ignored. Many-to-one mapping, so a split voice is not punished, a merged one is."""
    end = max(s.end for s in truth)
    frames = int(end / step) + 1
    t_lab = np.full(frames, -1)
    h_lab = np.full(frames, -1)
    t_names = sorted({str(s.speaker) for s in truth})
    h_names = sorted({str(s.speaker) for s in hyp})
    for seg in truth:
        t_lab[int(seg.start / step):int(seg.end / step)] = t_names.index(str(seg.speaker))
    for seg in hyp:
        h_lab[int(seg.start / step):min(int(seg.end / step), frames)] = h_names.index(str(seg.speaker))
    speech = t_lab >= 0
    correct = 0
    for h in range(len(h_names)):
        votes = np.bincount(t_lab[speech & (h_lab == h)], minlength=len(t_names))
        correct += int(votes.max()) if votes.size else 0
    return correct / max(int(speech.sum()), 1)
