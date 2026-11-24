# scripts/voices_eval.py
"""Score scripts/voices.py against the ground truth made by voices_make_testdata.

  python -m scripts.voices_eval purity /tmp/lowass-voices/mix --thresholds 0.3 0.4 0.5 0.6 0.7
  python -m scripts.voices_eval answers /tmp/lowass-voices/mix [--num-speakers 5]   prints the stdin for --name
  python -m scripts.voices_eval identify /tmp/lowass-voices/mix2 people.json        per truth turn: who was heard

<base> is the path of the wav without .wav; <base>.truth.json sits next to it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts import voices_core as core
from scripts.voices import voiceprints
from scripts.voices_engine import (
    DEFAULT_EMBEDDING,
    EMBEDDINGS,
    Embedder,
    diarize,
    load_audio,
)


def load_truth(base: str) -> list[core.Segment]:
    try:
        rows = json.loads(Path(base + ".truth.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"cannot read {base}.truth.json: {exc}") from exc
    return [core.Segment(a, b, who) for a, b, who in rows]


def dominant(seg: core.Segment, truth: list[core.Segment]) -> str:
    """The truth speaker that overlaps seg the most."""
    overlap: dict[str, float] = {}
    for t in truth:
        shared = min(seg.end, t.end) - max(seg.start, t.start)
        if shared > 0:
            overlap[str(t.speaker)] = overlap.get(str(t.speaker), 0.0) + shared
    return max(overlap, key=lambda k: overlap[k]) if overlap else core.UNKNOWN


def cmd_purity(args: argparse.Namespace) -> None:
    audio, truth = load_audio(args.base + ".wav"), load_truth(args.base)
    for threshold in args.thresholds:
        segs = diarize(audio, args.embedding, args.num_speakers, threshold)
        print(f"threshold {threshold}: {len({s.speaker for s in segs})} voices, purity {core.purity(truth, segs):.3f}")


def cmd_answers(args: argparse.Namespace) -> None:
    """For --name: the true name of every voice (the truth speaker it overlaps most), in the order --name asks."""
    audio, truth = load_audio(args.base + ".wav"), load_truth(args.base)
    segs = core.merge_segments(diarize(audio, args.embedding, args.num_speakers, args.cluster_threshold))
    for speaker in voiceprints(audio, segs, Embedder(args.embedding), 1.0):
        own = [s for s in segs if s.speaker == speaker]
        votes = [dominant(s, truth) for s in own for _ in range(max(1, int(s.duration)))]
        print(max(set(votes), key=votes.count))


def cmd_identify(args: argparse.Namespace) -> None:
    """Per segment: the oracle one (the true turns) and the real one (what the diarization found)."""
    audio, truth = load_audio(args.base + ".wav"), load_truth(args.base)
    profile = core.load_profile(args.profile)
    embedder = Embedder(args.embedding)
    found = core.merge_segments(diarize(audio, args.embedding, -1, args.cluster_threshold))
    for label, segs in ("true turns", truth), ("diarized segments", found):
        right = 0
        for seg in segs:
            name, score = core.match_voice(embedder.embed(audio, seg), profile, args.threshold)
            want = dominant(seg, truth)
            right += name == want
            print(f"  [{core.fmt_time(seg.start)}] {seg.duration:4.1f}s truth {want:8} heard {name:8} sim {score:.2f} {'ok' if name == want else 'WRONG'}")
        print(f"{label}: identification accuracy {right}/{len(segs)} at threshold {args.threshold}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--embedding", choices=sorted(EMBEDDINGS), default=DEFAULT_EMBEDDING, help="before the subcommand")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("purity")
    p.add_argument("base")
    p.add_argument("--thresholds", type=float, nargs="+", default=[0.5])
    p.add_argument("--num-speakers", type=int, default=-1)
    p.set_defaults(run=cmd_purity)
    a = sub.add_parser("answers")
    a.add_argument("base")
    a.add_argument("--num-speakers", type=int, default=-1)
    a.add_argument("--cluster-threshold", type=float, default=0.5)
    a.set_defaults(run=cmd_answers)
    i = sub.add_parser("identify")
    i.add_argument("base")
    i.add_argument("profile", type=Path)
    i.add_argument("--threshold", type=float, default=0.6)
    i.add_argument("--cluster-threshold", type=float, default=0.5)
    i.set_defaults(run=cmd_identify)
    args = ap.parse_args(argv)
    args.run(args)


if __name__ == "__main__":
    main()
