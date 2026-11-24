# scripts/voices_match.py
"""Name the voices of a recording by the mute timeline: a person can only speak while unmuted.

  python -m scripts.voices_match --wav data/rec-X.wav --timeline data/meeting-Y.jsonl [--num-speakers N]

The wav needs a sidecar json with the same base name (rec-X.json) holding start_epoch. Prints a table
voice -> name with confidence, then a timeline of the diarized segments. Everything stays on this machine.

Confidence of a voice = (evidence of its assigned name - evidence the best alternative would have)
/ total evidence of the voice, see scripts/voices_match_core.assign."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import voices_core as core
from scripts import voices_match_core as match_core
from scripts.voices_engine import (
    DEFAULT_EMBEDDING,
    EMBEDDINGS,
    SAMPLE_RATE,
    check_models,
    diarize,
    load_audio,
)


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="voices_match", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wav", type=Path, required=True, help="16 kHz mono recording with a sidecar json next to it")
    ap.add_argument("--timeline", type=Path, required=True, help="jsonl of mute/presence state changes")
    ap.add_argument("--num-speakers", type=int, default=-1, help="known number of voices (default: let the clustering decide)")
    ap.add_argument("--cluster-threshold", type=float, default=0.5, help="clustering threshold, smaller = more voices")
    ap.add_argument("--min-confidence", type=float, default=0.5, help="a voice with a lower confidence is shown as unknown")
    ap.add_argument("--embedding", choices=sorted(EMBEDDINGS), default=DEFAULT_EMBEDDING, help="speaker embedding model")
    return ap.parse_args(argv)


def read_start_epoch(wav: Path) -> float:
    sidecar = wav.with_suffix(".json")
    if not sidecar.exists():
        raise SystemExit(f"sidecar {sidecar} is missing, it holds start_epoch of the recording")
    return float(json.loads(sidecar.read_text(encoding="utf-8"))["start_epoch"])


def name_of(match: match_core.Match, names: list[str]) -> str:
    return names[match.col] if match.known and match.col is not None else core.UNKNOWN


def print_table(segments: list[core.Segment], names: list[str], speakers: list[int | str], matches: list[match_core.Match]) -> None:
    stats = core.speaker_stats(segments)
    print(f"{'voice':<7}{'name':<14}{'confidence':>11}{'evidence s':>12}{'speech s':>10}  runner-up")
    for m in matches:
        voice = speakers[m.row]
        runner = names[m.runner_up] if m.runner_up is not None else "-"
        print(f"{voice!s:<7}{name_of(m, names):<14}{m.confidence:>11.2f}{m.evidence:>12.1f}{stats[voice][0]:>10.1f}  {runner}")


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    start_epoch = read_start_epoch(args.wav)
    check_models(args.embedding)
    audio = load_audio(str(args.wav))
    segments = core.merge_segments(diarize(audio, args.embedding, args.num_speakers, args.cluster_threshold))
    intervals = match_core.load_timeline(args.timeline, start_epoch, len(audio) / SAMPLE_RATE)
    names, speakers, matrix = match_core.evidence_matrix(segments, intervals)
    matches = match_core.assign(matrix, args.min_confidence)
    print_table(segments, names, speakers, matches)
    labels = {speakers[m.row]: name_of(m, names) for m in matches}
    print()
    for seg in segments:
        label = labels[seg.speaker]
        print(f"[{core.fmt_time(seg.start)}] {label if label != core.UNKNOWN else f'unknown (voice {seg.speaker})'}: ({seg.duration:.1f}s)")


if __name__ == "__main__":
    main()
