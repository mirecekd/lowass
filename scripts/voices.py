# scripts/voices.py
"""Spike: tell the voices of a recording apart, name them, recognise them later. Offline, CPU, sherpa-onnx.

  python -m scripts.voices --download                                   models into ~/.cache/lowass/models
  python -m scripts.voices --analyze call.wav [--num-speakers 5]        "I hear K voices" + the clearest segments
  python -m scripts.voices --name call.wav --profile people.json        asks who is voice 0, 1, ... and saves voiceprints
  python -m scripts.voices --identify other.wav --profile people.json   timeline with the names from the profile

Segments shorter than --min-seconds are too short for a reliable voiceprint and are labelled unknown."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from scripts import voices_core as core
from scripts.voices_engine import (
    DEFAULT_EMBEDDING,
    EMBEDDINGS,
    Embedder,
    check_models,
    diarize,
    download,
    load_audio,
)


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="voices", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--download", action="store_true", help="download the models and exit")
    ap.add_argument("--analyze", metavar="WAV", help="how many voices are in the file")
    ap.add_argument("--name", metavar="WAV", help="analyze, ask who is who, save the voiceprints to --profile")
    ap.add_argument("--identify", metavar="WAV", help="timeline of who speaks when, using --profile")
    ap.add_argument("--profile", type=Path, help="profile json file")
    ap.add_argument("--num-speakers", type=int, default=-1, help="known number of voices (default: let the clustering decide)")
    ap.add_argument("--cluster-threshold", type=float, default=0.5, help="clustering threshold, smaller = more voices")
    ap.add_argument("--threshold", type=float, default=0.6, help="--identify: minimal cosine similarity, else unknown")
    ap.add_argument("--min-seconds", type=float, default=1.0, help="shortest segment used for a voiceprint")
    ap.add_argument("--embedding", choices=sorted(EMBEDDINGS), default=DEFAULT_EMBEDDING, help="speaker embedding model")
    args = ap.parse_args(argv)
    if (args.name or args.identify) and not args.profile:
        ap.error("--name and --identify need --profile")
    return args


def report(segments: list[core.Segment]) -> None:
    stats = core.speaker_stats(segments)
    print(f"I hear {len(stats)} voices")
    for speaker, (total, count) in sorted(stats.items()):
        best = ", ".join(core.fmt_range(s) for s in core.longest(segments, speaker))
        print(f"  voice {speaker}: {total:.1f} s speaking, {count} segments, longest: {best}")


def voiceprints(audio: np.ndarray, segments: list[core.Segment], embedder: Embedder, min_seconds: float) -> dict[int | str, np.ndarray]:
    """Mean embedding per voice from its segments that are long enough."""
    result: dict[int | str, np.ndarray] = {}
    for speaker in sorted({s.speaker for s in segments}, key=str):
        own = [s for s in segments if s.speaker == speaker and s.duration >= min_seconds]
        if own:
            result[speaker] = core.mean_embedding([embedder.embed(audio, s) for s in own], [s.duration for s in own])
    return result


def run_name(args: argparse.Namespace, audio: np.ndarray, segments: list[core.Segment]) -> None:
    prints = voiceprints(audio, segments, Embedder(args.embedding), args.min_seconds)
    profile = core.load_profile(args.profile)
    for speaker, vector in prints.items():
        name = input(f"Who is voice {speaker}? (Enter = skip) ").strip()
        if name:
            profile[name] = vector
    core.save_profile(args.profile, profile, args.embedding)
    print(f"saved {len(profile)} named voices to {args.profile}: {', '.join(profile)}")


def run_identify(args: argparse.Namespace, audio: np.ndarray, segments: list[core.Segment]) -> None:
    profile = core.load_profile(args.profile)
    embedder = Embedder(args.embedding)
    for seg in segments:
        name, score = core.match_voice(embedder.embed(audio, seg), profile, args.threshold) if seg.duration >= args.min_seconds else (core.UNKNOWN, 0.0)
        print(f"[{core.fmt_time(seg.start)}] {name}: ({seg.duration:.1f}s)  similarity {score:.2f}")


def main(argv: list[str] | None = None) -> None:
    args = parse(argv)
    if args.download:
        download(args.embedding)
        return
    wav = args.analyze or args.name or args.identify
    if not wav:
        raise SystemExit("nothing to do, see --help")
    check_models(args.embedding)
    audio = load_audio(wav)
    segments = core.merge_segments(diarize(audio, args.embedding, args.num_speakers, args.cluster_threshold))
    if args.identify:
        run_identify(args, audio, segments)
        return
    report(segments)
    if args.name:
        run_name(args, audio, segments)


if __name__ == "__main__":
    main()
