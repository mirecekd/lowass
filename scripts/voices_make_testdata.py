# scripts/voices_make_testdata.py
"""Test corpus for scripts/voices.py: a conversation of 5 different Amazon Polly voices, 16 kHz mono wav + ground truth.

  python -m scripts.voices_make_testdata --out /tmp/lowass-voices --name mix --set 0
  python -m scripts.voices_make_testdata --out /tmp/lowass-voices --name mix2 --set 1

Writes <out>/<name>.wav and <out>/<name>.truth.json ([[start, end, speaker], ...]). Uses boto3 with the AWS profile
'ai' (never keys). Both sets use the same voices and different sentences."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

RATE = 16000
GAP_SECONDS = 0.3
VOICES = [("Joanna", "en-US"), ("Matthew", "en-US"), ("Amy", "en-GB"), ("Brian", "en-GB"), ("Kendra", "en-US")]
SENTENCES = [
    [
        "Good morning everyone, thanks for joining the call today.",
        "Hi, I have finished the first draft of the migration plan and shared it yesterday evening.",
        "Great. Did you have time to look at the cost estimate for the new cluster?",
        "Not yet, I will go through it this afternoon and send my comments before five.",
        "I think the schedule is too tight, we need at least two more weeks for testing.",
        "That is a fair point, let us move the release to the end of the month.",
        "Agreed, and please do not forget the security review, it always takes longer than expected.",
        "I can take that one, the auditors already know our setup from last year.",
        "Perfect, then we are done with this topic and can move to the budget.",
        "The budget is unchanged, but the vendor asked for a small increase starting in January.",
        "We should negotiate that, other suppliers offer the same service for less money.",
        "I will prepare a comparison table and bring it to the next meeting.",
        "Thank you all, see you on Thursday, and have a nice day.",
        "Bye bye, talk to you soon.",
        "Have a good one, everybody.",
    ],
    [
        "Welcome back, let us start with a short summary of last week.",
        "The deployment went fine, only one test failed and it was fixed within an hour.",
        "Good to hear. What about the customer complaints about the slow dashboard?",
        "We found the reason, a missing index in the database, and the change is already in production.",
        "I would still like to add monitoring, so that we notice such problems earlier.",
        "That makes sense, I can set up alerts for the response time by tomorrow.",
        "Please also write a short document for the support team, they keep asking the same questions.",
        "Sure, I will do it together with the new colleague who joins on Monday.",
        "Excellent, and the last item is the training day in March.",
        "The room is booked, but we still need to confirm the catering.",
        "I will call the restaurant this afternoon and let you know the price.",
        "Wonderful, then I think we have everything covered.",
        "Thanks, that was a quick one.",
        "See you all next week.",
        "Goodbye everyone.",
    ],
]


def synthesize(session, voice: str, language: str, text: str) -> np.ndarray:
    polly = session.client("polly")
    reply = polly.synthesize_speech(Text=text, VoiceId=voice, LanguageCode=language, Engine="neural", OutputFormat="pcm", SampleRate="16000")
    return np.frombuffer(reply["AudioStream"].read(), dtype="<i2").astype(np.float32) / 32768.0


def build(session, sentences: list[str]) -> tuple[np.ndarray, list[list]]:
    gap = np.zeros(int(GAP_SECONDS * RATE), dtype=np.float32)
    chunks: list[np.ndarray] = []
    truth: list[list] = []
    cursor = 0.0
    order = [0, 1, 2, 3, 4, 1, 0, 3, 2, 4, 1, 3, 0, 2, 4]
    for index, text in zip(order, sentences, strict=True):
        voice, language = VOICES[index]
        audio = synthesize(session, voice, language, text)
        truth.append([round(cursor, 3), round(cursor + len(audio) / RATE, 3), voice])
        chunks += [audio, gap]
        cursor += len(audio) / RATE + GAP_SECONDS
    return np.concatenate(chunks), truth


def main(argv: list[str] | None = None) -> None:
    import boto3  # pyright: ignore[reportMissingImports]
    import soundfile as sf  # pyright: ignore[reportMissingImports]

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="output folder")
    ap.add_argument("--name", default="mix")
    ap.add_argument("--set", type=int, default=0, choices=range(len(SENTENCES)), help="which sentence set to speak")
    ap.add_argument("--region", default="eu-central-1")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    audio, truth = build(boto3.Session(profile_name="ai", region_name=args.region), SENTENCES[args.set])
    sf.write(str(out / f"{args.name}.wav"), audio, RATE, subtype="PCM_16")
    (out / f"{args.name}.truth.json").write_text(json.dumps(truth), encoding="utf-8")
    print(f"{out / args.name}.wav: {len(audio) / RATE:.1f} s, {len(truth)} turns")


if __name__ == "__main__":
    main()
